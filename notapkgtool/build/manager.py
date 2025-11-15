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

Private Helpers:
    - _get_installer_version: Extract version from downloaded installer
    - _find_installer_file: Locate installer in downloads directory
    - _create_build_directory: Create build directory structure
    - _copy_psadt_pristine: Copy PSADT files from cache
    - _copy_installer: Copy installer to Files/ directory
    - _apply_branding: Replace PSADT assets with custom branding

Design Principles:
    - Filesystem is source of truth for version information
    - Entire PSADT Template_v4 structure copied pristine
    - Invoke-AppDeployToolkit.ps1 is generated from template (not copied)
    - Build directories are versioned: {app_id}/{version}/
    - Branding applied by replacing files in root Assets/ directory (v4 structure)

Example:
    from pathlib import Path
    from notapkgtool.build import build_package

    result = build_package(
        recipe_path=Path("recipes/Google/chrome.yaml"),
        downloads_dir=Path("downloads"),
    )

    print(f"Built: {result['build_dir']}")
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from notapkgtool.config import load_effective_config
from notapkgtool.psadt import get_psadt_release
from notapkgtool.versioning.msi import version_from_msi_product_version


def _get_installer_version(
    installer_file: Path, config: dict[str, Any], state_file: Path | None = None
) -> str:
    """Extract version from installer file or state.

    Uses the version extraction method specified in the recipe's
    source configuration. If no version.type is specified (e.g., for
    api_github strategy), attempts to read from state file.

    Args:
        installer_file: Path to the installer file.
        config: Recipe configuration.
        state_file: Path to state file for fallback version
            lookup.

    Returns:
        Extracted version string.

    Raises:
        RuntimeError: If version extraction fails or version not found.
        ValueError: If version type is unsupported.
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    app = config["apps"][0]
    app_id = app.get("id", "unknown")
    source = app.get("source", {})
    version_config = source.get("version", {})
    version_type = version_config.get("type", "")

    logger.verbose("BUILD", f"Extracting version from: {installer_file.name}")
    logger.verbose("BUILD", f"Version type: {version_type}")

    # If no version type specified, try to use version from state
    if not version_type:
        if state_file and state_file.exists():
            from notapkgtool.state import load_state

            logger.verbose("BUILD", "No version type specified, using state file")
            state = load_state(state_file)
            app_state = state.get("apps", {}).get(app_id, {})
            known_version = app_state.get("known_version")

            if known_version:
                logger.verbose("BUILD", f"Using version from state: {known_version}")
                return known_version
            else:
                raise ValueError(
                    f"No version.type specified and no known_version in state for {app_id}. "
                    f"Run 'napt discover' first or add version.type to recipe."
                )
        else:
            raise ValueError(
                "No version.type specified in recipe. Add source.version.type or ensure state file exists."
            )

    if version_type == "msi":
        try:
            discovered = version_from_msi_product_version(installer_file)
            logger.verbose("BUILD", f"Extracted version: {discovered.version}")
            return discovered.version
        except Exception as err:
            raise RuntimeError(
                f"Failed to extract MSI version from {installer_file}: {err}"
            ) from err
    else:
        raise ValueError(
            f"Unsupported version type for build: {version_type!r}. " f"Supported: msi"
        )


def _find_installer_file(downloads_dir: Path, config: dict[str, Any]) -> Path:
    """Find the installer file in the downloads directory.

    Uses the URL from the recipe to determine the expected filename.

    Args:
        downloads_dir: Downloads directory to search.
        config: Recipe configuration.

    Returns:
        Path to the installer file.

    Raises:
        FileNotFoundError: If installer file cannot be found.
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    app = config["apps"][0]
    source = app.get("source", {})
    url = source.get("url", "")

    # Extract filename from URL
    if url:
        filename = url.split("/")[-1]
        installer_path = downloads_dir / filename

        if installer_path.exists():
            logger.verbose("BUILD", f"Found installer: {installer_path}")
            return installer_path

    # Fallback: Search for installer matching app name/id or use most recent
    app_id = app.get("id", "")
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

    # Ultimate fallback: Most recent installer of any type
    all_installers = list(downloads_dir.glob("*.msi")) + list(
        downloads_dir.glob("*.exe")
    )
    if all_installers:
        installer_path = max(all_installers, key=lambda p: p.stat().st_mtime)
        logger.verbose("BUILD", f"Found most recent installer: {installer_path}")
        return installer_path

    raise FileNotFoundError(
        f"No installer found in {downloads_dir}. "
        f"Run 'napt discover' first to download the installer."
    )


def _create_build_directory(base_dir: Path, app_id: str, version: str) -> Path:
    """Create the build directory structure.

    Args:
        base_dir: Base builds directory.
        app_id: Application ID.
        version: Application version.

    Returns:
        Path to the created build directory.

    Raises:
        OSError: If directory creation fails.
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    build_dir = base_dir / app_id / version

    if build_dir.exists():
        logger.verbose("BUILD", f"Build directory exists: {build_dir}")
        logger.verbose("BUILD", "Removing existing build...")
        shutil.rmtree(build_dir)

    # Create the build directory (template will provide subdirectories)
    build_dir.mkdir(parents=True, exist_ok=True)

    logger.verbose("BUILD", f"Created build directory: {build_dir}")

    return build_dir


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
        build_dir: Build directory where PSADT should be copied.

    Raises:
        FileNotFoundError: If PSADT cache directory or required files don't exist.
        OSError: If copy operation fails.
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    if not psadt_cache_dir.exists():
        raise FileNotFoundError(f"PSADT cache directory not found: {psadt_cache_dir}")

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
        build_dir: Build directory.

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
        build_dir: Build directory containing PSAppDeployToolkit/.

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


def build_package(
    recipe_path: Path,
    downloads_dir: Path | None = None,
    output_dir: Path | None = None,
    verbose: bool = False,
    debug: bool = False,
) -> dict[str, Any]:
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

    Args:
        recipe_path: Path to the recipe YAML file.
        downloads_dir: Directory containing the downloaded
            installer. Default: Path("downloads")
        output_dir: Base directory for build output.
            Default: From config or Path("builds")
        verbose: Show verbose progress output. Default is False.
        debug: Show debug output. Default is False.

    Returns:
        A dict (app_id, app_name, version, build_dir, psadt_version, status),
            where app_id is the application ID, app_name is the application
            name, version is the application version, build_dir is the Path
            to the build directory, psadt_version is the PSADT version used,
            and status is the build status.

    Raises:
        FileNotFoundError: If recipe or installer doesn't exist.
        RuntimeError: If build process fails.

    Example:
        Basic build:

            result = build_package(Path("recipes/Google/chrome.yaml"))
            print(result['build_dir'])  # builds/napt-chrome/141.0.7390.123

        Custom output directory:

            result = build_package(
                Path("recipes/Google/chrome.yaml"),
                output_dir=Path("custom/builds")
            )

    Note:
        Requires installer to be downloaded first (run 'napt discover').
        Version extracted from installer file, not state cache. Overwrites
        existing build directory if it exists. PSADT files are copied pristine
        from cache. Invoke-AppDeployToolkit.ps1 is generated (not copied).
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    # Load configuration
    logger.step(1, 6, "Loading configuration...")
    config = load_effective_config(recipe_path, verbose=verbose, debug=debug)

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
    installer_file = _find_installer_file(downloads_dir, config)

    # Extract version from installer or state (filesystem + state are truth)
    logger.step(3, 6, "Extracting version from installer...")
    state_file = Path("state/versions.json")  # Default state file location
    version = _get_installer_version(installer_file, config, state_file)

    logger.verbose("BUILD", f"Building {app_name} v{version}")

    # Get PSADT release
    logger.step(4, 6, "Getting PSADT release...")
    psadt_config = config.get("defaults", {}).get("psadt", {})
    release_spec = psadt_config.get("release", "latest")
    cache_dir = Path(psadt_config.get("cache_dir", "cache/psadt"))

    psadt_cache_dir = get_psadt_release(
        release_spec, cache_dir, verbose=verbose, debug=debug
    )
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
        template_path, config, version, psadt_version, verbose=verbose, debug=debug
    )

    # Write generated script
    script_dest = build_dir / "Invoke-AppDeployToolkit.ps1"
    script_dest.write_text(invoke_script, encoding="utf-8")
    logger.verbose("BUILD", "[OK] Generated Invoke-AppDeployToolkit.ps1")

    # Copy installer
    _copy_installer(installer_file, build_dir)

    # Apply branding
    logger.step(6, 6, "Applying branding...")
    _apply_branding(config, build_dir)

    logger.verbose("BUILD", f"[OK] Build complete: {build_dir}")

    return {
        "app_id": app_id,
        "app_name": app_name,
        "version": version,
        "build_dir": build_dir,
        "psadt_version": psadt_version,
        "status": "success",
    }
