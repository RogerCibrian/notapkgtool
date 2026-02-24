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

# Intune return codes for PSADT deployments
_RETURN_CODES = [
    {
        "@odata.type": "microsoft.graph.win32LobAppReturnCode",
        "returnCode": 0,
        "type": "success",
    },
    {
        "@odata.type": "microsoft.graph.win32LobAppReturnCode",
        "returnCode": 1641,
        "type": "softReboot",
    },
    {
        "@odata.type": "microsoft.graph.win32LobAppReturnCode",
        "returnCode": 3010,
        "type": "softReboot",
    },
]

# TODO: Investigate the difference between applicableArchitectures and
# allowedArchitectures in the Graph API win32LobApp resource. The v1.0 docs
# list both properties with overlapping but different value sets:
#   applicableArchitectures (windowsArchitecture enum): none, x86, x64, arm, neutral
#   allowedArchitectures: x86, x64, arm64
# It's unclear when to use each, and whether allowedArchitectures is the
# preferred field for arm64 targets. For now, map everything to
# applicableArchitectures using the safe fallback of "none" for arm64.
_ARCH_MAP: dict[str, str] = {
    "x86": "x86",
    "x64": "x64",
    "arm64": "none",  # TODO: should this use allowedArchitectures: "arm64" instead?
    "any": "none",
}


def _resolve_build_version_dir(config: dict[str, Any], app_id: str) -> tuple[Path, str]:
    """Find the most recent completed build directory for an app.

    Scans the configured builds output directory for version subdirectories
    that contain a packagefiles/ folder, sorted by modification time.

    Args:
        config: Effective configuration dict from load_effective_config.
        app_id: Application identifier (from recipe app.id).

    Returns:
        A tuple of (version_dir, version_str) where version_dir is the path
            to the version directory (parent of packagefiles/) and version_str
            is its name (the version string).

    Raises:
        ConfigError: If no builds directory exists for the app, or no
            completed build (with packagefiles/) is found.

    """
    build_output_dir = Path(config["defaults"]["build"]["output_dir"])
    app_build_dir = build_output_dir / app_id

    if not app_build_dir.exists():
        raise ConfigError(
            f"No builds found for '{app_id}' in {build_output_dir}. "
            "Run 'napt build' first."
        )

    version_dirs = sorted(
        (
            d
            for d in app_build_dir.iterdir()
            if d.is_dir() and (d / "packagefiles").is_dir()
        ),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    if not version_dirs:
        raise ConfigError(
            f"No completed builds found for '{app_id}' in {app_build_dir}. "
            "Run 'napt build' first."
        )

    version_dir = version_dirs[0]
    return version_dir, version_dir.name


def _infer_package_path(app_id: str) -> Path:
    """Infer the .intunewin package path from the app ID.

    Args:
        app_id: Application identifier (from recipe app.id).

    Returns:
        Expected path to the .intunewin file.

    Raises:
        ConfigError: If the expected package file does not exist.

    """
    package_path = Path("packages") / app_id / "Invoke-AppDeployToolkit.intunewin"
    if not package_path.exists():
        raise ConfigError(
            f"Package not found: {package_path}\n"
            "Run 'napt package' to create the .intunewin file first."
        )
    return package_path


def _build_app_metadata(
    config: dict[str, Any],
    recipe_path: Path,
    version: str,
    build_version_dir: Path,
) -> dict[str, Any]:
    """Build the Win32LobApp JSON payload for the Graph API.

    Assembles the app creation body from recipe config, optional intune:
    overrides, detection/requirements PS1 scripts, and PSADT invariants.

    Args:
        config: Effective configuration dict from load_effective_config.
        recipe_path: Path to the recipe file (used to infer vendor/publisher).
        version: Application version string (from build directory name).
        build_version_dir: Path to the version directory containing the
            generated PS1 scripts (e.g., builds/napt-chrome/141.0.7390.123/).

    Returns:
        Dict ready to POST to the Graph API mobileApps endpoint.

    Raises:
        ConfigError: If the detection script is missing from the build
            directory, or the requirements script is missing when build_types
            requires it.

    """
    logger = get_global_logger()
    app = config["app"]
    intune_overrides: dict[str, Any] = config.get("intune", {})
    win32: dict[str, Any] = app.get("win32", {})
    installed_check: dict[str, Any] = win32.get("installed_check", {})

    display_name: str = app["name"]
    # Publisher: recipe intune.publisher override, then vendor directory name
    publisher: str = intune_overrides.get("publisher") or recipe_path.parent.name
    description: str = intune_overrides.get("description", "")
    privacy_url: str = intune_overrides.get("privacy_url", "")
    info_url: str = intune_overrides.get("info_url", "")

    arch_raw: str = installed_check.get("architecture", "x64")
    applicable_architectures: str = _ARCH_MAP.get(arch_raw, "x64")

    build_types: str = config["defaults"]["win32"]["build_types"]

    # Detection script (always required)
    detection_scripts = sorted(build_version_dir.glob("*-Detection.ps1"))
    if not detection_scripts:
        raise ConfigError(
            f"Detection script not found in {build_version_dir}. "
            "Run 'napt build' to regenerate the build."
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
        req_scripts = sorted(build_version_dir.glob("*-Requirements.ps1"))
        if not req_scripts:
            raise ConfigError(
                f"Requirements script not found in {build_version_dir} "
                f"(build_types is '{build_types}'). "
                "Run 'napt build' to regenerate the build."
            )
        req_content = base64.b64encode(req_scripts[0].read_bytes()).decode()
        logger.verbose("UPLOAD", f"Requirements script: {req_scripts[0].name}")
        rules.append(
            {
                "@odata.type": "#microsoft.graph.win32LobAppPowerShellScriptRule",
                "ruleType": "requirement",
                "enforceSignatureCheck": False,
                "runAs32Bit": False,
                "scriptContent": req_content,
            }
        )

    return {
        "@odata.type": "#microsoft.graph.win32LobApp",
        "displayName": display_name,
        "publisher": publisher,
        "description": description,
        "privacyInformationUrl": privacy_url,
        "informationUrl": info_url,
        "isFeatured": False,
        "fileName": "IntunePackage.intunewin",
        "installExperience": {
            "@odata.type": "microsoft.graph.win32LobAppInstallExperience",
            "runAsAccount": "system",
            "deviceRestartBehavior": "suppress",
        },
        "returnCodes": _RETURN_CODES,
        "rules": rules,
        "applicableArchitectures": applicable_architectures,
        "setupFilePath": "Invoke-AppDeployToolkit.exe",
        "installCommandLine": (
            "Invoke-AppDeployToolkit.exe -DeploymentType Install -DeployMode Silent"
        ),
        "uninstallCommandLine": (
            "Invoke-AppDeployToolkit.exe -DeploymentType Uninstall -DeployMode Silent"
        ),
    }


def upload_package(recipe_path: Path) -> UploadResult:
    """Upload a packaged app to Microsoft Intune via the Graph API.

    Loads the recipe config, infers the .intunewin package path, authenticates
    using the available Azure credential, parses encryption metadata from the
    package, and executes the full Graph API upload flow.

    The package path is inferred as
    packages/{app.id}/Invoke-AppDeployToolkit.intunewin.
    Run 'napt package' before calling this function.

    Authentication is automatic — no configuration required:

    - Developers: run 'az login' once
    - CI/CD: set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID
    - Azure-hosted runners: assign a managed identity to the resource

    Args:
        recipe_path: Path to the recipe YAML file.

    Returns:
        Upload result including the Intune app ID, app name, version, and
            package path.

    Raises:
        ConfigError: If the package file is not found, builds directory is
            missing, or detection/requirements scripts are absent.
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
    app = config["app"]
    app_id: str = app["id"]
    app_name: str = app["name"]

    logger.verbose("UPLOAD", f"Starting upload for '{app_name}' ({app_id})")

    # Step 1: Locate the .intunewin package
    logger.step(1, 6, "Locating .intunewin package...")
    package_path = _infer_package_path(app_id)
    logger.verbose("UPLOAD", f"Package: {package_path}")

    # Step 2: Authenticate
    logger.step(2, 6, "Authenticating with Azure...")
    access_token = get_access_token()

    # Step 3: Parse .intunewin metadata and resolve build version
    logger.step(3, 6, "Parsing package metadata...")
    intunewin_metadata = parse_intunewin(package_path)
    build_version_dir, version = _resolve_build_version_dir(config, app_id)
    logger.verbose("UPLOAD", f"Version: {version}")
    logger.verbose("UPLOAD", f"Build dir: {build_version_dir}")

    # Step 4: Create Intune app record and content version
    logger.step(4, 6, f"Creating Intune app record for '{app_name}' {version}...")
    app_metadata = _build_app_metadata(config, recipe_path, version, build_version_dir)
    intune_app_id = create_win32_app(access_token, app_metadata)
    logger.verbose("UPLOAD", f"Created Intune app: {intune_app_id}")

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
