# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Upload orchestrator for NAPT Intune deployment.

Coordinates the full upload pipeline: loading recipe config, locating the
package of the recorded release, verifying it, authenticating, parsing the
.intunewin file, building app metadata, and executing the Graph API upload
flow.

The package is found through deployment state and the build manifest,
never by guessing: the version comes from the recorded release (pending,
else published), the manifest names the .intunewin file and the scripts,
and the .intunewin is re-hashed against what ``napt package`` recorded
before anything is sent.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
import functools
from pathlib import Path
import tempfile
from typing import Any

from napt.auth.credentials import get_access_token
from napt.build.manifest import read_build_manifest
from napt.config.loader import load_effective_config
from napt.download.download import sha256_file
from napt.exceptions import ConfigError, PackagingError
from napt.graph.intune import (
    MAX_ICON_BYTES,
    commit_content_version,
    commit_content_version_file,
    create_content_version,
    create_content_version_file,
    create_win32_app,
    delete_mobile_app,
    get_mobile_app,
    list_mobile_apps,
    update_win32_app,
    upload_to_azure_blob,
)
from napt.logging import Logger, get_global_logger
from napt.state.deployment import (
    deployment_state_path,
    load_deployment_state,
    record_published,
    save_deployment_state,
    working_release_of,
)
from napt.state.stamp import (
    ENTRY_INSTALL,
    ENTRY_UPDATE,
    build_stamp,
    find_stamped_app,
)
from napt.upload.intunewin import (
    IntunewinMetadata,
    extract_encrypted_payload,
    parse_intunewin,
)

# Intune return codes for PSADT deployments.
# 0    - success: clean install/uninstall
# 1707 - success: removal succeeded (used by some uninstallers)
# 3010 - softReboot: restart required but not yet initiated
# 1641 - hardReboot: restart already initiated (ERROR_SUCCESS_REBOOT_INITIATED)
# 1618 - retry: another installer is already running
_RETURN_CODES = [
    {
        "@odata.type": "microsoft.graph.win32LobAppReturnCode",
        "returnCode": 0,
        "type": "success",
    },
    {
        "@odata.type": "microsoft.graph.win32LobAppReturnCode",
        "returnCode": 1707,
        "type": "success",
    },
    {
        "@odata.type": "microsoft.graph.win32LobAppReturnCode",
        "returnCode": 3010,
        "type": "softReboot",
    },
    {
        "@odata.type": "microsoft.graph.win32LobAppReturnCode",
        "returnCode": 1641,
        "type": "hardReboot",
    },
    {
        "@odata.type": "microsoft.graph.win32LobAppReturnCode",
        "returnCode": 1618,
        "type": "retry",
    },
]

# Maps recipe architecture to the allowedArchitectures Graph API field value.
# Per the Graph API docs, setting allowedArchitectures to a non-null value
# causes the server to automatically set applicableArchitectures to "none",
# so we omit applicableArchitectures and drive targeting through
# allowedArchitectures only.
#
# Defaults reflect Windows binary compatibility, not just installer architecture:
#   x86  → x86,x64,ARM64  (WOW64 is universal; all Windows runs x86 binaries)
#   x64  → x64,ARM64      (ARM64 Windows 11 supports x64 emulation natively)
#   arm64 → ARM64          (native ARM64 binary; not compatible with x64 devices)
#   any  → null           (no restriction; applicableArchitectures becomes "none")
_ARCH_MAP: dict[str, str | None] = {
    "x86": "x86,x64,ARM64",
    "x64": "x64,ARM64",
    "arm64": "ARM64",
    "any": None,
}


def _locate_package_dir(
    packages_dir: Path, app_id: str, release: dict[str, Any] | None
) -> Path:
    """Finds the versioned package directory for the release to upload.

    The version comes from the recorded release, so every machine with
    the state file picks the same folder. With no recorded release, the
    only package is used; several packages then need a recorded release,
    since picking one by modification time would upload whichever was
    touched last.

    Args:
        packages_dir: Root packages directory (``directories.package``).
        app_id: Application identifier (from recipe app.id).
        release: The recorded release from deployment state, or None.

    Returns:
        The version directory ``{packages_dir}/{app_id}/{version}/``.

    Raises:
        ConfigError: If no package directory exists for the app, the
            recorded release was never packaged, or several packages exist
            and none is recorded.

    """
    app_package_dir = packages_dir / app_id

    if not app_package_dir.is_dir():
        raise ConfigError(
            f"No package found for '{app_id}' in {packages_dir}. "
            "Run 'napt package' first."
        )

    if release is not None:
        version_dir = app_package_dir / release["version"]
        if not (version_dir / "build-manifest.json").is_file():
            raise ConfigError(
                f"Deployment state records release {release['version']} for "
                f"'{app_id}', but there is no package of it in "
                f"{app_package_dir}. Run 'napt package' first."
            )
        return version_dir

    version_dirs = sorted(
        d for d in app_package_dir.iterdir() if (d / "build-manifest.json").is_file()
    )
    if not version_dirs:
        raise ConfigError(
            f"No packaged version found for '{app_id}' in {app_package_dir}. "
            "Run 'napt package' first."
        )
    if len(version_dirs) > 1:
        names = ", ".join(d.name for d in version_dirs)
        raise ConfigError(
            f"'{app_id}' has no recorded release and several packages ({names}). "
            "Run 'napt discover' to record the release, then 'napt package'."
        )
    return version_dirs[0]


def _verify_package_file(package_dir: Path, manifest: dict[str, Any]) -> Path:
    """Finds the .intunewin the manifest names and checks it is unchanged.

    Args:
        package_dir: Versioned package directory.
        manifest: The package's manifest.

    Returns:
        Path to the .intunewin file.

    Raises:
        PackagingError: If the file is missing or its hash differs from
            the one 'napt package' recorded.

    """
    package_path = package_dir / manifest["intunewin_filename"]
    if not package_path.is_file():
        raise PackagingError(
            f"{package_path} is missing. Run 'napt package' to recreate the package."
        )
    actual = sha256_file(package_path)
    if actual != manifest["intunewin_sha256"]:
        raise PackagingError(
            f"The .intunewin in {package_dir} does not match the hash "
            f"'napt package' recorded (expected {manifest['intunewin_sha256']}, "
            f"found {actual}). Run 'napt package' to recreate the package."
        )
    return package_path


def _load_icon_bytes(path: Path, logger: Logger) -> bytes | None:
    """Reads an icon file, warning instead of raising on failure.

    Args:
        path: Icon file to read.
        logger: Logger for warnings.

    Returns:
        The file bytes, or None if the file is unreadable or larger than
            Intune's icon size limit.
    """
    try:
        data = path.read_bytes()
    except OSError as err:
        logger.warning("UPLOAD", f"Could not read icon file {path}: {err}.")
        return None
    if len(data) > MAX_ICON_BYTES:
        logger.warning(
            "UPLOAD",
            f"Icon file {path} is {len(data) // 1000}KB, over Intune's "
            f"{MAX_ICON_BYTES // 1000}KB icon size limit. Replace it with a "
            f"smaller image (256x256 PNG recommended).",
        )
        return None
    return data


def _resolve_large_icon(config: dict[str, Any]) -> dict[str, Any] | None:
    """Resolves the largeIcon content for an app's Intune entries.

    Resolution order: intune.logo_path (explicit, always wins), then the
    icon extracted at build time to ``{directories.icons}/{id}.png``, then
    no icon with a warning. Unreadable and oversized icon files warn and
    are skipped; a broken logo_path only falls back when an extracted icon
    actually exists.

    Args:
        config: Effective configuration dict from load_effective_config.

    Returns:
        A mimeContent dict for the payload's largeIcon field, or None when
            no icon is available.
    """
    logger = get_global_logger()
    intune: dict[str, Any] = config["intune"]
    icon_path = Path(config["directories"]["icons"]) / f"{config['id']}.png"

    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    logo_path_str: str = intune.get("logo_path", "")
    if logo_path_str:
        logo_path = Path(logo_path_str)
        mime_type = mime_types.get(logo_path.suffix.lower())
        # Build skips extraction when logo_path is set, so an extracted
        # icon only exists here if it predates the logo_path setting.
        fallback = (
            "Falling back to the extracted icon"
            if icon_path.exists()
            else "The Intune app entry will have no logo; fix intune.logo_path, "
            "or unset it and run 'napt build' to extract an icon"
        )
        if not logo_path.exists():
            logger.warning("UPLOAD", f"Logo file not found: {logo_path}. {fallback}.")
        elif mime_type is None:
            logger.warning(
                "UPLOAD",
                f"Unsupported logo file type '{logo_path.suffix}' for "
                f"{logo_path.name}; use .png or .jpg. {fallback}.",
            )
        else:
            logo_bytes = _load_icon_bytes(logo_path, logger)
            if logo_bytes is not None:
                logger.verbose(
                    "UPLOAD", f"App icon: {logo_path.name} (intune.logo_path)"
                )
                return {
                    "type": mime_type,
                    "value": base64.b64encode(logo_bytes).decode(),
                }

    if icon_path.exists():
        icon_bytes = _load_icon_bytes(icon_path, logger)
        if icon_bytes is None:
            return None
        logger.verbose("UPLOAD", f"App icon: {icon_path} (extracted at build time)")
        return {"type": "image/png", "value": base64.b64encode(icon_bytes).decode()}

    if not logo_path_str:
        logger.warning(
            "UPLOAD",
            f"No app icon found for '{config['id']}'. The Intune app entry "
            f"will have no logo. Run 'napt build' to extract one, place a PNG "
            f"at {icon_path}, or set intune.logo_path.",
        )
    return None


_MANIFEST_REMEDY = "Run 'napt build' and 'napt package' to recreate the package."


def _read_build_manifest(package_dir: Path) -> dict[str, Any]:
    """Reads and validates the build manifest from a package directory.

    Args:
        package_dir: Versioned package directory containing
            build-manifest.json (copied there by 'napt package').

    Returns:
        The parsed build manifest.

    Raises:
        PackagingError: If the manifest is missing, not JSON, or lacks a
            field upload relies on (architecture, installer hash, build
            types, script and package names).

    """
    manifest = read_build_manifest(
        package_dir,
        (
            "win32_build_types",
            "detection_script_path",
            "intunewin_filename",
            "intunewin_sha256",
            "architecture",
            "installer_sha256",
        ),
        _MANIFEST_REMEDY,
    )
    if manifest["architecture"] not in _ARCH_MAP:
        raise PackagingError(
            f"Unrecognized architecture '{manifest['architecture']}' in the "
            f"build manifest in {package_dir}. Expected one of: "
            f"{', '.join(_ARCH_MAP)}. {_MANIFEST_REMEDY}"
        )
    return manifest


def _build_app_metadata(
    config: dict[str, Any],
    recipe_path: Path,
    version: str,
    package_path: Path,
    entry: str,
    manifest: dict[str, Any],
    large_icon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Win32LobApp JSON payload for the Graph API.

    Assembles the app creation body from recipe config, optional intune:
    overrides, detection/requirements PS1 scripts, and PSADT invariants.
    Scripts are read from the package directory (copied there by 'napt package'),
    so this function does not access the builds directory.

    The payload's notes field carries the NAPT provenance stamp
    (``napt/v1 id=<recipe-id> entry=<install|update> sha256=<installer-hash>``),
    which marks the app as NAPT-managed and ties it to the exact binary it
    was built from. The field is reserved for NAPT and is not
    recipe-configurable.

    Args:
        config: Effective configuration dict from load_effective_config.
        recipe_path: Path to the recipe file (used to infer vendor/publisher).
        version: Application version string (from package directory name).
        package_path: Path to the .intunewin file (e.g.,
            packages/google-chrome/<version>/Invoke-AppDeployToolkit.intunewin).
        entry: ``ENTRY_INSTALL`` (detection script only) or ``ENTRY_UPDATE``
            (detection and requirements scripts).
        manifest: Parsed build manifest from
            [_read_build_manifest][napt.upload.manager._read_build_manifest].
        large_icon: Resolved largeIcon mimeContent from
            [_resolve_large_icon][napt.upload.manager._resolve_large_icon],
            or None to omit the icon.

    Returns:
        Dict ready to POST to the Graph API mobileApps endpoint.

    Raises:
        ConfigError: If the detection script is missing, or the requirements
            script is missing when build_types is "update_only". Run
            'napt build' and 'napt package' to recreate the package.

    """
    logger = get_global_logger()
    package_dir = package_path.parent
    intune: dict[str, Any] = config["intune"]

    base_name: str = config["name"]
    if entry == ENTRY_UPDATE:
        prefix: str = intune["update_name_prefix"]
        display_name = f"{prefix}{base_name}"
    else:
        display_name = base_name
    # --- Optional Intune metadata (absent-means-skip) ---
    publisher: str = intune.get("publisher") or recipe_path.parent.name
    description: str = intune.get("description", "")
    privacy_url: str = intune.get("privacy_url", "")
    info_url: str = intune.get("info_url", "")

    allowed_architectures: str | None = _ARCH_MAP[manifest["architecture"]]

    # Detection script (always required), the one the manifest names
    detection_script = package_dir / manifest["detection_script_path"]
    if not detection_script.is_file():
        raise ConfigError(
            f"Detection script {detection_script.name} not found in "
            f"{package_dir}. Run 'napt package' to recreate the package."
        )
    detection_content = base64.b64encode(detection_script.read_bytes()).decode()
    logger.verbose("UPLOAD", f"Detection script: {detection_script.name}")

    enforce_sig: bool = intune["enforce_signature_check"]
    run_as_32_bit: bool = intune["run_as_32_bit"]
    run_as_account: str = intune["run_as_account"]

    rules: list[dict[str, Any]] = [
        {
            "@odata.type": "#microsoft.graph.win32LobAppPowerShellScriptRule",
            "ruleType": "detection",
            "enforceSignatureCheck": enforce_sig,
            "runAs32Bit": run_as_32_bit,
            "scriptContent": detection_content,
        }
    ]

    # Requirements script (update entries only), the one the manifest names
    if entry == ENTRY_UPDATE:
        req_name = manifest.get("requirements_script_path")
        req_script = package_dir / req_name if isinstance(req_name, str) else None
        if req_script is None or not req_script.is_file():
            raise ConfigError(
                f"Requirements script not found in {package_dir} "
                "(when build_types is "
                "'both' or 'update_only'). "
                "Run 'napt build' and 'napt package' to recreate the package."
            )
        req_content = base64.b64encode(req_script.read_bytes()).decode()
        logger.verbose("UPLOAD", f"Requirements script: {req_script.name}")
        rules.append(
            {
                "@odata.type": "#microsoft.graph.win32LobAppPowerShellScriptRule",
                "displayName": req_script.name,
                "ruleType": "requirement",
                "enforceSignatureCheck": enforce_sig,
                "runAs32Bit": run_as_32_bit,
                "runAsAccount": run_as_account,
                "scriptContent": req_content,
                "operationType": "string",
                "operator": "equal",
                "comparisonValue": "Required",
            }
        )

    install_command: str = intune["install_command"]
    uninstall_command: str = intune["uninstall_command"]
    minimum_windows_release: str = intune["minimum_supported_windows_release"]

    is_featured: bool = intune["is_featured"]
    allow_available_uninstall: bool = intune["allow_available_uninstall"]
    device_restart_behavior: str = intune["device_restart_behavior"]
    max_run_time_minutes: int = intune["max_run_time_minutes"]

    payload: dict[str, Any] = {
        "@odata.type": "#microsoft.graph.win32LobApp",
        "displayName": display_name,
        "displayVersion": version,
        "publisher": publisher,
        "description": description,
        "privacyInformationUrl": privacy_url,
        "informationUrl": info_url,
        "isFeatured": is_featured,
        "allowAvailableUninstall": allow_available_uninstall,
        "roleScopeTagIds": [],
        "runAs32Bit": run_as_32_bit,
        "fileName": package_path.name,
        "minimumSupportedWindowsRelease": minimum_windows_release,
        "installExperience": {
            "runAsAccount": run_as_account,
            "deviceRestartBehavior": device_restart_behavior,
            "maxRunTimeInMinutes": max_run_time_minutes,
        },
        "returnCodes": _RETURN_CODES,
        "rules": rules,
        "allowedArchitectures": allowed_architectures,
        "setupFilePath": "Invoke-AppDeployToolkit.exe",
        "installCommandLine": install_command,
        "uninstallCommandLine": uninstall_command,
    }

    # Optional fields: developer, owner
    if intune.get("developer"):
        payload["developer"] = intune["developer"]
    if intune.get("owner"):
        payload["owner"] = intune["owner"]

    # Provenance stamp: marks the app as NAPT-managed and ties it to the
    # exact binary it was built from. The notes field is reserved for NAPT.
    payload["notes"] = build_stamp(config["id"], entry, manifest["installer_sha256"])

    # Optional: app icon (largeIcon), resolved once per upload
    if large_icon is not None:
        payload["largeIcon"] = large_icon

    return payload


def _upload_app_content(
    access_token: str,
    intune_app_id: str,
    payload: Callable[[], Path],
    intunewin_metadata: IntunewinMetadata,
    step_upload: int,
    step_commit: int,
    total_steps: int,
) -> None:
    """Uploads and commits the encrypted payload for one app record.

    Args:
        access_token: Azure AD bearer token for Graph API calls.
        intune_app_id: Graph API object ID of the app record.
        payload: Returns the extracted encrypted payload, extracting it on
            first use so the install and update entries share one copy.
        intunewin_metadata: Parsed encryption metadata from parse_intunewin.
        step_upload: Step number to display when uploading to Blob Storage.
        step_commit: Step number to display when committing.
        total_steps: Total step count for progress display.

    """
    logger = get_global_logger()

    cv_id = create_content_version(access_token, intune_app_id)
    logger.verbose("UPLOAD", f"Content version: {cv_id}")

    file_id, sas_uri = create_content_version_file(
        access_token, intune_app_id, cv_id, intunewin_metadata
    )
    logger.verbose("UPLOAD", f"File entry: {file_id}")

    logger.step(step_upload, total_steps, "Uploading to Azure Blob Storage...")
    upload_to_azure_blob(sas_uri, payload())

    logger.step(step_commit, total_steps, "Committing content version...")
    commit_content_version_file(
        access_token, intune_app_id, cv_id, file_id, intunewin_metadata
    )
    commit_content_version(access_token, intune_app_id, cv_id)


def _upload_single_app(
    access_token: str,
    app_metadata: dict[str, Any],
    payload: Callable[[], Path],
    intunewin_metadata: IntunewinMetadata,
    existing_apps: list[dict[str, Any]],
    recipe_id: str,
    entry: str,
    installer_sha256: str,
    step_create: int,
    step_upload: int,
    step_commit: int,
    total_steps: int,
    force: bool = False,
) -> str:
    """Publish one Intune Win32 app entry, reusing an existing stamped app.

    Reconcile-before-act: when a NAPT-stamped app already matches this
    publish instance (recipe id, entry type, installer hash), the app is
    adopted instead of duplicated: skipped entirely if its content is
    committed, or deleted and recreated if a previous run crashed between
    app creation and commit (Intune refuses new content versions for an
    app whose first content version was never committed, so such an
    orphan cannot be resumed in place). Otherwise the app record is
    created and its content uploaded and committed.

    Adoption does not re-send app metadata or content: a matched app keeps
    whatever it already has, even if the recipe or package changed since it
    was published (the match key is the installer binary, not the package).
    Pass force=True to upload a fresh content version and then update the
    matched app's metadata instead of adopting.

    Args:
        access_token: Azure AD bearer token for Graph API calls.
        app_metadata: Win32LobApp JSON payload from _build_app_metadata.
        payload: Returns the extracted encrypted payload, extracting it on
            first use; an adopted entry never calls it.
        intunewin_metadata: Parsed encryption metadata from parse_intunewin.
        existing_apps: Mobile app dicts from list_mobile_apps.
        recipe_id: Recipe identifier for stamp matching.
        entry: Entry type for stamp matching ("install" or "update").
        installer_sha256: Installer hash for stamp matching.
        step_create: Step number to display when creating the app record.
        step_upload: Step number to display when uploading to Blob Storage.
        step_commit: Step number to display when committing.
        total_steps: Total step count for progress display.
        force: When True, a matched app gets its metadata updated and a
            fresh content version uploaded instead of being adopted as-is.

    Returns:
        The Graph API object ID of the created or adopted Intune Win32 app.

    """
    logger = get_global_logger()
    display_name: str = app_metadata["displayName"]

    match = find_stamped_app(existing_apps, recipe_id, entry, installer_sha256)
    patch_metadata_after_content = False
    if match is not None:
        intune_app_id: str = match["id"]
        full_app = get_mobile_app(access_token, intune_app_id)
        if not full_app.get("committedContentVersion"):
            # Orphan from a run that crashed between app creation and
            # content commit. Intune rejects a contentVersions POST until
            # the first content version is committed, so replace the app
            # instead of resuming it.
            logger.step(
                step_create,
                total_steps,
                f"Recreating app record for '{display_name}'...",
            )
            delete_mobile_app(access_token, intune_app_id)
            logger.info(
                "UPLOAD",
                f"Deleted Intune app {intune_app_id}: a previous upload "
                "never committed its content",
            )
            intune_app_id = create_win32_app(access_token, app_metadata)
            logger.info("UPLOAD", f"Created Intune app: {intune_app_id}")
        elif force:
            logger.step(
                step_create,
                total_steps,
                f"Re-uploading existing app record for '{display_name}'...",
            )
            # The metadata PATCH must come after the content upload: Intune
            # rejects a contentVersions POST that closely follows an app
            # PATCH with HTTP 412 ConditionNotMet (stale internal ETag).
            patch_metadata_after_content = True
        else:
            logger.step(
                step_create,
                total_steps,
                f"Adopting existing app record for '{display_name}'...",
            )
            logger.info(
                "UPLOAD",
                f"Adopted Intune app: {intune_app_id} (content already committed)",
            )
            return intune_app_id
    else:
        logger.step(
            step_create, total_steps, f"Creating app record for '{display_name}'..."
        )
        intune_app_id = create_win32_app(access_token, app_metadata)
        logger.info("UPLOAD", f"Created Intune app: {intune_app_id}")

    _upload_app_content(
        access_token,
        intune_app_id,
        payload,
        intunewin_metadata,
        step_upload,
        step_commit,
        total_steps,
    )

    if patch_metadata_after_content:
        update_win32_app(access_token, intune_app_id, app_metadata)
        logger.info(
            "UPLOAD",
            f"Updated Intune app metadata: {intune_app_id} (--force)",
        )

    return intune_app_id


@dataclass(frozen=True)
class UploadResult:
    """Result from uploading a .intunewin package to Microsoft Intune.

    Attributes:
        app_id: Unique application identifier (from recipe).
        app_name: Application display name.
        version: Application version uploaded.
        intune_app_id: Graph API object ID of the install app entry.
            None when build_types is "update_only".
        intune_update_app_id: Graph API object ID of the update app entry.
            None when build_types is "app_only".
        package_path: Path to the uploaded .intunewin file.
    """

    app_id: str
    app_name: str
    version: str
    package_path: Path
    intune_app_id: str | None = None
    intune_update_app_id: str | None = None


def upload_package(
    recipe_path: Path,
    force: bool = False,
    *,
    state_dir: Path | None = None,
    packages_dir: Path | None = None,
) -> UploadResult:
    """Upload a packaged app to Microsoft Intune via the Graph API.

    Loads the recipe config, locates the package of the release deployment
    state records, verifies it, authenticates using the available Azure
    credential, parses encryption metadata from the package, and executes
    the full Graph API upload flow.

    When intune.build_types is "both" (the default), two Intune app entries are
    created: an install entry (detection script only) and an update entry
    (detection + requirements scripts). Each entry is created, uploaded, and
    committed in sequence before moving to the next. The recipe's
    build_types must be the one the package was built with.

    The package directory is packages/{app.id}/{version}/ for the recorded
    release (pending, else published), or the only package when none is
    recorded. Run 'napt package' before calling this function.

    Authentication needs no configuration file:

    - Developers: run 'napt auth login' once
    - CI/CD: set AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET, or use
        OIDC federation

    Before any Graph call, the .intunewin is re-hashed against what 'napt
    package' recorded, and the package's installer hash (from the build
    manifest) is verified against the pending release recorded in the app's
    deployment state, so what was recorded at discovery is byte-for-byte
    what ships. A hash mismatch aborts the upload. A package matching the
    published release (a re-run after writeback, or a --force refresh)
    passes too. When it matches neither, the upload proceeds with a
    warning, or fails when deployment.require_pending is enabled. On
    success, the deployment state records the published version, hash, and
    Intune app IDs, and a matching pending slot is cleared.

    Re-running an upload is safe: existing NAPT-stamped apps matching this
    publish instance (recipe id, entry type, installer hash) are adopted
    instead of duplicated; one whose content was never committed is deleted
    and recreated, so it gets a new app ID. Adoption keeps the app as it is;
    it does not re-send metadata or content. Pass force=True to update
    matched apps' metadata and upload a
    fresh content version (e.g., after changing PSADT commands or detection
    settings without a new installer release).

    Args:
        recipe_path: Path to the recipe YAML file.
        force: When True, matched stamped apps are re-uploaded (metadata
            and content) instead of adopted as-is. Never creates
            duplicates.
        state_dir: State root whose deployment/ folder records the
            release. If None, reads from config directories.state.
        packages_dir: Directory holding the packages. If None, reads from
            config directories.package.

    Returns:
        Upload result including the Intune app ID(s), app name, version, and
            package path. intune_app_id is None when build_types is "update_only";
            intune_update_app_id is None when build_types is "app_only".

    Raises:
        ConfigError: If the package of the recorded release is not found,
            several packages exist with none recorded, the manifest is
            unusable, the recipe's build_types differs from the package's,
            or a script the manifest names is missing. Run 'napt package'
            to create or recreate the package.
        AuthError: If all Azure credential methods fail.
        NetworkError: If Graph API or Azure Blob Storage calls fail.
        PackagingError: If the .intunewin file is malformed or no longer
            matches the hash 'napt package' recorded, the package's
            installer hash does not match the pending release in deployment
            state, or it matches neither pending nor published while
            deployment.require_pending is enabled.
        StateError: On a corrupted deployment state file.

    Example:
        Upload and print the resulting Intune app IDs:
            ```python
            from pathlib import Path
            from napt.upload.manager import upload_package

            result = upload_package(Path("recipes/Google/chrome.yaml"))
            print(f"Install app ID: {result.intune_app_id}")
            if result.intune_update_app_id:
                print(f"Update app ID: {result.intune_update_app_id}")
            ```

    """
    logger = get_global_logger()

    config = load_effective_config(recipe_path)
    app_id: str = config["id"]
    app_name: str = config["name"]
    build_types: str = config["intune"]["build_types"]

    logger.verbose("UPLOAD", f"Starting upload for '{app_name}' ({app_id})")
    logger.verbose("UPLOAD", f"build_types: {build_types}")

    # Resolve the app icon once; it is shared by the install and update entries
    large_icon = _resolve_large_icon(config)

    # Step 1: Locate the package of the recorded release and verify it
    total_steps = 9 if build_types == "both" else 6
    logger.step(1, total_steps, "Locating .intunewin package...")
    if state_dir is None:
        state_dir = Path(config["directories"]["state"])
    if packages_dir is None:
        packages_dir = Path(config["directories"]["package"])
    state_path = deployment_state_path(state_dir / "deployment", app_id)
    state = load_deployment_state(state_path)
    release = working_release_of(state)
    package_dir = _locate_package_dir(packages_dir, app_id, release)
    version = package_dir.name
    manifest = _read_build_manifest(package_dir)
    package_path = _verify_package_file(package_dir, manifest)
    installer_sha256: str = manifest["installer_sha256"]
    logger.verbose("UPLOAD", f"Package: {package_path}")
    logger.verbose("UPLOAD", f"Version: {version}")

    # The package was built for one build_types; the metadata below comes
    # from the recipe. They must agree, or one entry would be committed
    # before the other fails on a script the package does not hold.
    built_types: str = manifest["win32_build_types"]
    if built_types != build_types:
        raise ConfigError(
            f"The package of '{app_id}' was built with build_types "
            f"'{built_types}', but the recipe now says '{build_types}'. Run "
            "'napt build' and 'napt package' so the package matches the recipe."
        )

    # Verify provenance against deployment state before any Graph call:
    # what was recorded at discovery must be byte-for-byte what ships. A
    # package matching the published release is a re-run after writeback
    # or a --force refresh, and passes too.
    pending = state.get("pending")
    published = state.get("published")
    if pending:
        if pending.get("sha256") != installer_sha256:
            raise PackagingError(
                f"Installer hash mismatch for '{app_id}': the package was "
                f"built from a different binary than the pending release "
                f"recorded in {state_path}.\n"
                f"  pending:  {pending.get('version')} "
                f"(sha256 {pending.get('sha256')})\n"
                f"  package:  {version} (sha256 {installer_sha256})\n"
                "Re-run 'napt discover', 'napt build', and 'napt package' "
                "so the package matches the recorded release."
            )
        logger.info(
            "UPLOAD", f"Package matches pending release (sha256 {installer_sha256})"
        )
    elif published and published.get("sha256") == installer_sha256:
        logger.info(
            "UPLOAD",
            f"Package matches the published release (sha256 {installer_sha256})",
        )
    elif config["deployment"]["require_pending"]:
        raise PackagingError(
            f"No pending release recorded for '{app_id}' and "
            "deployment.require_pending is enabled, and the package does not "
            "match the published release.\n"
            "Run 'napt discover' to record the release, or add a pending "
            f"entry (version, sha256, url) to {state_path}."
        )
    else:
        logger.warning(
            "UPLOAD",
            f"No pending release recorded for '{app_id}'; uploading "
            "without provenance verification.",
        )

    # Step 2: Authenticate
    logger.step(2, total_steps, "Authenticating with Azure...")
    access_token = get_access_token()

    # Step 3: Parse .intunewin metadata
    logger.step(3, total_steps, "Parsing package metadata...")
    intunewin_metadata = parse_intunewin(package_path)

    # Reconcile-before-act: list existing apps once so stamped apps from a
    # previous (possibly crashed) run are adopted instead of duplicated.
    existing_apps = list_mobile_apps(access_token)
    logger.verbose("UPLOAD", f"Tenant has {len(existing_apps)} mobile apps")

    intune_app_id: str | None = None
    intune_update_app_id: str | None = None

    # The install and update entries upload the same bytes, so the package
    # is decrypted once, and only if an entry needs uploading at all.
    with tempfile.TemporaryDirectory() as tmp_dir:

        @functools.cache
        def payload() -> Path:
            return extract_encrypted_payload(package_path, Path(tmp_dir))

        if build_types in ("app_only", "both"):
            # Install entry: steps 4-6
            install_metadata = _build_app_metadata(
                config,
                recipe_path,
                version,
                package_path,
                ENTRY_INSTALL,
                manifest,
                large_icon,
            )
            intune_app_id = _upload_single_app(
                access_token,
                install_metadata,
                payload,
                intunewin_metadata,
                existing_apps,
                recipe_id=app_id,
                entry=ENTRY_INSTALL,
                installer_sha256=installer_sha256,
                step_create=4,
                step_upload=5,
                step_commit=6,
                total_steps=total_steps,
                force=force,
            )

        if build_types in ("update_only", "both"):
            # Update entry: steps 4-6 (single) or 7-9 (both)
            step_offset = 6 if build_types == "both" else 3
            update_metadata = _build_app_metadata(
                config,
                recipe_path,
                version,
                package_path,
                ENTRY_UPDATE,
                manifest,
                large_icon,
            )
            intune_update_app_id = _upload_single_app(
                access_token,
                update_metadata,
                payload,
                intunewin_metadata,
                existing_apps,
                recipe_id=app_id,
                entry=ENTRY_UPDATE,
                installer_sha256=installer_sha256,
                step_create=step_offset + 1,
                step_upload=step_offset + 2,
                step_commit=step_offset + 3,
                total_steps=total_steps,
                force=force,
            )

    # Record the publication in deployment state: published version,
    # hash, and Intune app IDs; a matching pending slot is cleared.
    record_published(
        state,
        version=version,
        sha256=installer_sha256,
        intune_app_id=intune_app_id,
        intune_update_app_id=intune_update_app_id,
    )
    state["name"] = config["name"]
    save_deployment_state(state, state_path)
    logger.info("STATE", f"Recorded published release {version} in {state_path}")

    logger.verbose("UPLOAD", "Upload complete")

    return UploadResult(
        app_id=app_id,
        app_name=app_name,
        version=version,
        intune_app_id=intune_app_id,
        intune_update_app_id=intune_update_app_id,
        package_path=package_path,
    )
