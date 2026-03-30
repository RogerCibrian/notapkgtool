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

"""Requirements script generation for Intune Win32 apps.

This module generates PowerShell requirements scripts for Intune Win32 app
deployments. Requirements scripts determine if the Update entry should be
applicable to a device based on whether an older version is installed.

Requirements Logic:
    - Checks HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall (always)
    - Checks HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall (always)
    - Checks HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall
        (only on 64-bit OS with 64-bit PowerShell process)
    - Checks HKCU:\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall
        (only on 64-bit OS with 64-bit PowerShell process)
    - Matches by DisplayName (using AppName from recipe or MSI ProductName)
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
    - Primary (System): C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\NAPTRequirements.log
    - Primary (User): C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\NAPTRequirementsUser.log
    - Fallback (System): C:\\ProgramData\\NAPT\\NAPTRequirements.log
    - Fallback (User): %LOCALAPPDATA%\\NAPT\\NAPTRequirementsUser.log
    - Log rotation: 2-file rotation (.log and .log.old), configurable max size
        (default: 3MB)
    - Format: CMTrace format for compatibility with Intune diagnostics

Example:
    Generate requirements script:
        ```python
        from pathlib import Path
        from napt.build.requirements import RequirementsConfig, generate_requirements_script

        config = RequirementsConfig(
            app_name="Google Chrome",
            version="131.0.6778.86",
        )
        script_path = generate_requirements_script(
            config=config,
            output_path=Path("builds/chrome/131.0.6778.86/Google-Chrome-131.0.6778.86-Requirements.ps1"),
        )
        ```

Note:
    Requirements scripts are saved as siblings to the packagefiles directory
    to prevent them from being included in the .intunewin package. They
    should be uploaded separately to Intune as a custom requirement rule
    with output type String, operator Equals, value "Required".

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
class RequirementsConfig:
    """Configuration for requirements script generation.

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


def generate_requirements_script(config: RequirementsConfig, output_path: Path) -> Path:
    """Generate PowerShell requirements script for Intune Win32 app.

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
            from napt.build.requirements import RequirementsConfig, generate_requirements_script

            config = RequirementsConfig(
                app_name="Google Chrome",
                version="131.0.6778.86",
            )
            script_path = generate_requirements_script(
                config,
                Path("requirements.ps1")
            )
            ```

    """
    from napt.build._ps_templates import _load_ps_template, substitute_ps_template
    from napt.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose(
        "REQUIREMENTS", f"Generating requirements script: {output_path.name}"
    )

    template = _load_ps_template("requirements_script.ps1")
    script_content = substitute_ps_template(
        template,
        app_name=config.app_name,
        version=config.version,
        log_rotation_mb=str(config.log_rotation_mb),
        is_msi_installer="$True" if config.is_msi_installer else "$False",
        expected_architecture=config.expected_architecture,
        display_name_operator="-like" if config.use_wildcard else "-eq",
        script_type="Requirements",
        log_base_name="Requirements",
        fallback_script_name="requirements.ps1",
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
