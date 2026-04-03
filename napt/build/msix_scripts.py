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

"""MSIX detection and requirements script generation for Intune Win32 apps.

This module generates PowerShell detection and requirements scripts for
MSIX packages deployed as Intune Win32 apps. Unlike MSI/EXE installers
that use registry-based detection, MSIX scripts query the AppX package
database via ``Get-AppxPackage``.

Detection Logic:
    - Queries ``Get-AppxPackage -Name <identity_name>`` for the package
    - Compares installed version against expected version
    - Supports exact match or minimum version comparison
    - Exits 0 if detected, 1 if not detected

Requirements Logic:
    - Queries ``Get-AppxPackage -Name <identity_name>`` for the package
    - If installed version < target version: outputs "Required"
    - Otherwise: outputs nothing
    - Always exits 0 so Intune can evaluate STDOUT

Logging:
    - Primary (System):
        C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\NAPTDetections.log
    - Primary (User):
        C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\NAPTDetectionsUser.log
    - Fallback locations mirror the registry-based scripts
    - Format: CMTrace for compatibility with Intune diagnostics

Example:
    Generate MSIX detection script:
        ```python
        from pathlib import Path
        from napt.build.msix_scripts import (
            MSIXDetectionConfig,
            generate_msix_detection_script,
        )

        config = MSIXDetectionConfig(
            identity_name="com.tinyspeck.slackdesktop",
            version="4.49.81.0",
        )
        script_path = generate_msix_detection_script(
            config=config,
            output_path=Path("builds/slack/4.49.81.0/Slack-4.49.81.0-Detection.ps1"),
        )
        ```

Note:
    Detection and requirements scripts are saved as siblings to the
    packagefiles directory to prevent them from being included in the
    .intunewin package.

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LogFormat = Literal["cmtrace"]
LogLevel = Literal["INFO", "WARNING", "ERROR", "DEBUG"]


@dataclass(frozen=True)
class MSIXDetectionConfig:
    """Configuration for MSIX detection script generation.

    Attributes:
        identity_name: Package identity name for ``Get-AppxPackage``
            query (e.g., "com.tinyspeck.slackdesktop").
        app_name: Human-readable application name for logging and
            component identification.
        version: Expected version string to match.
        log_format: Log format (currently only "cmtrace" supported).
        log_level: Minimum log level (INFO, WARNING, ERROR, DEBUG).
        log_rotation_mb: Maximum log file size in MB before rotation.
        exact_match: If True, version must match exactly. If False,
            minimum version comparison (installed >= expected).
        app_id: Application ID (used for fallback identification).

    """

    identity_name: str
    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    exact_match: bool = False
    app_id: str = ""


@dataclass(frozen=True)
class MSIXRequirementsConfig:
    """Configuration for MSIX requirements script generation.

    Attributes:
        identity_name: Package identity name for ``Get-AppxPackage``
            query (e.g., "com.tinyspeck.slackdesktop").
        app_name: Human-readable application name for logging and
            component identification.
        version: Target version string (requirement met if
            installed < this).
        log_format: Log format (currently only "cmtrace" supported).
        log_level: Minimum log level (INFO, WARNING, ERROR, DEBUG).
        log_rotation_mb: Maximum log file size in MB before rotation.
        app_id: Application ID (used for fallback identification).

    """

    identity_name: str
    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    app_id: str = ""


def generate_msix_detection_script(
    config: MSIXDetectionConfig, output_path: Path
) -> Path:
    """Generates PowerShell detection script for MSIX Win32 app.

    Creates a PowerShell script that queries ``Get-AppxPackage`` for the
    package identity and compares installed version against expected
    version.

    Args:
        config: MSIX detection configuration.
        output_path: Path where the detection script will be saved.

    Returns:
        Path to the generated detection script.

    Raises:
        OSError: If the script file cannot be written.

    Example:
        Generate script with default settings:
            ```python
            from pathlib import Path
            from napt.build.msix_scripts import (
                MSIXDetectionConfig,
                generate_msix_detection_script,
            )

            config = MSIXDetectionConfig(
                identity_name="com.tinyspeck.slackdesktop",
                app_name="Slack",
                version="4.49.81.0",
            )
            script_path = generate_msix_detection_script(
                config,
                Path("detection.ps1"),
            )
            ```

    """
    from napt.build._ps_templates import _load_ps_template, substitute_ps_template
    from napt.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose(
        "DETECTION", f"Generating MSIX detection script: {output_path.name}"
    )

    template = _load_ps_template("msix_detection_script.ps1")
    script_content = substitute_ps_template(
        template,
        {
            "$NaptPackageIdentityName": config.identity_name,
            "$NaptAppName": config.app_name,
            "$NaptVersion": config.version,
            "$NaptExactMatch": "$True" if config.exact_match else "$False",
            "$NaptLogRotationMb": str(config.log_rotation_mb),
            "$NaptScriptType": "Detection",
            "$NaptLogBaseName": "NAPTDetections",
            "$NaptFallbackScriptName": "detection.ps1",
        },
    )

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


def generate_msix_requirements_script(
    config: MSIXRequirementsConfig, output_path: Path
) -> Path:
    """Generates PowerShell requirements script for MSIX Win32 app.

    Creates a PowerShell script that queries ``Get-AppxPackage`` for the
    package identity and determines if an older version is installed.
    Outputs "Required" if installed version < target, nothing otherwise.

    Args:
        config: MSIX requirements configuration.
        output_path: Path where the requirements script will be saved.

    Returns:
        Path to the generated requirements script.

    Raises:
        OSError: If the script file cannot be written.

    Example:
        Generate script with default settings:
            ```python
            from pathlib import Path
            from napt.build.msix_scripts import (
                MSIXRequirementsConfig,
                generate_msix_requirements_script,
            )

            config = MSIXRequirementsConfig(
                identity_name="com.tinyspeck.slackdesktop",
                app_name="Slack",
                version="4.49.81.0",
            )
            script_path = generate_msix_requirements_script(
                config,
                Path("requirements.ps1"),
            )
            ```

    """
    from napt.build._ps_templates import _load_ps_template, substitute_ps_template
    from napt.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose(
        "REQUIREMENTS",
        f"Generating MSIX requirements script: {output_path.name}",
    )

    template = _load_ps_template("msix_requirements_script.ps1")
    script_content = substitute_ps_template(
        template,
        {
            "$NaptPackageIdentityName": config.identity_name,
            "$NaptAppName": config.app_name,
            "$NaptVersion": config.version,
            "$NaptLogRotationMb": str(config.log_rotation_mb),
            "$NaptScriptType": "Requirements",
            "$NaptLogBaseName": "NAPTRequirements",
            "$NaptFallbackScriptName": "requirements.ps1",
        },
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        script_bytes = script_content.encode("utf-8")
        output_path.write_bytes(script_bytes)
        logger.verbose(
            "REQUIREMENTS", f"Requirements script written to: {output_path}"
        )
    except OSError as err:
        raise OSError(
            f"Failed to write requirements script to {output_path}: {err}"
        ) from err

    return output_path
