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
database. The query used depends on ``install_scope``:

- ``"system"`` (default): Queries ``Get-AppxProvisionedPackage -Online``
  for provisioned (all-users) packages.
- ``"user"``: Queries ``Get-AppxPackage -Name <identity_name>`` for
  per-user packages.

For system-scope scripts, ``Version`` and ``Architecture`` are parsed from
``PackageName`` (the package full name) rather than read from object
properties. The package full name format is
``Name_Version_Architecture_ResourceId_PublisherId``, where underscore is
the structural delimiter. The MSIX spec
(https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/package-identity-overview)
explicitly prohibits underscores in all five components, so splitting on
``_`` is safe by design. Reading ``Architecture`` directly from the object
returns an integer enum value (e.g. ``11`` for neutral) that requires a
separate mapping step; parsing from ``PackageName`` yields the canonical
string form directly.

Detection Logic:
    - Queries the appropriate AppX store for the package identity
    - Compares installed version against expected version
    - Supports exact match or minimum version comparison
    - Exits 0 if detected, 1 if not detected

Requirements Logic:
    - Queries the appropriate AppX store for the package identity
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
        identity_name: Package identity name for AppX package query
            (e.g., "com.tinyspeck.slackdesktop").
        app_name: Human-readable application name for logging and
            component identification.
        version: Expected version string to match.
        log_format: Log format (currently only "cmtrace" supported).
        log_level: Minimum log level (INFO, WARNING, ERROR, DEBUG).
        log_rotation_mb: Maximum log file size in MB before rotation.
        exact_match: If True, version must match exactly. If False,
            minimum version comparison (installed >= expected).
        app_id: Application ID (used for fallback identification).
        install_scope: Whether to query per-user (``"user"``) or
            provisioned all-users (``"system"``) package store.

    """

    identity_name: str
    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    exact_match: bool = False
    app_id: str = ""
    install_scope: Literal["system", "user"] = "system"


@dataclass(frozen=True)
class MSIXRequirementsConfig:
    """Configuration for MSIX requirements script generation.

    Attributes:
        identity_name: Package identity name for AppX package query
            (e.g., "com.tinyspeck.slackdesktop").
        app_name: Human-readable application name for logging and
            component identification.
        version: Target version string (requirement met if
            installed < this).
        log_format: Log format (currently only "cmtrace" supported).
        log_level: Minimum log level (INFO, WARNING, ERROR, DEBUG).
        log_rotation_mb: Maximum log file size in MB before rotation.
        app_id: Application ID (used for fallback identification).
        install_scope: Whether to query per-user (``"user"``) or
            provisioned all-users (``"system"``) package store.

    """

    identity_name: str
    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    app_id: str = ""
    install_scope: Literal["system", "user"] = "system"


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
    from napt.build._ps_templates import (
        _TEMPLATES_DIR,
        _load_ps_template,
        substitute_ps_template,
    )
    from napt.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose(
        "DETECTION", f"Generating MSIX detection script: {output_path.name}"
    )

    helper_name = f"_msix_shared_{config.install_scope}.ps1"
    helper_content = (_TEMPLATES_DIR / helper_name).read_text(encoding="utf-8")

    template = _load_ps_template("msix_detection_script.ps1")
    template = template.replace("$NaptMsixSharedHelper", helper_content)
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
    from napt.build._ps_templates import (
        _TEMPLATES_DIR,
        _load_ps_template,
        substitute_ps_template,
    )
    from napt.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose(
        "REQUIREMENTS",
        f"Generating MSIX requirements script: {output_path.name}",
    )

    helper_name = f"_msix_shared_{config.install_scope}.ps1"
    helper_content = (_TEMPLATES_DIR / helper_name).read_text(encoding="utf-8")

    template = _load_ps_template("msix_requirements_script.ps1")
    template = template.replace("$NaptMsixSharedHelper", helper_content)
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
