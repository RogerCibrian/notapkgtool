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

"""Registry-based detection and requirements script generation for Intune Win32 apps.

This module generates PowerShell detection and requirements scripts for
MSI and EXE installers deployed as Intune Win32 apps. Scripts check
Windows uninstall registry keys for installed software and version
information using CMTrace-formatted logging.

Detection Logic:
    - Checks HKLM and HKCU uninstall registry keys
    - Uses architecture-aware registry views (32-bit, 64-bit, or both)
    - Matches by DisplayName (using AppName from recipe or MSI ProductName)
    - Compares version (exact or minimum version match based on config)
    - Exits 0 if detected, 1 if not detected

Requirements Logic:
    - Same registry scanning as detection
    - If installed version < target version: outputs "Required" and exits 0
    - Otherwise: outputs nothing and exits 0

Installer Type Filtering:
    Scripts filter registry entries based on installer type to prevent false
    matches when both MSI and EXE versions of software exist:

    - MSI installers (strict): Only matches registry entries with
        WindowsInstaller=1. Prevents false matches with EXE versions.
    - Non-MSI installers (permissive): Matches ANY registry entry. Handles
        EXE installers that run embedded MSIs internally.

Logging:
    - Primary: C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\
    - Fallback: C:\\ProgramData\\NAPT\\ (system) or %LOCALAPPDATA%\\NAPT\\
        (user)
    - Log rotation: 2-file rotation (.log and .log.old), configurable max
        size (default: 3MB)
    - Format: CMTrace for compatibility with Intune diagnostics

Example:
    Generate detection and requirements scripts:
        ```python
        from pathlib import Path
        from napt.build.registry_scripts import (
            DetectionConfig,
            RequirementsConfig,
            generate_detection_script,
            generate_requirements_script,
        )

        det_config = DetectionConfig(
            app_name="Google Chrome",
            version="131.0.6778.86",
        )
        generate_detection_script(det_config, Path("detection.ps1"))

        req_config = RequirementsConfig(
            app_name="Google Chrome",
            version="131.0.6778.86",
        )
        generate_requirements_script(req_config, Path("requirements.ps1"))
        ```

Note:
    Scripts are saved as siblings to the packagefiles directory to prevent
    them from being included in the .intunewin package. They should be
    uploaded separately to Intune alongside the package.

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LogFormat = Literal["cmtrace"]
LogLevel = Literal["INFO", "WARNING", "ERROR", "DEBUG"]

# Type alias for architecture values
ArchitectureMode = Literal["x86", "x64", "arm64", "any"]


@dataclass(frozen=True)
class DetectionConfig:
    """Configuration for registry-based detection script generation.

    Attributes:
        app_name: Application name to search for in registry DisplayName.
        version: Expected version string to match.
        log_format: Log format (currently only "cmtrace" supported).
        log_level: Minimum log level (INFO, WARNING, ERROR, DEBUG).
        log_rotation_mb: Maximum log file size in MB before rotation.
        exact_match: If True, version must match exactly. If False, minimum
            version comparison (remote >= expected).
        app_id: Application ID (used for fallback if app_name sanitization
            results in empty string).
        is_msi_installer: If True, only match MSI-based registry entries.
            If False, only match non-MSI entries. This prevents false matches
            when both MSI and EXE versions of software exist with the same
            DisplayName.
        expected_architecture: Architecture filter for registry view selection.
            - "x86": Check only 32-bit registry view
            - "x64": Check only 64-bit registry view
            - "arm64": Check only 64-bit registry view (ARM64 uses 64-bit registry)
            - "any": Check both 32-bit and 64-bit views (permissive)
        use_wildcard: If True, use PowerShell -like operator for DisplayName
            matching (supports * and ? wildcards). If False, use exact -eq match.

    """

    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    exact_match: bool = False
    app_id: str = ""
    is_msi_installer: bool = False
    expected_architecture: ArchitectureMode = "any"
    use_wildcard: bool = False


@dataclass(frozen=True)
class RequirementsConfig:
    """Configuration for registry-based requirements script generation.

    Attributes:
        app_name: Application name to search for in registry DisplayName.
        version: Target version string (requirement met if installed < this).
        log_format: Log format (currently only "cmtrace" supported).
        log_level: Minimum log level (INFO, WARNING, ERROR, DEBUG).
        log_rotation_mb: Maximum log file size in MB before rotation.
        app_id: Application ID (used for fallback if app_name sanitization
            results in empty string).
        is_msi_installer: If True, only match MSI-based registry entries.
            If False, only match non-MSI entries. This prevents false matches
            when both MSI and EXE versions of software exist with the same
            DisplayName.
        expected_architecture: Architecture filter for registry view selection.
            - "x86": Check only 32-bit registry view
            - "x64": Check only 64-bit registry view
            - "arm64": Check only 64-bit registry view (ARM64 uses 64-bit registry)
            - "any": Check both 32-bit and 64-bit views (permissive)
        use_wildcard: If True, use PowerShell -like operator for DisplayName
            matching (supports * and ? wildcards). If False, use exact -eq match.

    """

    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    app_id: str = ""
    is_msi_installer: bool = False
    expected_architecture: ArchitectureMode = "any"
    use_wildcard: bool = False


def generate_detection_script(config: DetectionConfig, output_path: Path) -> Path:
    """Generates PowerShell detection script for Intune Win32 app.

    Creates a PowerShell script that checks Windows uninstall registry keys
    for software installation and version. The script uses CMTrace-formatted
    logging with verbose output, includes log rotation logic, and performs
    write permission testing with automatic fallback to alternate log locations
    if primary locations are unavailable.

    Args:
        config: Detection configuration (app name, version, logging settings).
        output_path: Path where the detection script will be saved.

    Returns:
        Path to the generated detection script.

    Raises:
        OSError: If the script file cannot be written.

    Example:
        Generate script with default settings:
            ```python
            from pathlib import Path
            from napt.build.registry_scripts import (
                DetectionConfig,
                generate_detection_script,
            )

            config = DetectionConfig(
                app_name="Google Chrome",
                version="131.0.6778.86",
            )
            script_path = generate_detection_script(
                config,
                Path("detection.ps1"),
            )
            ```

    """
    from napt.build._ps_templates import _load_ps_template, substitute_ps_template
    from napt.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose("DETECTION", f"Generating detection script: {output_path.name}")

    template = _load_ps_template("registry_detection_script.ps1")
    script_content = substitute_ps_template(
        template,
        {
            "$NaptAppName": config.app_name,
            "$NaptVersion": config.version,
            "$NaptExactMatch": "$True" if config.exact_match else "$False",
            "$NaptLogRotationMb": str(config.log_rotation_mb),
            "$NaptIsMsiInstaller": "$True" if config.is_msi_installer else "$False",
            "$NaptExpectedArchitecture": config.expected_architecture,
            "$NaptScriptType": "Detection",
            "$NaptLogBaseName": "NAPTDetections",
            "$NaptFallbackScriptName": "detection.ps1",
        },
    )

    # Template defaults to -like; replace with -eq for exact matching
    if not config.use_wildcard:
        script_content = script_content.replace(
            "$DisplayNameValue -like $AppName",
            "$DisplayNameValue -eq $AppName",
        )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        script_bytes = script_content.encode("utf-8")
        output_path.write_bytes(script_bytes)
        logger.verbose("DETECTION", f"Detection script written to: {output_path}")
    except OSError as err:
        raise OSError(
            f"Failed to write detection script to {output_path}: {err}"
        ) from err

    return output_path


def generate_requirements_script(
    config: RequirementsConfig, output_path: Path
) -> Path:
    """Generates PowerShell requirements script for Intune Win32 app.

    Creates a PowerShell script that checks Windows uninstall registry keys
    for software installation and determines if an older version is installed.
    The script outputs "Required" if installed version < target version,
    nothing otherwise. Always exits with code 0 so Intune can evaluate STDOUT.

    Args:
        config: Requirements configuration (app name, version, logging settings).
        output_path: Path where the requirements script will be saved.

    Returns:
        Path to the generated requirements script.

    Raises:
        OSError: If the script file cannot be written.

    Example:
        Generate script with default settings:
            ```python
            from pathlib import Path
            from napt.build.registry_scripts import (
                RequirementsConfig,
                generate_requirements_script,
            )

            config = RequirementsConfig(
                app_name="Google Chrome",
                version="131.0.6778.86",
            )
            script_path = generate_requirements_script(
                config,
                Path("requirements.ps1"),
            )
            ```

    """
    from napt.build._ps_templates import _load_ps_template, substitute_ps_template
    from napt.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose(
        "REQUIREMENTS", f"Generating requirements script: {output_path.name}"
    )

    template = _load_ps_template("registry_requirements_script.ps1")
    script_content = substitute_ps_template(
        template,
        {
            "$NaptAppName": config.app_name,
            "$NaptVersion": config.version,
            "$NaptLogRotationMb": str(config.log_rotation_mb),
            "$NaptIsMsiInstaller": "$True" if config.is_msi_installer else "$False",
            "$NaptExpectedArchitecture": config.expected_architecture,
            "$NaptScriptType": "Requirements",
            "$NaptLogBaseName": "NAPTRequirements",
            "$NaptFallbackScriptName": "requirements.ps1",
        },
    )

    # Template defaults to -like; replace with -eq for exact matching
    if not config.use_wildcard:
        script_content = script_content.replace(
            "$DisplayNameValue -like $AppName",
            "$DisplayNameValue -eq $AppName",
        )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        script_bytes = script_content.encode("utf-8")
        output_path.write_bytes(script_bytes)
        logger.verbose("REQUIREMENTS", f"Requirements script written to: {output_path}")
    except OSError as err:
        raise OSError(
            f"Failed to write requirements script to {output_path}: {err}"
        ) from err

    return output_path
