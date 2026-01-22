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
    - Entire PSADT Template_v4 structure copied pristine
    - Invoke-AppDeployToolkit.ps1 is generated from template (not copied)
    - Build directories are versioned: {app_id}/{version}/
    - Branding applied by replacing files in root Assets/ directory (v4 structure)

Example:
    Basic usage:
        ```python
        from pathlib import Path
        from notapkgtool.build import build_package

        result = build_package(
            recipe_path=Path("recipes/Google/chrome.yaml"),
            downloads_dir=Path("downloads"),
        )

        print(f"Built: {result.build_dir}")
        ```
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from notapkgtool.config import load_effective_config
from notapkgtool.detection import (
    DetectionConfig,
    generate_detection_script,
    sanitize_filename,
)
from notapkgtool.exceptions import ConfigError, PackagingError
from notapkgtool.psadt import get_psadt_release
from notapkgtool.results import BuildResult
from notapkgtool.versioning.msi import (
    extract_msi_metadata,
    version_from_msi_product_version,
)


def _get_installer_version(
    installer_file: Path, config: dict[str, Any], state_file: Path | None = None
) -> str:
    """Get version for the installer file.

    Priority:
        1. Auto-detect MSI files (`.msi` extension) and extract version
        2. Fall back to known_version from state file
        3. If all else fails, raise an error

    Args:
        installer_file: Path to the installer file.
        config: Recipe configuration.
        state_file: Path to state file for fallback version lookup.

    Returns:
        Extracted version string.

    Raises:
        PackagingError: If MSI version extraction fails (when explicitly requested).
        ConfigError: If version cannot be determined from any source.
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    app = config["app"]
    app_id = app.get("id", "unknown")

    # Priority 1: Auto-detect MSI files and extract version
    if installer_file.suffix.lower() == ".msi":
        logger.verbose(
            "BUILD", f"Auto-detected MSI, extracting version: {installer_file.name}"
        )
        try:
            discovered = version_from_msi_product_version(installer_file)
            logger.verbose("BUILD", f"Extracted version: {discovered.version}")
            return discovered.version
        except Exception as err:
            # MSI extraction failed, fall through to state file
            logger.verbose(
                "BUILD", f"MSI version extraction failed, trying state file: {err}"
            )

    # Priority 2: Fall back to state file
    if state_file and state_file.exists():
        from notapkgtool.state import load_state

        logger.verbose("BUILD", "Using version from state file")
        state = load_state(state_file)
        app_state = state.get("apps", {}).get(app_id, {})
        known_version = app_state.get("known_version")

        if known_version:
            logger.verbose("BUILD", f"Using version from state: {known_version}")
            return known_version

    # No version found - provide error
    raise ConfigError(
        f"Could not determine version for {app_id}. Either:\n"
        f"  - Use an MSI installer (auto-detected from file extension)\n"
        f"  - Run 'napt discover' first to populate state file with version"
    )


def _find_installer_file(
    downloads_dir: Path, config: dict[str, Any], state_file: Path | None = None
) -> Path:
    """Find the installer file in the downloads directory.

    Uses multiple strategies to locate the installer:
    1. URL from recipe (for url_download strategy)
    2. URL from state file (for web_scrape, api_github, api_json strategies)
    3. Filename matching by app name/id
    4. Most recent installer (last resort)

    Args:
        downloads_dir: Downloads directory to search.
        config: Recipe configuration.
        state_file: Optional state file to check for cached URL.

    Returns:
        Path to the installer file.

    Raises:
        PackagingError: If installer file cannot be found.
    """
    from urllib.parse import urlparse

    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    app = config["app"]
    app_id = app.get("id", "")
    source = app.get("source", {})
    url = source.get("url", "")

    # Strategy 1: Extract filename from recipe URL (for url_download)
    if url:
        parsed = urlparse(url)
        filename = Path(parsed.path).name
        if filename:
            installer_path = downloads_dir / filename

            if installer_path.exists():
                logger.verbose(
                    "BUILD", f"Found installer from recipe URL: {installer_path}"
                )
                return installer_path

    # Strategy 2: Extract filename from state file URL (for web_scrape, etc.)
    if state_file and state_file.exists():
        try:
            from notapkgtool.state import load_state

            state = load_state(state_file)
            app_state = state.get("apps", {}).get(app_id, {})
            state_url = app_state.get("url", "")

            if state_url:
                parsed = urlparse(state_url)
                filename = Path(parsed.path).name
                if filename:
                    installer_path = downloads_dir / filename

                    if installer_path.exists():
                        logger.verbose(
                            "BUILD", f"Found installer from state URL: {installer_path}"
                        )
                        return installer_path
        except Exception as err:
            logger.warning("BUILD", f"Could not check state file: {err}")

    # Strategy 3: Fallback - Search for installer matching app name/id
    app_name = app.get("name", "").lower()

    # Try to find installer matching app_id or app_name in filename
    for pattern in ["*.msi", "*.exe"]:
        matches = list(downloads_dir.glob(pattern))

        # Filter by app name/id if possible
        matching = [
            p
            for p in matches
            if app_id.lower().replace("napt-", "") in p.name.lower()
            or any(word in p.name.lower() for word in app_name.split() if len(word) > 3)
        ]

        if matching:
            installer_path = max(matching, key=lambda p: p.stat().st_mtime)
            logger.verbose("BUILD", f"Found installer matching app: {installer_path}")
            return installer_path

    # No installer found after trying all strategies
    raise PackagingError(
        f"Cannot locate installer file for {app_id} in {downloads_dir}. "
        f"Tried locating via recipe URL, state file URL, and filename matching, "
        f"but no matching installer found. Verify the installer file exists in {downloads_dir}."
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
        Path to the packagefiles subdirectory (build_dir/packagefiles/).

    Raises:
        OSError: If directory creation fails.
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
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


def _copy_psadt_pristine(psadt_cache_dir: Path, build_dir: Path) -> None:
    """Copy PSADT template files from cache to build directory (pristine, unmodified).

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
    from notapkgtool.logging import get_global_logger

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
    from notapkgtool.logging import get_global_logger

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
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    brand_pack = config.get("defaults", {}).get("psadt", {}).get("brand_pack")

    if not brand_pack:
        logger.verbose("BUILD", "No brand pack configured, using PSADT defaults")
        return

    brand_path = Path(brand_pack.get("path", ""))
    mappings = brand_pack.get("mappings", [])

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


def _generate_detection_script(
    installer_file: Path,
    config: dict[str, Any],
    version: str,
    app_id: str,
    build_dir: Path,
) -> Path:
    """Generate detection script for Intune Win32 app.

    Extracts metadata from installer (MSI ProductName for MSIs, detection.display_name
    for non-MSI installers), generates PowerShell detection script, and saves it as a
    sibling to the packagefiles directory.

    Args:
        installer_file: Path to the installer file.
        config: Recipe configuration.
        version: Extracted version string.
        app_id: Application ID.
        build_dir: Build directory (packagefiles subdirectory).

    Returns:
        Path to the generated detection script.

    Raises:
        PackagingError: If detection script generation fails.
        ConfigError: If required configuration is missing (detection.display_name
            required for non-MSI installers).
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    app = config["app"]

    # Get detection configuration (merged defaults + app-specific)
    defaults_detection = config.get("defaults", {}).get("detection", {})
    app_detection = app.get("detection", {})
    detection_config_dict = {**defaults_detection, **app_detection}

    # Determine AppName for detection
    app_name_for_detection = None
    installer_ext = installer_file.suffix.lower()

    # Check if display_name is set for MSI installers (not allowed)
    if installer_ext == ".msi" and detection_config_dict.get("display_name"):
        logger.warning(
            "DETECTION",
            "detection.display_name is set but will be ignored for MSI installers. "
            "MSI ProductName is used as the authoritative source for registry "
            "DisplayName.",
        )

    if installer_ext == ".msi":
        # MSI: Use ProductName (required, no fallback - authoritative source)
        try:
            msi_metadata = extract_msi_metadata(installer_file)
            if not msi_metadata.product_name:
                raise ConfigError(
                    "MSI ProductName property not found. Cannot generate detection "
                    "script. Ensure the MSI file is valid and contains ProductName "
                    "property."
                )
            app_name_for_detection = msi_metadata.product_name
            logger.verbose(
                "DETECTION",
                f"Using MSI ProductName for detection: {app_name_for_detection}",
            )
        except ConfigError:
            # Re-raise ConfigError as-is (e.g., ProductName not found)
            raise
        except Exception as err:
            # Wrap other exceptions (extraction failures) as ConfigError
            raise ConfigError(
                f"Failed to extract MSI ProductName. Cannot generate detection script. "
                f"Error: {err}"
            ) from err
    elif detection_config_dict.get("display_name"):
        # Non-MSI: Use explicit display_name (required)
        app_name_for_detection = detection_config_dict["display_name"]
        logger.verbose(
            "DETECTION",
            f"Using detection.display_name: {app_name_for_detection}",
        )
    else:
        # Non-MSI: display_name required
        raise ConfigError(
            "detection.display_name is required for non-MSI installers. "
            "Set detection.display_name in recipe configuration."
        )

    # Create DetectionConfig from merged configuration
    detection_config_obj = DetectionConfig(
        app_name=app_name_for_detection,
        version=version,
        log_format=detection_config_dict.get("log_format", "cmtrace"),
        log_level=detection_config_dict.get("log_level", "INFO"),
        log_rotation_mb=detection_config_dict.get("log_rotation_mb", 10),
        exact_match=detection_config_dict.get("exact_match", True),
        app_id=app_id,
    )

    # Sanitize AppName for filename
    sanitized_app_name = sanitize_filename(app_name_for_detection, app_id)
    sanitized_version = version.replace(
        " ", "-"
    )  # Versions shouldn't have spaces, but be safe

    # Build detection script filename: {AppName}_{Version}-Detection.ps1
    detection_filename = f"{sanitized_app_name}_{sanitized_version}-Detection.ps1"

    # Save as sibling to packagefiles/ (build_dir.parent is the version directory)
    detection_script_path = build_dir.parent / detection_filename

    logger.verbose("DETECTION", f"Generating detection script: {detection_filename}")
    logger.verbose("DETECTION", f"AppName: {app_name_for_detection}")
    logger.verbose("DETECTION", f"Version: {version}")

    # Generate the script
    generate_detection_script(detection_config_obj, detection_script_path)

    return detection_script_path


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
    6. Copies PSADT files (pristine)
    7. Generates Invoke-AppDeployToolkit.ps1 from template
    8. Copies installer to Files/
    9. Applies custom branding
    10. Generates detection script for Intune Win32 app deployment

    Args:
        recipe_path: Path to the recipe YAML file.
        downloads_dir: Directory containing the downloaded
            installer. Default: Path("downloads")
        output_dir: Base directory for build output.
            Default: From config or Path("builds")

    Returns:
        BuildResult dataclass with the following fields:

            - app_id (str): Unique application identifier from recipe configuration.
            - app_name (str): Application display name from recipe configuration.
            - version (str): Application version extracted from installer file (filesystem
                is source of truth).
            - build_dir (Path): Path to the created build directory, following the pattern
                {output_dir}/{app_id}/{version}/.
            - psadt_version (str): PSADT version used for the build (e.g., "4.1.7").
            - status (str): Build status, typically "success" for completed builds.
            - detection_script_path (Path | None): Path to the generated detection script,
                or None if detection script generation was skipped or failed (non-fatal).

    Raises:
        FileNotFoundError: If recipe or installer doesn't exist.
        PackagingError: If build process fails or detection script generation fails
            (when fail_on_error=true in detection config).
        ConfigError: If required configuration is missing.

    Example:
        Basic build:
            ```python
            result = build_package(Path("recipes/Google/chrome.yaml"))
            print(result.build_dir)  # builds/napt-chrome/141.0.7390.123
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
        Version extracted from installer file, not state cache. Overwrites
        existing build directory if it exists. PSADT files are copied pristine
        from cache. Invoke-AppDeployToolkit.ps1 is generated (not copied).
        Detection script is generated as a sibling to the packagefiles directory
        (not included in .intunewin package - must be uploaded separately to Intune).
        Detection script generation can be configured as non-fatal via
        detection.fail_on_error setting in recipe configuration.
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    # Load configuration
    logger.step(1, 6, "Loading configuration...")
    config = load_effective_config(recipe_path)

    app = config["apps"][0]
    app_id = app.get("id", "unknown-app")
    app_name = app.get("name", "Unknown App")

    # Set defaults
    if downloads_dir is None:
        downloads_dir = Path("downloads")

    if output_dir is None:
        output_dir = Path(
            config.get("defaults", {}).get("build", {}).get("output_dir", "builds")
        )

    # Find installer file
    logger.step(2, 6, "Finding installer...")
    state_file = Path("state/versions.json")  # Default state file location
    installer_file = _find_installer_file(downloads_dir, config, state_file)

    # Extract version from installer or state (filesystem + state are truth)
    logger.step(3, 6, "Determining version...")
    version = _get_installer_version(installer_file, config, state_file)

    logger.verbose("BUILD", f"Building {app_name} v{version}")

    # Get PSADT release
    logger.step(4, 6, "Getting PSADT release...")
    psadt_config = config.get("defaults", {}).get("psadt", {})
    release_spec = psadt_config.get("release", "latest")
    cache_dir = Path(psadt_config.get("cache_dir", "cache/psadt"))

    psadt_cache_dir = get_psadt_release(release_spec, cache_dir)
    psadt_version = psadt_cache_dir.name  # Directory name is the version

    logger.verbose("BUILD", f"Using PSADT {psadt_version}")

    # Create build directory
    logger.step(5, 6, "Creating build structure...")
    build_dir = _create_build_directory(output_dir, app_id, version)

    # Copy PSADT files (pristine)
    _copy_psadt_pristine(psadt_cache_dir, build_dir)

    # Generate Invoke-AppDeployToolkit.ps1
    from .template import generate_invoke_script

    template_path = psadt_cache_dir / "Invoke-AppDeployToolkit.ps1"
    invoke_script = generate_invoke_script(
        template_path, config, version, psadt_version
    )

    # Write generated script
    script_dest = build_dir / "Invoke-AppDeployToolkit.ps1"
    script_dest.write_text(invoke_script, encoding="utf-8")
    logger.verbose("BUILD", "[OK] Generated Invoke-AppDeployToolkit.ps1")

    # Copy installer
    _copy_installer(installer_file, build_dir)

    # Apply branding
    logger.step(6, 7, "Applying branding...")
    _apply_branding(config, build_dir)

    # Generate detection script
    logger.step(7, 7, "Generating detection script...")
    detection_script_path = None
    try:
        detection_script_path = _generate_detection_script(
            installer_file, config, version, app_id, build_dir
        )
        logger.verbose("BUILD", "[OK] Detection script generated")
    except Exception as err:
        detection_config = config.get("defaults", {}).get("detection", {}) or app.get(
            "detection", {}
        )
        fail_on_error = detection_config.get("fail_on_error", True)

        if fail_on_error:
            raise PackagingError(
                f"Detection script generation failed (fail_on_error=true): {err}"
            ) from err
        else:
            logger.warning(
                "BUILD",
                f"Detection script generation failed (non-fatal): {err}",
            )
            logger.verbose("BUILD", "Continuing build without detection script...")

    logger.verbose("BUILD", f"[OK] Build complete: {build_dir}")

    return BuildResult(
        app_id=app_id,
        app_name=app_name,
        version=version,
        build_dir=build_dir,
        psadt_version=psadt_version,
        status="success",
        detection_script_path=detection_script_path,
    )
