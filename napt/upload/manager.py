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

from napt.config import load_effective_config
from napt.exceptions import ConfigError
from napt.logging import get_global_logger
from napt.results import UploadResult
from napt.upload.auth import get_access_token
from napt.upload.graph import (
    commit_content_version,
    commit_content_version_file,
    create_content_version,
    create_content_version_file,
    create_win32_app,
    upload_to_azure_blob,
)
from napt.upload.intunewin import extract_encrypted_payload, parse_intunewin

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


def _build_app_metadata(
    config: dict[str, Any],
    recipe_path: Path,
    version: str,
    package_path: Path,
) -> dict[str, Any]:
    """Build the Win32LobApp JSON payload for the Graph API.

    Assembles the app creation body from recipe config, optional intune:
    overrides, detection/requirements PS1 scripts, and PSADT invariants.
    Scripts are read from the package directory (copied there by 'napt package'),
    so this function does not access the builds directory.

    Args:
        config: Effective configuration dict from load_effective_config.
        recipe_path: Path to the recipe file (used to infer vendor/publisher).
        version: Application version string (from package directory name).
        package_path: Path to the .intunewin file
            (e.g., packages/napt-chrome/144.0.7559.110/Invoke-AppDeployToolkit.intunewin).

    Returns:
        Dict ready to POST to the Graph API mobileApps endpoint.

    Raises:
        ConfigError: If the build manifest is missing, the architecture field
            is absent or unrecognized, the detection script is missing, or the
            requirements script is missing when build_types requires it.
            Run 'napt build' and 'napt package' to recreate the package.

    """
    logger = get_global_logger()
    package_dir = package_path.parent
    intune: dict[str, Any] = config.get("intune", {})

    display_name: str = config["name"]
    # Publisher: recipe intune.publisher override, then vendor directory name
    publisher: str = intune.get("publisher") or recipe_path.parent.name
    description: str = intune.get("description", "")
    privacy_url: str = intune.get("privacy_url", "")
    info_url: str = intune.get("info_url", "")

    # Read architecture from build manifest (written by napt build)
    manifest_path = package_dir / "build-manifest.json"
    if not manifest_path.exists():
        raise ConfigError(
            f"Build manifest not found in {package_dir}. "
            "Run 'napt package' to recreate the package."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    allowed_architectures: str | None = _ARCH_MAP[arch_raw]

    build_types: str = intune.get("build_types", "both")

    # Detection script (always required)
    detection_scripts = sorted(package_dir.glob("*-Detection.ps1"))
    if not detection_scripts:
        raise ConfigError(
            f"Detection script not found in {package_dir}. "
            "Run 'napt package' to recreate the package."
        )
    detection_content = base64.b64encode(detection_scripts[0].read_bytes()).decode()
    logger.verbose("UPLOAD", f"Detection script: {detection_scripts[0].name}")

    rules: list[dict[str, Any]] = [
        {
            "@odata.type": "#microsoft.graph.win32LobAppPowerShellScriptRule",
            "ruleType": "detection",
            "enforceSignatureCheck": False,
            "runAs32Bit": False,
            "scriptContent": detection_content,
        }
    ]

    # Requirements script (for build_types that include update detection)
    if build_types in ("both", "update_only"):
        req_scripts = sorted(package_dir.glob("*-Requirements.ps1"))
        if not req_scripts:
            raise ConfigError(
                f"Requirements script not found in {package_dir} "
                f"(build_types is '{build_types}'). "
                "Run 'napt package' to recreate the package."
            )
        req_content = base64.b64encode(req_scripts[0].read_bytes()).decode()
        logger.verbose("UPLOAD", f"Requirements script: {req_scripts[0].name}")
        # TODO: Make enforceSignatureCheck, runAs32Bit, and runAsAccount
        # configurable per-recipe via intune.requirement_rule settings.
        # Also make allowAvailableUninstall configurable via intune.
        rules.append(
            {
                "@odata.type": "#microsoft.graph.win32LobAppPowerShellScriptRule",
                "displayName": req_scripts[0].name,
                "ruleType": "requirement",
                "enforceSignatureCheck": False,
                "runAs32Bit": False,
                "runAsAccount": "system",
                "scriptContent": req_content,
                "operationType": "string",
                "operator": "equal",
                "comparisonValue": "Required",
            }
        )

    install_command: str = intune.get(
        "install_command",
        "Invoke-AppDeployToolkit.exe -DeploymentType Install -DeployMode Silent",
    )
    uninstall_command: str = intune.get(
        "uninstall_command",
        "Invoke-AppDeployToolkit.exe -DeploymentType Uninstall -DeployMode Silent",
    )
    minimum_windows_release: str = intune.get(
        "minimum_supported_windows_release", "Windows10_21H2"
    )

    payload: dict[str, Any] = {
        "@odata.type": "#microsoft.graph.win32LobApp",
        "displayName": display_name,
        "displayVersion": version,
        "publisher": publisher,
        "description": description,
        "privacyInformationUrl": privacy_url,
        "informationUrl": info_url,
        "isFeatured": False,
        "allowAvailableUninstall": True,
        "roleScopeTagIds": [],
        "runAs32Bit": False,
        "fileName": package_path.name,
        "minimumSupportedWindowsRelease": minimum_windows_release,
        "installExperience": {
            "runAsAccount": "system",
            "deviceRestartBehavior": "allow",
            "maxRunTimeInMinutes": 60,
        },
        "returnCodes": _RETURN_CODES,
        "rules": rules,
        "allowedArchitectures": allowed_architectures,
        "setupFilePath": "Invoke-AppDeployToolkit.exe",
        "installCommandLine": install_command,
        "uninstallCommandLine": uninstall_command,
    }

    # Optional fields: developer, owner, notes
    if intune.get("developer"):
        payload["developer"] = intune["developer"]
    if intune.get("owner"):
        payload["owner"] = intune["owner"]
    if intune.get("notes"):
        payload["notes"] = intune["notes"]

    # Optional: app icon (largeIcon)
    logo_path_str: str = intune.get("logo_path", "")
    if logo_path_str:
        logo_path = Path(logo_path_str)
        if logo_path.exists():
            suffix = logo_path.suffix.lower()
            mime_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
            }
            mime_type = mime_types.get(suffix, "image/png")
            icon_value = base64.b64encode(logo_path.read_bytes()).decode()
            payload["largeIcon"] = {"type": mime_type, "value": icon_value}
            logger.verbose("UPLOAD", f"App icon: {logo_path.name}")
        else:
            logger.warning("UPLOAD", f"Logo file not found: {logo_path}, skipping icon")

    # TODO: categories require a lookup against GET /deviceAppManagement/
    # mobileAppCategories to resolve names to IDs before the POST.
    # Source: intune.category

    return payload


def upload_package(recipe_path: Path) -> UploadResult:
    """Upload a packaged app to Microsoft Intune via the Graph API.

    Loads the recipe config, infers the .intunewin package path, authenticates
    using the available Azure credential, parses encryption metadata from the
    package, and executes the full Graph API upload flow.

    The package directory is inferred as packages/{app.id}/{version}/.
    Run 'napt package' before calling this function.

    Authentication is automatic — no configuration required:

    - Developers: set AZURE_CLIENT_ID and AZURE_TENANT_ID, complete device code flow
    - CI/CD: set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID
    - Azure-hosted runners: assign a managed identity to the resource

    Args:
        recipe_path: Path to the recipe YAML file.

    Returns:
        Upload result including the Intune app ID, app name, version, and
            package path.

    Raises:
        ConfigError: If the package directory is not found, or detection/
            requirements scripts are absent from the package directory.
            Run 'napt package' to create or recreate the package.
        AuthError: If all Azure credential methods fail.
        NetworkError: If Graph API or Azure Blob Storage calls fail.
        PackagingError: If the .intunewin file is malformed.

    Example:
        Upload and print the resulting Intune app ID:
            ```python
            from pathlib import Path
            from napt.upload import upload_package

            result = upload_package(Path("recipes/Google/chrome.yaml"))
            print(f"Intune app ID: {result.intune_app_id}")
            ```

    """
    logger = get_global_logger()

    config = load_effective_config(recipe_path)
    app_id: str = config["id"]
    app_name: str = config["name"]

    logger.verbose("UPLOAD", f"Starting upload for '{app_name}' ({app_id})")

    # Step 1: Locate the package directory
    logger.step(1, 6, "Locating .intunewin package...")
    package_path, version = _infer_package_dir(app_id)
    logger.verbose("UPLOAD", f"Package: {package_path}")
    logger.verbose("UPLOAD", f"Version: {version}")

    # Step 2: Authenticate
    logger.step(2, 6, "Authenticating with Azure...")
    access_token = get_access_token()

    # Step 3: Parse .intunewin metadata
    logger.step(3, 6, "Parsing package metadata...")
    intunewin_metadata = parse_intunewin(package_path)

    # Step 4: Create Intune app record and content version
    logger.step(4, 6, f"Creating Intune app record for '{app_name}' {version}...")
    app_metadata = _build_app_metadata(config, recipe_path, version, package_path)
    intune_app_id = create_win32_app(access_token, app_metadata)
    logger.info("UPLOAD", f"Created Intune app: {intune_app_id}")

    cv_id = create_content_version(access_token, intune_app_id)
    logger.verbose("UPLOAD", f"Content version: {cv_id}")

    file_id, sas_uri = create_content_version_file(
        access_token, intune_app_id, cv_id, intunewin_metadata
    )
    logger.verbose("UPLOAD", f"File entry: {file_id}")

    # Step 5: Upload encrypted payload to Azure Blob Storage
    logger.step(5, 6, "Uploading to Azure Blob Storage...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        payload_path = extract_encrypted_payload(package_path, Path(tmp_dir))
        upload_to_azure_blob(sas_uri, payload_path)

    # Step 6: Commit
    logger.step(6, 6, "Committing content version...")
    commit_content_version_file(
        access_token, intune_app_id, cv_id, file_id, intunewin_metadata
    )
    commit_content_version(access_token, intune_app_id, cv_id)

    logger.verbose("UPLOAD", "Upload complete")

    return UploadResult(
        app_id=app_id,
        app_name=app_name,
        version=version,
        intune_app_id=intune_app_id,
        package_path=package_path,
        status="success",
    )
