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

"""Build manager for PSADT package creation.

This module orchestrates the complete build process for creating PSADT
packages from recipes and downloaded installers.

Design Principles:
    - Filesystem is source of truth for version information
    - Entire PSADT Template_v4 structure copied unmodified
    - Invoke-AppDeployToolkit.ps1 is generated from template (not copied)
    - Build directories are versioned: {app_id}/{version}/
    - Branding applied by replacing files in root Assets/ directory (v4 structure)
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any, cast

from napt.build.icons import extract_icon_png
from napt.build.msix_scripts import (
    MSIXDetectionConfig,
    MSIXRequirementsConfig,
    generate_msix_detection_script,
    generate_msix_requirements_script,
)
from napt.build.registry_scripts import (
    ArchitectureMode,
    DetectionConfig,
    RequirementsConfig,
    generate_detection_script,
    generate_requirements_script,
)
from napt.config.loader import load_effective_config
from napt.download.download import DOWNLOAD_PART_SUFFIX, sha256_file
from napt.exceptions import ConfigError, PackagingError, StateError
from napt.paths import is_safe_path_component
from napt.powershell import (
    PS_SCRIPT_ENCODING,
    ps_single_quote,
    strip_control_characters,
)
from napt.psadt.release import get_psadt_release
from napt.results import BuildResult
from napt.state.deployment import deployment_state_path, load_deployment_state
from napt.versioning.msi import (
    MSIMetadata,
    extract_msi_metadata,
)
from napt.versioning.msix import (
    MSIXMetadata,
    extract_msix_metadata,
)


def sanitize_filename(name: str, app_id: str = "") -> str:
    r"""Sanitize string for use in Windows filename.

    Rules:
        - Replace spaces with hyphens
        - Remove invalid Windows filename characters (< > : " | ? * \ /)
        - Normalize multiple consecutive hyphens to single hyphen
        - Remove leading/trailing hyphens and dots
        - If result is empty, fallback to app_id (or "app" if app_id is empty)

    Args:
        name: String to sanitize (e.g., "Google Chrome").
        app_id: Fallback identifier if name becomes empty after sanitization.

    Returns:
        Sanitized filename-safe string (e.g., "Google-Chrome").

    Example:
        Basic sanitization:
            ```python
            sanitize_filename("Google Chrome")  # Returns: "Google-Chrome"
            sanitize_filename("My App v2.0")    # Returns: "My-App-v2.0"
            sanitize_filename("Test<>App")      # Returns: "TestApp"
            ```

        Fallback behavior:
            ```python
            sanitize_filename("  ", "my-app")   # Returns: "my-app"
            sanitize_filename("", "test")       # Returns: "test"
            ```

    """
    sanitized = name.replace(" ", "-")
    invalid_chars = '<>:"|?*\\/'
    for char in invalid_chars:
        sanitized = sanitized.replace(char, "")
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip(".-")
    if not sanitized:
        sanitized = app_id if app_id else "app"
    return sanitized


def _release_to_build(config: dict[str, Any]) -> dict[str, Any] | None:
    """Reads the release to build from the app's deployment state.

    That is the pending release (awaiting publication), or the published
    release when nothing is pending, which is the case when rebuilding the
    current version. Deployment state is committed alongside recipes, so
    this works on machines that never ran discover, such as a CI publish
    job restoring downloads from a cache.

    Args:
        config: Recipe configuration.

    Returns:
        The release entry (``version``, ``sha256``, ``url``), or None when
            no release is recorded.

    Raises:
        StateError: If the deployment state file exists but is corrupted
            or has an unsupported schema version.
    """
    state_dir = Path(config["directories"]["state"]) / "deployment"
    state = load_deployment_state(deployment_state_path(state_dir, config["id"]))
    return state.get("pending") or state.get("published")


def _get_installer_version(installer_file: Path) -> str:
    """Gets the version for the installer file.

    The version is the name of the folder discover filed the installer in
    (``downloads/<id>/<version>/``). An MSI or MSIX installer reports its
    own version, and discover names the folder after it, so for those the
    two are read and must agree: a file moved into the wrong folder by
    hand would otherwise be built and detected under a version it does
    not carry.

    Args:
        installer_file: Path to the installer file.

    Returns:
        Version string.

    Raises:
        PackagingError: If MSI or MSIX metadata extraction fails, or if
            the installer's version differs from its folder's name.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    version = installer_file.parent.name
    suffix = installer_file.suffix.lower()

    if suffix == ".msi":
        logger.verbose(
            "BUILD", f"Auto-detected MSI, extracting version: {installer_file.name}"
        )
        reported = extract_msi_metadata(installer_file).product_version
    elif suffix == ".msix":
        logger.verbose(
            "BUILD",
            f"Auto-detected MSIX, extracting version: {installer_file.name}",
        )
        reported = extract_msix_metadata(installer_file).version
    else:
        logger.verbose("BUILD", f"Using discovered version: {version}")
        return version

    logger.verbose("BUILD", f"Extracted version: {reported}")
    if reported != version:
        raise PackagingError(
            f"{installer_file.name} reports version {reported} but is filed "
            f"under {installer_file.parent}. Run 'napt discover' to file it "
            "under its own version, or rename the folder to match."
        )
    return version


_INSTALLER_SUFFIXES = (".msi", ".msix", ".exe")


def _find_installer_file(
    downloads_dir: Path, app_id: str, release: dict[str, Any] | None
) -> tuple[Path, str]:
    """Finds the installer to build and returns it with its SHA-256.

    Discover saves each download to ``downloads/<id>/<version>/``. With a
    recorded release, the installer is the file in that version's folder
    whose hash matches the recorded one, so a file that was swapped or
    corrupted since discovery is refused rather than packaged.

    Without a recorded release (a stateless discover and no deployment
    state), there is nothing to match against, and the single installer
    found in one of the app's version folders is used.

    Args:
        downloads_dir: Downloads directory to search.
        app_id: Recipe id.
        release: The release to build (``version`` and ``sha256``), from
            [_release_to_build][napt.build.manager._release_to_build], or
            None when no release is recorded.

    Returns:
        A tuple (installer_path, sha256), where
            installer_path is the installer file,
            sha256 is its hex digest.

    Raises:
        StateError: If the recorded version is not a plain folder name.
        PackagingError: If no file matches the recorded release, or, with
            no recorded release, if there is not exactly one installer.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    app_dir = downloads_dir / app_id

    if release is not None:
        # State files are hand-editable and reviewed through pull requests, so
        # the recorded version is not trusted to stay inside the app's folder.
        if not is_safe_path_component(release["version"]):
            raise StateError(
                f"Deployment state for {app_id} records version "
                f"{release['version']!a}, which cannot be used as a folder name. "
                "Run 'napt discover' to record the release again."
            )
        version_dir = app_dir / release["version"]
        candidates = (
            [
                p
                for p in version_dir.iterdir()
                if p.is_file() and p.suffix != DOWNLOAD_PART_SUFFIX
            ]
            if version_dir.is_dir()
            else []
        )
        for candidate in candidates:
            digest = sha256_file(candidate)
            if digest == release["sha256"]:
                logger.verbose("BUILD", f"Found installer: {candidate}")
                return candidate, digest
        raise PackagingError(
            f"No file in {version_dir} matches the recorded release of {app_id} "
            f"(version {release['version']}, sha256 {release['sha256']}). "
            f"Run 'napt discover' to download it."
        )

    # Only folders named like a version count. That skips ".incoming", where
    # an interrupted discover can leave a finished download behind.
    installers = sorted(
        p
        for p in app_dir.glob("*/*")
        if p.is_file()
        and p.suffix.lower() in _INSTALLER_SUFFIXES
        and is_safe_path_component(p.parent.name)
    )
    if len(installers) == 1:
        logger.verbose("BUILD", f"Found installer: {installers[0]}")
        return installers[0], sha256_file(installers[0])
    if not installers:
        raise PackagingError(
            f"No installer found for {app_id} under {app_dir}. "
            f"Run 'napt discover' first."
        )
    listing = ", ".join(str(p.relative_to(app_dir)) for p in installers)
    raise PackagingError(
        f"No release is recorded for {app_id}, and {app_dir} holds more than one "
        f"installer ({listing}). Run 'napt discover' without --stateless so "
        f"the release to build is recorded."
    )


def _create_build_directory(base_dir: Path, app_id: str, version: str) -> Path:
    """Create the build directory structure.

    Creates the directory structure:
        {base_dir}/{app_id}/{version}/packagefiles/

    The packagefiles/ subdirectory contains the PSADT files that will be
    packaged into the .intunewin file. Detection scripts are saved as
    siblings to packagefiles/ to prevent them from being included in the
    package.

    Args:
        base_dir: Base builds directory.
        app_id: Application ID.
        version: Application version.

    Returns:
        Path to the packagefiles subdirectory where PSADT files will be copied
            (build_dir/packagefiles/).

    Raises:
        PackagingError: If the version cannot be used as a folder name.
        OSError: If directory creation fails.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    # The version comes from installer metadata or a scraped page. An existing
    # build directory is deleted below, so a version such as "..\.." must
    # never be allowed to point that delete somewhere else.
    if not is_safe_path_component(version):
        raise PackagingError(
            f"Version {version!a} for {app_id} cannot be used as a folder name. "
            "Versions may contain only letters, digits, '.', '-', '_', and '+'."
        )
    version_dir = base_dir / app_id / version
    packagefiles_dir = version_dir / "packagefiles"

    if version_dir.exists():
        logger.verbose("BUILD", f"Build directory exists: {version_dir}")
        logger.verbose("BUILD", "Removing existing build...")
        shutil.rmtree(version_dir)

    # Create the packagefiles subdirectory
    packagefiles_dir.mkdir(parents=True, exist_ok=True)

    logger.verbose("BUILD", f"Created build directory: {packagefiles_dir}")

    return packagefiles_dir


def _copy_psadt_template(psadt_cache_dir: Path, build_dir: Path) -> None:
    """Copy PSADT template files from cache to build directory without modification.

    Copies the entire v4 template structure including:
    - PSAppDeployToolkit/ (module)
    - Invoke-AppDeployToolkit.exe
    - Invoke-AppDeployToolkit.ps1 (template - will be overwritten)
    - Assets/, Config/, Strings/ (default configs)
    - Files/, SupportFiles/ (empty directories for user files)
    - PSAppDeployToolkit.Extensions/

    Args:
        psadt_cache_dir: Path to cached PSADT version directory (root
            of Template_v4 extraction).
        build_dir: Build directory (packagefiles subdirectory) where PSADT
            should be copied.

    Raises:
        PackagingError: If PSADT cache directory or required files don't exist.
        OSError: If copy operation fails.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    if not psadt_cache_dir.exists():
        raise PackagingError(f"PSADT cache directory not found: {psadt_cache_dir}")

    logger.verbose("BUILD", f"Copying PSADT template from cache: {psadt_cache_dir}")

    # Copy all files and directories from the template root
    for item in psadt_cache_dir.iterdir():
        dest = build_dir / item.name

        if item.is_dir():
            shutil.copytree(item, dest)
            logger.verbose("BUILD", f"  Copied directory: {item.name}/")
        else:
            shutil.copy2(item, dest)
            logger.verbose("BUILD", f"  Copied file: {item.name}")

    logger.verbose("BUILD", "[OK] PSADT template copied")


def _copy_installer(installer_file: Path, build_dir: Path) -> None:
    """Copy installer to the build's Files/ directory.

    Args:
        installer_file: Path to the installer file.
        build_dir: Build directory (packagefiles subdirectory).

    Raises:
        OSError: If copy operation fails.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    files_dir = build_dir / "Files"
    dest = files_dir / installer_file.name

    logger.verbose("BUILD", f"Copying installer: {installer_file.name}")

    shutil.copy2(installer_file, dest)

    logger.verbose("BUILD", "[OK] Installer copied to Files/")


def _apply_branding(config: dict[str, Any], build_dir: Path) -> None:
    """Apply custom branding by replacing PSADT assets.

    Reads the brand_pack configuration and replaces PSADT's default
    assets (logo, banner) with custom ones.

    Args:
        config: Merged configuration with brand_pack settings.
        build_dir: Build directory (packagefiles subdirectory) containing
            PSAppDeployToolkit/.

    Raises:
        FileNotFoundError: If branding files don't exist.
        OSError: If file copy operation fails.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    brand_pack = config["psadt"]["brand_pack"]

    if not brand_pack["path"]:
        logger.verbose("BUILD", "No brand pack configured, using PSADT defaults")
        return

    brand_path = Path(brand_pack["path"])
    mappings = brand_pack["mappings"]

    if not brand_path.exists():
        logger.verbose(
            "BUILD", f"Brand pack path not found: {brand_path}, skipping branding"
        )
        return

    logger.verbose("BUILD", f"Applying branding from: {brand_path}")

    for mapping in mappings:
        source_pattern = mapping.get("source", "")
        target_path = mapping.get("target", "")

        if not source_pattern or not target_path:
            continue

        # Find source files matching pattern
        source_files = list(brand_path.glob(source_pattern))

        if not source_files:
            logger.verbose("BUILD", f"No files match pattern: {source_pattern}")
            continue

        # Use first match
        source_file = source_files[0]

        # Build target path (append extension from source, don't replace)
        # Apply to root Assets directory (v4 template structure)
        target = build_dir / target_path
        target_with_ext = Path(str(target) + source_file.suffix)

        # Ensure parent directory exists
        target_with_ext.parent.mkdir(parents=True, exist_ok=True)

        # Copy file
        shutil.copy2(source_file, target_with_ext)
        logger.verbose("BUILD", f"  {source_file.name} -> {target_with_ext.name}")

    logger.verbose("BUILD", "[OK] Branding applied")


def _resolve_app_info(
    installer_file: Path,
    config: dict[str, Any],
    version: str,
    msi_metadata: MSIMetadata | None,
    msix_metadata: MSIXMetadata | None = None,
) -> tuple[str, ArchitectureMode]:
    """Resolve app name and architecture for script generation.

    Determines the correct display name and architecture from installer
    metadata (authoritative for MSI and MSIX installers) or from
    intune.detection recipe config (required for EXE installers). Also
    emits warnings for misconfigured fields that will be silently ignored.

    Args:
        installer_file: Path to the installer file.
        config: Recipe configuration.
        version: Extracted version string (used for
            {{discovered_version}} substitution).
        msi_metadata: Pre-extracted MSI metadata (non-None for MSI
            installers).
        msix_metadata: Pre-extracted MSIX metadata (non-None for MSIX
            installers).

    Returns:
        A tuple (app_name, architecture), where
            app_name is the resolved display name for detection,
            architecture is one of "x86", "x64", "arm64", "any".

    Raises:
        ConfigError: If required configuration is missing or inconsistent.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    detection_settings = config.get("intune", {}).get("detection", {})
    installer_ext = installer_file.suffix.lower()
    override_display_name = detection_settings.get("override_msi_display_name", False)

    # Warn about fields that will be ignored for MSI installers
    if installer_ext == ".msi" and detection_settings.get("display_name"):
        if not override_display_name:
            logger.warning(
                "BUILD",
                "intune.detection.display_name is set but will be ignored for "
                "MSI installers. MSI ProductName is used as the authoritative "
                "source for registry DisplayName. Set "
                "override_msi_display_name: true to use display_name "
                "instead.",
            )

    if installer_ext == ".msi" and detection_settings.get("architecture"):
        logger.warning(
            "BUILD",
            "intune.detection.architecture is set but will be ignored for MSI "
            "installers. MSI Template is used as the authoritative source for "
            "architecture.",
        )

    # Warn about fields that will be ignored for MSIX installers
    if installer_ext == ".msix" and detection_settings.get("display_name"):
        logger.warning(
            "BUILD",
            "intune.detection.display_name is set but will be ignored for "
            "MSIX installers. MSIX DisplayName is used as the authoritative "
            "source for detection.",
        )

    if installer_ext == ".msix" and detection_settings.get("architecture"):
        logger.warning(
            "BUILD",
            "intune.detection.architecture is set but will be ignored for "
            "MSIX installers. MSIX ProcessorArchitecture is used as the "
            "authoritative source for architecture.",
        )

    # Warn about override flag on non-MSI installers
    if installer_ext != ".msi" and override_display_name:
        logger.warning(
            "BUILD",
            "intune.detection.override_msi_display_name is set but will "
            "be ignored for non-MSI installers. This flag only applies to "
            "MSI installers.",
        )

    expected_architecture: ArchitectureMode = "any"

    if installer_ext == ".msi":
        assert msi_metadata is not None  # guaranteed by build_package
        if override_display_name:
            if not detection_settings.get("display_name"):
                raise ConfigError(
                    "intune.detection.override_msi_display_name is true "
                    "but display_name is not set. Set "
                    "intune.detection.display_name when using "
                    "override_msi_display_name."
                )
            app_name = detection_settings["display_name"]
            app_name = app_name.replace("{{discovered_version}}", version)
            logger.verbose("BUILD", f"Using display_name (override): {app_name}")
        else:
            if not msi_metadata.product_name:
                raise ConfigError(
                    "MSI ProductName property not found. Cannot generate "
                    "scripts. Ensure the MSI file is valid and contains "
                    "ProductName property."
                )
            app_name = msi_metadata.product_name
            logger.verbose("BUILD", f"Using MSI ProductName: {app_name}")

        expected_architecture = msi_metadata.architecture
        logger.verbose("BUILD", f"MSI architecture: {expected_architecture}")

    elif installer_ext == ".msix":
        assert msix_metadata is not None  # guaranteed by build_package
        if not msix_metadata.display_name:
            raise ConfigError(
                "MSIX DisplayName property not found. Cannot generate "
                "scripts. Ensure the MSIX file is valid and contains "
                "a DisplayName in Properties."
            )
        app_name = msix_metadata.display_name
        logger.verbose("BUILD", f"Using MSIX DisplayName: {app_name}")

        expected_architecture = msix_metadata.architecture
        logger.verbose("BUILD", f"MSIX architecture: {expected_architecture}")

    elif detection_settings.get("display_name"):
        app_name = detection_settings["display_name"]
        app_name = app_name.replace("{{discovered_version}}", version)
        logger.verbose("BUILD", f"Using intune.detection.display_name: {app_name}")

        if detection_settings.get("architecture"):
            expected_architecture = cast(
                ArchitectureMode, detection_settings["architecture"]
            )
            logger.verbose(
                "BUILD",
                f"Using intune.detection.architecture: {expected_architecture}",
            )
        else:
            raise ConfigError(
                "intune.detection.architecture is required for EXE installers. "
                "Set intune.detection.architecture in the recipe. "
                "Allowed values: x86, x64, arm64, any"
            )
    else:
        raise ConfigError(
            "intune.detection.display_name is required for EXE installers. "
            "Set intune.detection.display_name in the recipe."
        )

    # The name is written into a comment line and the script filenames, where
    # a line break would end the comment or break the name.
    cleaned = strip_control_characters(app_name)
    if cleaned != app_name:
        logger.warning(
            "BUILD",
            f"App name {app_name!a} contains control characters; using "
            f"{cleaned!a} for scripts and filenames",
        )
        app_name = cleaned

    return app_name, expected_architecture


def _generate_detection_script(
    installer_file: Path,
    config: dict[str, Any],
    version: str,
    app_id: str,
    build_dir: Path,
    msi_metadata: MSIMetadata | None,
    msix_metadata: MSIXMetadata | None = None,
) -> Path:
    """Generate detection script for Intune Win32 app.

    Uses installer metadata (ProductName for MSI, DisplayName/IdentityName
    for MSIX) or intune.detection config for EXE installers. MSIX uses
    AppX package detection; MSI/EXE use registry-based detection. Saves
    the script as a sibling to the packagefiles directory.

    Args:
        installer_file: Path to the installer file.
        config: Recipe configuration.
        version: Extracted version string.
        app_id: Application ID.
        build_dir: Build directory (packagefiles subdirectory).
        msi_metadata: Pre-extracted MSI metadata (non-None for MSI
            installers).
        msix_metadata: Pre-extracted MSIX metadata (non-None for MSIX
            installers).

    Returns:
        Path to the generated detection script.

    Raises:
        ConfigError: If required configuration is missing.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    detection_settings = config["intune"]["detection"]
    logging_settings = config["logging"]
    installer_ext = installer_file.suffix.lower()

    app_name, architecture = _resolve_app_info(
        installer_file, config, version, msi_metadata, msix_metadata
    )

    sanitized_app_name = sanitize_filename(app_name, app_id)
    sanitized_version = version.replace(" ", "-")
    detection_filename = f"{sanitized_app_name}_{sanitized_version}-Detection.ps1"
    detection_script_path = build_dir.parent / detection_filename

    logger.verbose("DETECTION", f"Generating detection script: {detection_filename}")
    logger.verbose("DETECTION", f"AppName: {app_name}")
    logger.verbose("DETECTION", f"Version: {version}")

    if installer_ext == ".msix":
        assert msix_metadata is not None
        run_as_account = config["intune"]["run_as_account"]
        detection_config = MSIXDetectionConfig(
            identity_name=msix_metadata.identity_name,
            app_name=app_name,
            version=version,
            log_rotation_mb=logging_settings["log_rotation_mb"],
            exact_match=detection_settings["exact_match"],
            app_id=app_id,
            install_scope=run_as_account,
        )
        generate_msix_detection_script(detection_config, detection_script_path)
    else:
        use_wildcard = "*" in app_name or "?" in app_name
        detection_config = DetectionConfig(
            app_name=app_name,
            version=version,
            log_rotation_mb=logging_settings["log_rotation_mb"],
            exact_match=detection_settings["exact_match"],
            app_id=app_id,
            is_msi_installer=(installer_ext == ".msi"),
            expected_architecture=architecture,
            use_wildcard=use_wildcard,
        )
        generate_detection_script(detection_config, detection_script_path)

    return detection_script_path


def _generate_requirements_script(
    installer_file: Path,
    config: dict[str, Any],
    version: str,
    app_id: str,
    build_dir: Path,
    msi_metadata: MSIMetadata | None,
    msix_metadata: MSIXMetadata | None = None,
) -> Path:
    """Generate requirements script for Intune Win32 app (Update entry).

    Uses installer metadata (ProductName for MSI, DisplayName/IdentityName
    for MSIX) or intune.detection config for EXE installers. MSIX uses
    AppX package detection; MSI/EXE use registry-based detection. Saves
    the script as a sibling to the packagefiles directory.

    The requirements script determines if an older version is installed,
    making the Update entry applicable only to devices that need updating.

    Args:
        installer_file: Path to the installer file.
        config: Recipe configuration.
        version: Extracted version string (target version).
        app_id: Application ID.
        build_dir: Build directory (packagefiles subdirectory).
        msi_metadata: Pre-extracted MSI metadata (non-None for MSI
            installers).
        msix_metadata: Pre-extracted MSIX metadata (non-None for MSIX
            installers).

    Returns:
        Path to the generated requirements script.

    Raises:
        ConfigError: If required configuration is missing.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    logging_settings = config["logging"]
    installer_ext = installer_file.suffix.lower()

    app_name, architecture = _resolve_app_info(
        installer_file, config, version, msi_metadata, msix_metadata
    )

    sanitized_app_name = sanitize_filename(app_name, app_id)
    sanitized_version = version.replace(" ", "-")
    requirements_filename = f"{sanitized_app_name}_{sanitized_version}-Requirements.ps1"
    requirements_script_path = build_dir.parent / requirements_filename

    logger.verbose(
        "REQUIREMENTS",
        f"Generating requirements script: {requirements_filename}",
    )
    logger.verbose("REQUIREMENTS", f"AppName: {app_name}")
    logger.verbose("REQUIREMENTS", f"Version: {version}")

    if installer_ext == ".msix":
        assert msix_metadata is not None
        run_as_account = config["intune"]["run_as_account"]
        requirements_config = MSIXRequirementsConfig(
            identity_name=msix_metadata.identity_name,
            app_name=app_name,
            version=version,
            log_rotation_mb=logging_settings["log_rotation_mb"],
            app_id=app_id,
            install_scope=run_as_account,
        )
        generate_msix_requirements_script(requirements_config, requirements_script_path)
    else:
        use_wildcard = "*" in app_name or "?" in app_name
        requirements_config = RequirementsConfig(
            app_name=app_name,
            version=version,
            log_rotation_mb=logging_settings["log_rotation_mb"],
            app_id=app_id,
            is_msi_installer=(installer_ext == ".msi"),
            expected_architecture=architecture,
            use_wildcard=use_wildcard,
        )
        generate_requirements_script(requirements_config, requirements_script_path)

    return requirements_script_path


def _write_build_manifest(
    build_dir: Path,
    app_id: str,
    app_name: str,
    version: str,
    build_types: str,
    architecture: str,
    installer_sha256: str,
    detection_script_path: Path | None,
    requirements_script_path: Path | None,
) -> Path:
    """Write build manifest JSON to the build output directory.

    The manifest provides metadata about what was built, enabling downstream
    tools (like napt upload) to understand the build output without needing
    to re-derive paths or configuration.

    Args:
        build_dir: Build directory (packagefiles subdirectory).
        app_id: Application ID.
        app_name: Application display name.
        version: Application version.
        build_types: The build_types setting used ("both", "app_only", "update_only").
        architecture: Resolved installer architecture ("x86", "x64", "arm64", "any").
            Auto-detected from MSI Template for MSI installers; from recipe config
            for non-MSI installers.
        installer_sha256: SHA-256 hex digest of the source installer file,
            carried through so 'napt upload' can verify provenance.
        detection_script_path: Path to detection script, or None if not generated.
        requirements_script_path: Path to requirements script, or None if not generated.

    Returns:
        Path to the generated manifest file.

    Raises:
        OSError: If the manifest file cannot be written.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    # Build manifest content
    manifest = {
        "app_id": app_id,
        "app_name": app_name,
        "version": version,
        "win32_build_types": build_types,
        "architecture": architecture,
        "installer_sha256": installer_sha256,
    }

    # Add script paths (relative to version directory for portability)
    version_dir = build_dir.parent
    if detection_script_path:
        manifest["detection_script_path"] = detection_script_path.name
    if requirements_script_path:
        manifest["requirements_script_path"] = requirements_script_path.name

    # Write manifest to version directory (sibling to packagefiles/)
    manifest_path = version_dir / "build-manifest.json"

    try:
        manifest_json = json.dumps(manifest, indent=2)
        manifest_path.write_text(manifest_json, encoding="utf-8")
        logger.verbose("BUILD", f"Build manifest written to: {manifest_path}")
    except OSError as err:
        raise OSError(
            f"Failed to write build manifest to {manifest_path}: {err}"
        ) from err

    return manifest_path


def _apply_msix_commands(
    config: dict[str, Any],
    msix_metadata: MSIXMetadata,
    installer_file: Path,
    logger: Any,
) -> None:
    """Auto-generates MSIX install/uninstall commands or applies overrides.

    For MSIX installers, generates install/uninstall commands from manifest
    metadata. The commands vary based on ``intune.run_as_account``:

    - ``"system"`` (default): Uses ``Add-AppxProvisionedPackage`` for
      all-users provisioned install and ``Remove-AppxProvisionedPackage``
      for removal.
    - ``"user"``: Uses ``Add-AppxPackage`` for per-user install and
      ``Remove-AppxPackage`` for removal.

    If the recipe specifies ``psadt.install`` or ``psadt.uninstall``, those
    are ignored unless ``psadt.override_msix_commands`` is set to true.

    Args:
        config: Recipe configuration (mutated in place to inject
            auto-generated commands).
        msix_metadata: Pre-extracted MSIX metadata.
        installer_file: Path to the MSIX installer file.
        logger: Logger instance.

    Raises:
        ConfigError: If ``override_msix_commands`` is true but no
            ``psadt.install`` or ``psadt.uninstall`` is provided.
    """
    psadt_config = config["psadt"]
    override_commands = psadt_config.get("override_msix_commands", False)
    recipe_install = psadt_config.get("install")
    recipe_uninstall = psadt_config.get("uninstall")

    # The filename and identity come from the vendor, so both are emitted as
    # single-quoted literals; Join-Path keeps the filename out of an
    # expandable string.
    package_path = (
        f"(Join-Path $adtSession.DirFiles {ps_single_quote(installer_file.name)})"
    )
    identity = ps_single_quote(msix_metadata.identity_name)

    run_as_account = config["intune"]["run_as_account"]
    if run_as_account == "user":
        auto_install = f"Add-AppxPackage -Path {package_path}"
        auto_uninstall = f"Get-AppxPackage -Name {identity} | Remove-AppxPackage"
    else:
        auto_install = (
            f"Add-AppxProvisionedPackage -Online"
            f" -PackagePath {package_path}"
            f" -SkipLicense"
        )
        auto_uninstall = (
            f"Get-AppxProvisionedPackage -Online"
            f" | Where-Object {{ $_.DisplayName -eq {identity} }}"
            f" | Remove-AppxProvisionedPackage -Online"
        )

    if override_commands:
        if not recipe_install and not recipe_uninstall:
            raise ConfigError(
                "psadt.override_msix_commands is true but neither "
                "psadt.install nor psadt.uninstall is set. Set "
                "psadt.install and/or psadt.uninstall when using "
                "override_msix_commands."
            )
        if recipe_install:
            logger.verbose(
                "BUILD",
                "Using recipe psadt.install (override_msix_commands)",
            )
        else:
            config["psadt"]["install"] = auto_install
            logger.info("BUILD", f"Auto-generated MSIX install: {auto_install}")

        if recipe_uninstall:
            logger.verbose(
                "BUILD",
                "Using recipe psadt.uninstall (override_msix_commands)",
            )
        else:
            config["psadt"]["uninstall"] = auto_uninstall
            logger.info("BUILD", f"Auto-generated MSIX uninstall: {auto_uninstall}")
        return

    # No override flag: auto-generate and warn if recipe code is set
    if recipe_install:
        logger.warning(
            "BUILD",
            "psadt.install is set but will be ignored for MSIX installers. "
            "MSIX manifest is used as the authoritative source for install "
            "commands. Set override_msix_commands: true to use psadt.install "
            "instead.",
        )

    if recipe_uninstall:
        logger.warning(
            "BUILD",
            "psadt.uninstall is set but will be ignored for MSIX installers. "
            "MSIX manifest is used as the authoritative source for uninstall "
            "commands. Set override_msix_commands: true to use psadt.uninstall "
            "instead.",
        )

    config["psadt"]["install"] = auto_install
    config["psadt"]["uninstall"] = auto_uninstall
    logger.info("BUILD", f"Auto-generated MSIX install: {auto_install}")
    logger.info("BUILD", f"Auto-generated MSIX uninstall: {auto_uninstall}")


def _apply_msi_commands(
    config: dict[str, Any],
    msi_metadata: MSIMetadata,
    installer_file: Path,
    logger: Any,
) -> None:
    """Auto-generates MSI install/uninstall commands or applies overrides.

    For MSI installers, generates:

    - Install: ``Start-ADTMsiProcess -Action Install`` with the exact
      installer filename. PSADT's configuration supplies the silent-install
      arguments and verbose logging. When ``intune.run_as_account`` is
      ``"system"``, ``ALLUSERS=1`` is appended via ``-AdditionalArgumentList``
      to force a per-machine installation.
    - Uninstall: ``Uninstall-ADTApplication`` matching the MSI ProductName
      exactly, restricted to MSI applications. Name-based matching is used
      instead of ProductCode so uninstall keeps working when vendors change
      the ProductCode between versions.

    If the recipe specifies ``psadt.install`` or ``psadt.uninstall``, those
    are ignored unless ``psadt.override_msi_commands`` is set to true.

    Args:
        config: Recipe configuration (mutated in place to inject
            auto-generated commands).
        msi_metadata: Pre-extracted MSI metadata.
        installer_file: Path to the MSI installer file.
        logger: Logger instance.

    Raises:
        ConfigError: If ``override_msi_commands`` is true but no
            ``psadt.install`` or ``psadt.uninstall`` is provided, or if the
            MSI has no ProductName when the uninstall command must be
            auto-generated.

    Note:
        The ProductName check only fires when the uninstall command is
        actually auto-generated, so override recipes that supply their own
        uninstall still build against MSIs lacking ProductName.
    """
    psadt_config = config["psadt"]
    override_commands = psadt_config.get("override_msi_commands", False)
    recipe_install = psadt_config.get("install")
    recipe_uninstall = psadt_config.get("uninstall")

    auto_install = (
        "Start-ADTMsiProcess -Action Install"
        f" -FilePath {ps_single_quote(installer_file.name)}"
    )
    if config["intune"]["run_as_account"] == "system":
        auto_install += ' -AdditionalArgumentList "ALLUSERS=1"'

    def auto_uninstall() -> str:
        if not msi_metadata.product_name:
            raise ConfigError(
                "MSI ProductName property not found. Cannot auto-generate "
                "the uninstall command. Set override_msi_commands: true and "
                "provide psadt.uninstall, or ensure the MSI file contains "
                "ProductName."
            )
        quoted_name = ps_single_quote(msi_metadata.product_name)
        return (
            f"Uninstall-ADTApplication -Name {quoted_name}"
            " -NameMatch 'Exact' -ApplicationType 'MSI'"
        )

    if override_commands:
        if not recipe_install and not recipe_uninstall:
            raise ConfigError(
                "psadt.override_msi_commands is true but neither "
                "psadt.install nor psadt.uninstall is set. Set "
                "psadt.install and/or psadt.uninstall when using "
                "override_msi_commands."
            )
        if recipe_install:
            logger.verbose(
                "BUILD",
                "Using recipe psadt.install (override_msi_commands)",
            )
        else:
            config["psadt"]["install"] = auto_install
            logger.info("BUILD", f"Auto-generated MSI install: {auto_install}")

        if recipe_uninstall:
            logger.verbose(
                "BUILD",
                "Using recipe psadt.uninstall (override_msi_commands)",
            )
        else:
            config["psadt"]["uninstall"] = auto_uninstall()
            logger.info(
                "BUILD",
                f"Auto-generated MSI uninstall: {config['psadt']['uninstall']}",
            )
        return

    # No override flag: auto-generate and warn if recipe code is set
    if recipe_install:
        logger.warning(
            "BUILD",
            "psadt.install is set but will be ignored for MSI installers. "
            "Install commands are auto-generated from the MSI. Set "
            "override_msi_commands: true to use psadt.install instead.",
        )

    if recipe_uninstall:
        logger.warning(
            "BUILD",
            "psadt.uninstall is set but will be ignored for MSI installers. "
            "Uninstall commands are auto-generated from the MSI. Set "
            "override_msi_commands: true to use psadt.uninstall instead.",
        )

    config["psadt"]["install"] = auto_install
    config["psadt"]["uninstall"] = auto_uninstall()
    logger.info("BUILD", f"Auto-generated MSI install: {auto_install}")
    logger.info(
        "BUILD",
        f"Auto-generated MSI uninstall: {config['psadt']['uninstall']}",
    )


def _require_exe_scripts(config: dict[str, Any]) -> None:
    """Checks that an EXE recipe supplies its own install and uninstall scripts.

    MSI and MSIX installers carry enough metadata to auto-generate the
    commands; EXE installers do not, so the recipe must provide both.

    Args:
        config: Effective configuration for the recipe.

    Raises:
        ConfigError: If ``psadt.install`` or ``psadt.uninstall`` is missing
            or blank.
    """
    psadt_scripts = config["psadt"]
    missing = [
        key
        for key in ("install", "uninstall")
        if not str(psadt_scripts.get(key) or "").strip()
    ]
    if missing:
        raise ConfigError(
            f"psadt.{' and psadt.'.join(missing)} required for EXE "
            "installers: NAPT can only auto-generate install and "
            "uninstall commands for MSI and MSIX packages"
        )


def _extract_app_icon(
    config: dict[str, Any], installer_file: Path, app_id: str
) -> None:
    """Extracts the app icon from the installer into the icons directory.

    Best-effort side task that never raises: a failed extraction warns and
    the build continues. Skipped when intune.logo_path is set (the explicit
    icon wins at upload) or when the icon file already exists (users may
    drop curated replacements into the icons directory; NAPT never
    overwrites them).

    A failed extraction is recorded in a ``{app_id}.no-icon`` marker so
    expensive MSI extraction is not repeated every build. The marker
    invalidates itself when the installer file changes and is removed on a
    successful extraction.

    Args:
        config: Merged effective configuration.
        installer_file: Path to the downloaded installer.
        app_id: Recipe id; the icon is written to
            ``{directories.icons}/{app_id}.png``.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    if config["intune"].get("logo_path"):
        logger.info("BUILD", "Skipping icon extraction: intune.logo_path is set")
        return

    icons_dir = Path(config["directories"]["icons"])
    icon_path = icons_dir / f"{app_id}.png"
    if icon_path.exists():
        logger.info("BUILD", f"Skipping icon extraction: {icon_path} already exists")
        return

    marker_path = icons_dir / f"{app_id}.no-icon"
    stat = installer_file.stat()
    fingerprint = f"{installer_file.name}|{stat.st_size}|{stat.st_mtime_ns}"
    if marker_path.exists():
        try:
            marker_matches = (
                marker_path.read_text(encoding="utf-8").strip() == fingerprint
            )
        except OSError:
            marker_matches = False
        if marker_matches:
            logger.info(
                "BUILD",
                "Skipping icon extraction: no icon was found in this "
                "installer previously",
            )
            return

    result = extract_icon_png(installer_file)
    if result.png is None:
        try:
            icons_dir.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(fingerprint, encoding="utf-8")
        except OSError:
            pass
        logger.warning(
            "BUILD",
            f"No app icon extracted from {installer_file.name}: {result.detail}. "
            f"The Intune app entry will be created without a logo. Place a PNG "
            f"at {icon_path} or set intune.logo_path to provide an icon "
            f"manually.",
        )
        return

    try:
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        icon_path.write_bytes(result.png)
        marker_path.unlink(missing_ok=True)
    except OSError as err:
        logger.warning("BUILD", f"Could not write app icon to {icon_path}: {err}")
        return
    logger.info("BUILD", f"Extracted app icon ({result.width}px): {icon_path}")
    logger.verbose("BUILD", f"Icon source: {result.detail}")


def build_package(
    recipe_path: Path,
    downloads_dir: Path | None = None,
    output_dir: Path | None = None,
) -> BuildResult:
    """Build a PSADT package from a recipe and downloaded installer.

    This is the main entry point for the build process. It:

    1. Loads the recipe configuration
    2. Finds the downloaded installer
    3. Extracts version from installer (filesystem is truth)
    4. Gets/downloads PSADT release
    5. Creates build directory structure
    6. Copies PSADT files unmodified
    7. Generates Invoke-AppDeployToolkit.ps1 from template
    8. Copies installer to Files/
    9. Applies custom branding
    10. Generates detection script (always; used by App entry and by Update entry)
    11. Generates requirements script (when build_types is "both" or "update_only")

    Args:
        recipe_path: Path to the recipe YAML file.
        downloads_dir: Directory containing the downloaded
            installer. Default: Path("downloads")
        output_dir: Base directory for build output.
            Default: From config or Path("builds")

    Returns:
        Build result containing app metadata, build paths, PSADT version, and
            generated script paths.

    Raises:
        FileNotFoundError: If recipe or installer doesn't exist.
        PackagingError: If build process fails or script generation fails.
        ConfigError: If required configuration is missing.

    Example:
        Basic build:
            ```python
            result = build_package(Path("recipes/Google/chrome.yaml"))
            print(result.build_dir)  # builds/napt-chrome/141.0.7390.123
            print(result.build_types)  # "both"
            ```

        Custom output directory:
            ```python
            result = build_package(
                Path("recipes/Google/chrome.yaml"),
                output_dir=Path("custom/builds")
            )
            ```

    Note:
        Requires installer to be downloaded first (run 'napt discover').
        Version extracted from installer file, not state cache.
        Overwrites existing build directory if it exists.
        PSADT files are copied unmodified from cache.
        Invoke-AppDeployToolkit.ps1 is generated (not copied).
        Scripts are generated as siblings to the packagefiles directory
        (not included in .intunewin package - must be uploaded separately to Intune).
        Detection script is always generated.
        The build_types setting controls requirements script only: "both" (default)
        generates detection and requirements, "app_only" generates only detection,
        "update_only" generates detection and requirements.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    # Load configuration
    logger.step(1, 8, "Loading configuration...")
    config = load_effective_config(recipe_path)

    app_id = config["id"]
    app_name = config["name"]

    # Set defaults
    if downloads_dir is None:
        downloads_dir = Path(config["directories"]["discover"])

    if output_dir is None:
        output_dir = Path(config["directories"]["build"])

    # Find installer file
    logger.step(2, 8, "Finding installer...")
    installer_file, installer_sha256 = _find_installer_file(
        downloads_dir, app_id, _release_to_build(config)
    )

    # MSI and MSIX report their own version; otherwise the discovered one
    logger.step(3, 8, "Determining version...")
    version = _get_installer_version(installer_file)

    logger.info("BUILD", f"Building {app_name} v{version}")

    # Extract installer metadata upfront (or validate EXE architecture from recipe)
    installer_ext = installer_file.suffix.lower()
    msi_metadata: MSIMetadata | None = None
    msix_metadata: MSIXMetadata | None = None

    if installer_ext == ".msi":
        msi_metadata = extract_msi_metadata(installer_file)
        architecture: str = msi_metadata.architecture
    elif installer_ext == ".msix":
        msix_metadata = extract_msix_metadata(installer_file)
        architecture = msix_metadata.architecture
    else:
        detection_settings = config["intune"]["detection"]
        architecture = detection_settings.get("architecture") or ""
        if not architecture:
            raise ConfigError(
                "intune.detection.architecture is required for EXE "
                "installers. Set intune.detection.architecture in the "
                "recipe. Allowed values: x86, x64, arm64, any"
            )
        _require_exe_scripts(config)

    # Extract the app icon for Intune (best-effort; warns instead of failing)
    _extract_app_icon(config, installer_file, app_id)

    # Get PSADT release
    logger.step(4, 8, "Getting PSADT release...")
    psadt_config = config["psadt"]
    release_spec = psadt_config["release"]
    cache_dir = Path(psadt_config["cache_dir"])

    psadt_cache_dir = get_psadt_release(release_spec, cache_dir)
    psadt_version = psadt_cache_dir.name  # Directory name is the version

    logger.info("BUILD", f"Using PSADT {psadt_version}")

    # Create build directory
    logger.step(5, 8, "Creating build structure...")
    build_dir = _create_build_directory(output_dir, app_id, version)

    # Copy PSADT files
    _copy_psadt_template(psadt_cache_dir, build_dir)

    # Auto-generate install/uninstall commands (or warn if overridden)
    if installer_ext == ".msix":
        assert msix_metadata is not None
        _apply_msix_commands(config, msix_metadata, installer_file, logger)
    elif installer_ext == ".msi":
        assert msi_metadata is not None
        _apply_msi_commands(config, msi_metadata, installer_file, logger)

    # Generate Invoke-AppDeployToolkit.ps1
    from .template import generate_invoke_script

    template_path = psadt_cache_dir / "Invoke-AppDeployToolkit.ps1"
    invoke_script = generate_invoke_script(
        template_path,
        config,
        version,
        psadt_version,
        architecture,
        installer_file.name,
    )

    # Write generated script
    script_dest = build_dir / "Invoke-AppDeployToolkit.ps1"
    script_dest.write_text(invoke_script, encoding=PS_SCRIPT_ENCODING)
    logger.verbose("BUILD", "[OK] Generated Invoke-AppDeployToolkit.ps1")

    # Copy installer
    _copy_installer(installer_file, build_dir)

    # Apply branding
    logger.step(6, 8, "Applying branding...")
    _apply_branding(config, build_dir)

    # Get build_types configuration
    build_types = config["intune"]["build_types"]

    detection_script_path = None
    requirements_script_path = None

    # Generate detection script (always; needed for App and Update entries)
    logger.step(7, 8, "Generating detection script...")
    detection_script_path = _generate_detection_script(
        installer_file,
        config,
        version,
        app_id,
        build_dir,
        msi_metadata,
        msix_metadata,
    )
    logger.verbose("BUILD", "[OK] Detection script generated")

    # Generate requirements script (for "both" or "update_only")
    if build_types in ("both", "update_only"):
        logger.step(8, 8, "Generating requirements script...")
        requirements_script_path = _generate_requirements_script(
            installer_file,
            config,
            version,
            app_id,
            build_dir,
            msi_metadata,
            msix_metadata,
        )
        logger.verbose("BUILD", "[OK] Requirements script generated")
    else:
        logger.step(8, 8, "Skipping requirements script (build_types=app_only)...")

    # Write build manifest
    _write_build_manifest(
        build_dir=build_dir,
        app_id=app_id,
        app_name=app_name,
        version=version,
        build_types=build_types,
        architecture=architecture,
        installer_sha256=installer_sha256,
        detection_script_path=detection_script_path,
        requirements_script_path=requirements_script_path,
    )

    logger.verbose("BUILD", f"[OK] Build complete: {build_dir}")

    return BuildResult(
        app_id=app_id,
        app_name=app_name,
        version=version,
        build_dir=build_dir,
        psadt_version=psadt_version,
        status="success",
        build_types=build_types,
        detection_script_path=detection_script_path,
        requirements_script_path=requirements_script_path,
    )
