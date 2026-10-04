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

"""The detection and requirements scripts written beside a build.

Both scripts are named after the app and version and saved as siblings of
the ``packagefiles/`` folder, so they stay out of the .intunewin file and
``napt upload`` can send them to Intune separately. MSIX installers get
the AppX package queries; MSI and EXE installers get the registry scripts.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Literal

from napt.build.installer import InstallerInfo
from napt.build.msix_scripts import (
    MSIXDetectionConfig,
    MSIXRequirementsConfig,
    generate_msix_detection_script,
    generate_msix_requirements_script,
)
from napt.build.registry_scripts import (
    DetectionConfig,
    RequirementsConfig,
    generate_detection_script,
    generate_requirements_script,
)
from napt.logging import get_global_logger

_ScriptKind = Literal["Detection", "Requirements"]


def sanitize_filename(name: str, app_id: str) -> str:
    r"""Makes an app name safe to use in a Windows filename.

    Spaces become hyphens, the characters Windows forbids (< > : " | ? * \ /)
    are dropped, runs of hyphens collapse, and leading or trailing hyphens
    and dots are trimmed. A name with nothing left falls back to the app id.

    Args:
        name: String to sanitize (e.g., "Google Chrome").
        app_id: Fallback when nothing usable is left.

    Returns:
        Sanitized filename-safe string (e.g., "Google-Chrome").

    Example:
        Basic sanitization:
            ```python
            sanitize_filename("Google Chrome", "napt-chrome")  # "Google-Chrome"
            sanitize_filename("Test<>App", "napt-test")        # "TestApp"
            sanitize_filename("  ", "my-app")                   # "my-app"
            ```

    """
    sanitized = name.replace(" ", "-")
    for char in '<>:"|?*\\/':
        sanitized = sanitized.replace(char, "")
    sanitized = re.sub(r"-+", "-", sanitized).strip(".-")
    return sanitized or app_id


def _write_script(
    kind: _ScriptKind,
    installer: InstallerInfo,
    config: dict[str, Any],
    build_dir: Path,
) -> Path:
    """Writes one script for the installer beside the packagefiles folder.

    Args:
        kind: Which script to write.
        installer: The inspected installer.
        config: Recipe configuration.
        build_dir: Build directory (packagefiles subdirectory).

    Returns:
        Path to the generated script.

    Raises:
        PackagingError: If the script cannot be written.
    """
    logger = get_global_logger()
    prefix = kind.upper()
    filename = (
        f"{sanitize_filename(installer.app_name, config['id'])}_"
        f"{installer.version.replace(' ', '-')}-{kind}.ps1"
    )
    script_path = build_dir.parent / filename
    log_rotation_mb = config["logging"]["log_rotation_mb"]

    logger.verbose(prefix, f"Generating {kind.lower()} script: {filename}")
    logger.verbose(prefix, f"AppName: {installer.app_name}")
    logger.verbose(prefix, f"Version: {installer.version}")

    if installer.kind == ".msix":
        assert installer.msix is not None  # set by inspect_installer
        install_scope = config["intune"]["run_as_account"]
        if kind == "Detection":
            generate_msix_detection_script(
                MSIXDetectionConfig(
                    identity_name=installer.msix.identity_name,
                    app_name=installer.app_name,
                    version=installer.version,
                    log_rotation_mb=log_rotation_mb,
                    exact_match=config["intune"]["detection"]["exact_match"],
                    install_scope=install_scope,
                ),
                script_path,
            )
        else:
            generate_msix_requirements_script(
                MSIXRequirementsConfig(
                    identity_name=installer.msix.identity_name,
                    app_name=installer.app_name,
                    version=installer.version,
                    log_rotation_mb=log_rotation_mb,
                    install_scope=install_scope,
                ),
                script_path,
            )
        return script_path

    use_wildcard = "*" in installer.app_name or "?" in installer.app_name
    if kind == "Detection":
        generate_detection_script(
            DetectionConfig(
                app_name=installer.app_name,
                version=installer.version,
                log_rotation_mb=log_rotation_mb,
                exact_match=config["intune"]["detection"]["exact_match"],
                is_msi_installer=installer.kind == ".msi",
                expected_architecture=installer.architecture,
                use_wildcard=use_wildcard,
            ),
            script_path,
        )
    else:
        generate_requirements_script(
            RequirementsConfig(
                app_name=installer.app_name,
                version=installer.version,
                log_rotation_mb=log_rotation_mb,
                is_msi_installer=installer.kind == ".msi",
                expected_architecture=installer.architecture,
                use_wildcard=use_wildcard,
            ),
            script_path,
        )
    return script_path


def write_detection_script(
    installer: InstallerInfo, config: dict[str, Any], build_dir: Path
) -> Path:
    """Writes the detection script Intune runs to see whether the app is installed.

    Args:
        installer: The inspected installer.
        config: Recipe configuration.
        build_dir: Build directory (packagefiles subdirectory).

    Returns:
        Path to the generated detection script.

    Raises:
        PackagingError: If the script cannot be written.
    """
    return _write_script("Detection", installer, config, build_dir)


def write_requirements_script(
    installer: InstallerInfo, config: dict[str, Any], build_dir: Path
) -> Path:
    """Writes the requirements script that scopes the update entry to older installs.

    Args:
        installer: The inspected installer.
        config: Recipe configuration.
        build_dir: Build directory (packagefiles subdirectory).

    Returns:
        Path to the generated requirements script.

    Raises:
        PackagingError: If the script cannot be written.
    """
    return _write_script("Requirements", installer, config, build_dir)
