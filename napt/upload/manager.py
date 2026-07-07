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

Coordinates the full upload pipeline: loading recipe config, inferring the
package path, authenticating, parsing the .intunewin file, building app
metadata, and executing the Graph API upload flow.

Example:
    Upload a packaged app to Intune:
        ```python
        from pathlib import Path
        from napt.upload import upload_package

        result = upload_package(Path("recipes/Google/chrome.yaml"))
        print(f"Created Intune app: {result.intune_app_id}")
        print(f"App: {result.app_name} {result.version}")
        ```

"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
from typing import Any

from napt.build.icons import MAX_ICON_BYTES
from napt.config import load_effective_config
from napt.exceptions import ConfigError, PackagingError
from napt.logging import get_global_logger
from napt.results import UploadResult
from napt.state import (
    deployment_state_path,
    load_deployment_state,
    record_deployed,
    save_deployment_state,
)
from napt.upload.auth import get_access_token
from napt.upload.graph import (
    commit_content_version,
    commit_content_version_file,
    create_content_version,
    create_content_version_file,
    create_win32_app,
    get_mobile_app,
    list_mobile_apps,
    update_win32_app,
    upload_to_azure_blob,
)
from napt.upload.intunewin import extract_encrypted_payload, parse_intunewin
from napt.upload.stamp import ENTRY_INSTALL, ENTRY_UPDATE, build_stamp, parse_stamp

__all__ = ["upload_package"]

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


def _infer_package_dir(app_id: str) -> tuple[Path, str]:
    """Find the versioned package directory and .intunewin file for an app.

    Scans packages/{app_id}/ for a single version subdirectory created by
    'napt package'. The package directory is self-contained: it holds the
    .intunewin file and the detection/requirements scripts copied during
    packaging, so upload does not need to access the builds directory.

    Args:
        app_id: Application identifier (from recipe app.id).

    Returns:
        A tuple of (package_path, version_str) where package_path is the
            .intunewin file and version_str is the version name (directory
            name).

    Raises:
        ConfigError: If no package directory exists for the app, or the
            .intunewin file is missing from the version directory.

    """
    app_package_dir = Path("packages") / app_id

    if not app_package_dir.exists():
        raise ConfigError(
            f"No package found for '{app_id}' in packages/. "
            "Run 'napt package' first."
        )

    version_dirs = [d for d in app_package_dir.iterdir() if d.is_dir()]

    if not version_dirs:
        raise ConfigError(
            f"No packaged version found for '{app_id}' in {app_package_dir}. "
            "Run 'napt package' first."
        )

    # Single-slot: there should be exactly one version dir, but take the most
    # recently modified in case of an interrupted previous run.
    version_dir = max(version_dirs, key=lambda d: d.stat().st_mtime)
    intunewin_files = list(version_dir.glob("*.intunewin"))

    if not intunewin_files:
        raise ConfigError(
            f"No .intunewin file found in {version_dir}\n"
            "Run 'napt package' to recreate the package."
        )

    return intunewin_files[0], version_dir.name


def _load_icon_bytes(path: Path, logger: Any) -> bytes | None:
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


def _read_build_manifest(package_dir: Path) -> dict[str, Any]:
    """Reads and validates the build manifest from a package directory.

    Args:
        package_dir: Versioned package directory containing
            build-manifest.json (copied there by 'napt package').

    Returns:
        The parsed build manifest.

    Raises:
        ConfigError: If the manifest is missing, or its architecture or
            installer_sha256 fields are absent or unrecognized. Run
            'napt build' and 'napt package' to recreate the package.

    """
    manifest_path = package_dir / "build-manifest.json"
    if not manifest_path.exists():
        raise ConfigError(
            f"Build manifest not found in {package_dir}. "
            "Run 'napt package' to recreate the package."
        )
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    arch_raw: str = manifest.get("architecture") or ""
    if not arch_raw:
        raise ConfigError(
            f"Architecture not found in build manifest {manifest_path}. "
            "Run 'napt build' and 'napt package' to recreate the package."
        )
    if arch_raw not in _ARCH_MAP:
        raise ConfigError(
            f"Unrecognized architecture '{arch_raw}' in build manifest. "
            f"Expected one of: {', '.join(_ARCH_MAP)}. "
            "Run 'napt build' and 'napt package' to recreate the package."
        )

    if not manifest.get("installer_sha256"):
        raise ConfigError(
            f"installer_sha256 not found in build manifest {manifest_path}. "
            "Run 'napt build' and 'napt package' to recreate the package."
        )

    return manifest


def _build_app_metadata(
    config: dict[str, Any],
    recipe_path: Path,
    version: str,
    package_path: Path,
    build_types: str,
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
        package_path: Path to the .intunewin file
            (e.g., packages/napt-chrome/144.0.7559.110/Invoke-AppDeployToolkit.intunewin).
        build_types: Either "app_only" (install entry, detection script only) or
            "update_only" (update entry, detection + requirements scripts).
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
    if build_types == "update_only":
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

    # Detection script (always required)
    detection_scripts = sorted(package_dir.glob("*-Detection.ps1"))
    if not detection_scripts:
        raise ConfigError(
            f"Detection script not found in {package_dir}. "
            "Run 'napt package' to recreate the package."
        )
    detection_content = base64.b64encode(detection_scripts[0].read_bytes()).decode()
    logger.verbose("UPLOAD", f"Detection script: {detection_scripts[0].name}")

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

    # Requirements script (update entries only)
    if build_types == "update_only":
        req_scripts = sorted(package_dir.glob("*-Requirements.ps1"))
        if not req_scripts:
            raise ConfigError(
                f"Requirements script not found in {package_dir} "
                "(when build_types is "
                "'both' or 'update_only'). "
                "Run 'napt package' to recreate the package."
            )
        req_content = base64.b64encode(req_scripts[0].read_bytes()).decode()
        logger.verbose("UPLOAD", f"Requirements script: {req_scripts[0].name}")
        rules.append(
            {
                "@odata.type": "#microsoft.graph.win32LobAppPowerShellScriptRule",
                "displayName": req_scripts[0].name,
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
    entry = ENTRY_UPDATE if build_types == "update_only" else ENTRY_INSTALL
    payload["notes"] = build_stamp(config["id"], entry, manifest["installer_sha256"])

    # Optional: app icon (largeIcon), resolved once per upload
    if large_icon is not None:
        payload["largeIcon"] = large_icon

    # TODO: categories require a lookup against GET /deviceAppManagement/
    # mobileAppCategories to resolve names to IDs before the POST.
    # Source: intune.category

    return payload


def _find_stamped_app(
    apps: list[dict[str, Any]],
    recipe_id: str,
    entry: str,
    sha256: str,
) -> dict[str, Any] | None:
    """Finds the app whose provenance stamp matches a publish instance.

    Args:
        apps: Mobile app dicts from list_mobile_apps.
        recipe_id: Recipe identifier to match.
        entry: Entry type to match ("install" or "update").
        sha256: Installer hash to match.

    Returns:
        The matching app dict, or None when no stamped app matches.

    """
    for app in apps:
        stamp = parse_stamp(app.get("notes"))
        if (
            stamp
            and stamp["id"] == recipe_id
            and stamp["entry"] == entry
            and stamp["sha256"] == sha256
        ):
            return app
    return None


def _upload_app_content(
    access_token: str,
    intune_app_id: str,
    package_path: Path,
    intunewin_metadata: Any,
    step_upload: int,
    step_commit: int,
    total_steps: int,
) -> None:
    """Uploads and commits the encrypted payload for one app record.

    Args:
        access_token: Azure AD bearer token for Graph API calls.
        intune_app_id: Graph API object ID of the app record.
        package_path: Path to the .intunewin file.
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
    with tempfile.TemporaryDirectory() as tmp_dir:
        payload_path = extract_encrypted_payload(package_path, Path(tmp_dir))
        upload_to_azure_blob(sas_uri, payload_path)

    logger.step(step_commit, total_steps, "Committing content version...")
    commit_content_version_file(
        access_token, intune_app_id, cv_id, file_id, intunewin_metadata
    )
    commit_content_version(access_token, intune_app_id, cv_id)


def _upload_single_app(
    access_token: str,
    app_metadata: dict[str, Any],
    package_path: Path,
    intunewin_metadata: Any,
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
    adopted instead of duplicated — skipped entirely if its content is
    committed, or resumed with a fresh content upload if a previous run
    crashed between app creation and commit. Otherwise the app record is
    created and its content uploaded and committed.

    Adoption does not re-send app metadata or content: a matched app keeps
    whatever it already has, even if the recipe or package changed since it
    was published (the match key is the installer binary, not the package).
    Pass force=True to update the matched app's metadata and upload a fresh
    content version instead of adopting.

    Args:
        access_token: Azure AD bearer token for Graph API calls.
        app_metadata: Win32LobApp JSON payload from _build_app_metadata.
        package_path: Path to the .intunewin file.
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

    match = _find_stamped_app(existing_apps, recipe_id, entry, installer_sha256)
    if match is not None:
        intune_app_id: str = match["id"]
        if force:
            logger.step(
                step_create,
                total_steps,
                f"Re-uploading existing app record for '{display_name}'...",
            )
            update_win32_app(access_token, intune_app_id, app_metadata)
            logger.info(
                "UPLOAD",
                f"Updated Intune app metadata: {intune_app_id} (--force)",
            )
        else:
            full_app = get_mobile_app(access_token, intune_app_id)
            if full_app.get("committedContentVersion"):
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

            logger.step(
                step_create,
                total_steps,
                f"Resuming upload for existing app record '{display_name}'...",
            )
            logger.info(
                "UPLOAD",
                f"Reusing Intune app: {intune_app_id} (content was never committed)",
            )
    else:
        logger.step(
            step_create, total_steps, f"Creating app record for '{display_name}'..."
        )
        intune_app_id = create_win32_app(access_token, app_metadata)
        logger.info("UPLOAD", f"Created Intune app: {intune_app_id}")

    _upload_app_content(
        access_token,
        intune_app_id,
        package_path,
        intunewin_metadata,
        step_upload,
        step_commit,
        total_steps,
    )

    return intune_app_id


def upload_package(recipe_path: Path, force: bool = False) -> UploadResult:
    """Upload a packaged app to Microsoft Intune via the Graph API.

    Loads the recipe config, infers the .intunewin package path, authenticates
    using the available Azure credential, parses encryption metadata from the
    package, and executes the full Graph API upload flow.

    When intune.build_types is "both" (the default), two Intune app entries are
    created: an install entry (detection script only) and an update entry
    (detection + requirements scripts). Each entry is created, uploaded, and
    committed in sequence before moving to the next.

    The package directory is inferred as packages/{app.id}/{version}/.
    Run 'napt package' before calling this function.

    Authentication is automatic — no configuration required:

    - Developers: set AZURE_CLIENT_ID and AZURE_TENANT_ID, complete device code flow
    - CI/CD: set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID
    - Azure-hosted runners: assign a managed identity to the resource

    Before any Graph call, the package's installer hash (from the build
    manifest) is verified against the pending release recorded in the app's
    deployment state, so what was recorded at discovery is byte-for-byte
    what ships. A hash mismatch aborts the upload. When no pending release
    is recorded, the upload proceeds with a warning. On success, the
    deployment state records the published version, hash, and Intune app
    IDs, and a matching pending slot is cleared.

    Re-running an upload is safe: existing NAPT-stamped apps matching this
    publish instance (recipe id, entry type, installer hash) are adopted —
    or their interrupted content upload resumed — instead of duplicated.
    Adoption keeps the app as it is; it does not re-send metadata or
    content. Pass force=True to update matched apps' metadata and upload a
    fresh content version (e.g., after changing PSADT commands or detection
    settings without a new installer release).

    Args:
        recipe_path: Path to the recipe YAML file.
        force: When True, matched stamped apps are re-uploaded (metadata
            and content) instead of adopted as-is. Never creates
            duplicates.

    Returns:
        Upload result including the Intune app ID(s), app name, version, and
            package path. intune_app_id is None when build_types is "update_only";
            intune_update_app_id is None when build_types is "app_only".

    Raises:
        ConfigError: If the package directory is not found, or detection/
            requirements scripts are absent from the package directory.
            Run 'napt package' to create or recreate the package.
        AuthError: If all Azure credential methods fail.
        NetworkError: If Graph API or Azure Blob Storage calls fail.
        PackagingError: If the .intunewin file is malformed, or the
            package's installer hash does not match the pending release
            in deployment state.

    Example:
        Upload and print the resulting Intune app IDs:
            ```python
            from pathlib import Path
            from napt.upload import upload_package

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

    # Step 1: Locate the package directory
    total_steps = 9 if build_types == "both" else 6
    logger.step(1, total_steps, "Locating .intunewin package...")
    package_path, version = _infer_package_dir(app_id)
    logger.verbose("UPLOAD", f"Package: {package_path}")
    logger.verbose("UPLOAD", f"Version: {version}")

    manifest = _read_build_manifest(package_path.parent)
    installer_sha256: str = manifest["installer_sha256"]

    # Verify provenance against deployment state before any Graph call:
    # what was recorded at discovery must be byte-for-byte what ships.
    state_path = deployment_state_path(
        Path(config["directories"]["state"]) / "deployment", app_id
    )
    state = load_deployment_state(state_path)
    pending = state.get("pending")
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

    if build_types in ("app_only", "both"):
        # Install entry: steps 4-6
        install_metadata = _build_app_metadata(
            config, recipe_path, version, package_path, "app_only", manifest, large_icon
        )
        intune_app_id = _upload_single_app(
            access_token,
            install_metadata,
            package_path,
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
            "update_only",
            manifest,
            large_icon,
        )
        intune_update_app_id = _upload_single_app(
            access_token,
            update_metadata,
            package_path,
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

    # Record the publication in deployment state: deployed version, hash,
    # and Intune app IDs; a matching pending slot is cleared.
    record_deployed(
        state,
        version=version,
        sha256=installer_sha256,
        intune_app_id=intune_app_id,
        intune_update_app_id=intune_update_app_id,
    )
    save_deployment_state(state, state_path)
    logger.info("STATE", f"Recorded deployed release {version} in {state_path}")

    logger.verbose("UPLOAD", "Upload complete")

    return UploadResult(
        app_id=app_id,
        app_name=app_name,
        version=version,
        intune_app_id=intune_app_id,
        intune_update_app_id=intune_update_app_id,
        package_path=package_path,
        status="success",
    )
