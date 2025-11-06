"""
Build manager for PSADT package creation.

This module orchestrates the complete build process for creating PSADT
packages from recipes and downloaded installers.

Functions
---------
build_package : function
    Main entry point for building PSADT packages.

Private Helpers
---------------
_get_installer_version : Extract version from downloaded installer
_find_installer_file : Locate installer in downloads directory
_create_build_directory : Create build directory structure
_copy_psadt_pristine : Copy PSADT files from cache
_copy_installer : Copy installer to Files/ directory
_apply_branding : Replace PSADT assets with custom branding

Design Principles
-----------------
- Filesystem is source of truth for version information
- PSADT files remain pristine (copied, not modified)
- Invoke-AppDeployToolkit.ps1 is generated (not copied)
- Build directories are versioned: {app_id}/{version}/
- Branding applied by replacing files in PSAppDeployToolkit/Assets/

Example
-------
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


def _get_installer_version(installer_file: Path, config: dict[str, Any]) -> str:
    """
    Extract version from installer file.

    Uses the version extraction method specified in the recipe's
    source configuration.

    Parameters
    ----------
    installer_file : Path
        Path to the installer file.
    config : dict
        Recipe configuration.

    Returns
    -------
    str
        Extracted version string.

    Raises
    ------
    RuntimeError
        If version extraction fails.
    ValueError
        If version type is unsupported.
    """
    from notapkgtool.cli import print_verbose

    app = config["apps"][0]
    source = app.get("source", {})
    version_config = source.get("version", {})
    version_type = version_config.get("type", "")

    print_verbose("BUILD", f"Extracting version from: {installer_file.name}")
    print_verbose("BUILD", f"Version type: {version_type}")

    if version_type == "msi_product_version_from_file":
        try:
            discovered = version_from_msi_product_version(installer_file)
            print_verbose("BUILD", f"Extracted version: {discovered.version}")
            return discovered.version
        except Exception as err:
            raise RuntimeError(
                f"Failed to extract MSI version from {installer_file}: {err}"
            ) from err
    else:
        raise ValueError(
            f"Unsupported version type for build: {version_type!r}. "
            f"Supported: msi_product_version_from_file"
        )


def _find_installer_file(downloads_dir: Path, config: dict[str, Any]) -> Path:
    """
    Find the installer file in the downloads directory.

    Uses the URL from the recipe to determine the expected filename.

    Parameters
    ----------
    downloads_dir : Path
        Downloads directory to search.
    config : dict
        Recipe configuration.

    Returns
    -------
    Path
        Path to the installer file.

    Raises
    ------
    FileNotFoundError
        If installer file cannot be found.
    """
    from notapkgtool.cli import print_verbose

    app = config["apps"][0]
    source = app.get("source", {})
    url = source.get("url", "")

    # Extract filename from URL
    if url:
        filename = url.split("/")[-1]
        installer_path = downloads_dir / filename

        if installer_path.exists():
            print_verbose("BUILD", f"Found installer: {installer_path}")
            return installer_path

    # Fallback: Search for common installer patterns
    for pattern in ["*.msi", "*.exe"]:
        matches = list(downloads_dir.glob(pattern))
        if matches:
            # Use the most recently modified file
            installer_path = max(matches, key=lambda p: p.stat().st_mtime)
            print_verbose(
                "BUILD", f"Found installer by pattern {pattern}: {installer_path}"
            )
            return installer_path

    raise FileNotFoundError(
        f"No installer found in {downloads_dir}. "
        f"Run 'napt discover' first to download the installer."
    )


def _create_build_directory(base_dir: Path, app_id: str, version: str) -> Path:
    """
    Create the build directory structure.

    Parameters
    ----------
    base_dir : Path
        Base builds directory.
    app_id : str
        Application ID.
    version : str
        Application version.

    Returns
    -------
    Path
        Path to the created build directory.

    Raises
    ------
    OSError
        If directory creation fails.
    """
    from notapkgtool.cli import print_verbose

    build_dir = base_dir / app_id / version

    if build_dir.exists():
        print_verbose("BUILD", f"Build directory exists: {build_dir}")
        print_verbose("BUILD", "Removing existing build...")
        shutil.rmtree(build_dir)

    # Create directory structure
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "Files").mkdir(exist_ok=True)
    (build_dir / "SupportFiles").mkdir(exist_ok=True)

    print_verbose("BUILD", f"Created build directory: {build_dir}")

    return build_dir


def _copy_psadt_pristine(psadt_cache_dir: Path, build_dir: Path) -> None:
    """
    Copy PSADT files from cache to build directory (pristine, unmodified).

    Parameters
    ----------
    psadt_cache_dir : Path
        Path to cached PSADT version directory.
    build_dir : Path
        Build directory where PSADT should be copied.

    Raises
    ------
    FileNotFoundError
        If PSADT cache directory or required files don't exist.
    OSError
        If copy operation fails.
    """
    from notapkgtool.cli import print_verbose

    psadt_source = psadt_cache_dir / "PSAppDeployToolkit"

    if not psadt_source.exists():
        raise FileNotFoundError(f"PSADT directory not found in cache: {psadt_source}")

    psadt_dest = build_dir / "PSAppDeployToolkit"

    print_verbose("BUILD", f"Copying PSADT from cache: {psadt_source}")

    # Copy entire PSAppDeployToolkit directory
    shutil.copytree(psadt_source, psadt_dest)

    # Also copy the Invoke-AppDeployToolkit.exe launcher
    exe_source = psadt_cache_dir / "Invoke-AppDeployToolkit.exe"
    if exe_source.exists():
        exe_dest = build_dir / "Invoke-AppDeployToolkit.exe"
        shutil.copy2(exe_source, exe_dest)
        print_verbose("BUILD", "Copied Invoke-AppDeployToolkit.exe")

    print_verbose("BUILD", "✓ PSADT files copied")


def _copy_installer(installer_file: Path, build_dir: Path) -> None:
    """
    Copy installer to the build's Files/ directory.

    Parameters
    ----------
    installer_file : Path
        Path to the installer file.
    build_dir : Path
        Build directory.

    Raises
    ------
    OSError
        If copy operation fails.
    """
    from notapkgtool.cli import print_verbose

    files_dir = build_dir / "Files"
    dest = files_dir / installer_file.name

    print_verbose("BUILD", f"Copying installer: {installer_file.name}")

    shutil.copy2(installer_file, dest)

    print_verbose("BUILD", "✓ Installer copied to Files/")


def _apply_branding(config: dict[str, Any], build_dir: Path) -> None:
    """
    Apply custom branding by replacing PSADT assets.

    Reads the brand_pack configuration and replaces PSADT's default
    assets (logo, banner) with custom ones.

    Parameters
    ----------
    config : dict
        Merged configuration with brand_pack settings.
    build_dir : Path
        Build directory containing PSAppDeployToolkit/.

    Raises
    ------
    FileNotFoundError
        If branding files don't exist.
    OSError
        If file copy operation fails.
    """
    from notapkgtool.cli import print_verbose

    brand_pack = config.get("defaults", {}).get("psadt", {}).get("brand_pack")

    if not brand_pack:
        print_verbose("BUILD", "No brand pack configured, using PSADT defaults")
        return

    brand_path = Path(brand_pack.get("path", ""))
    mappings = brand_pack.get("mappings", [])

    if not brand_path.exists():
        print_verbose(
            "BUILD", f"Brand pack path not found: {brand_path}, skipping branding"
        )
        return

    print_verbose("BUILD", f"Applying branding from: {brand_path}")

    for mapping in mappings:
        source_pattern = mapping.get("source", "")
        target_path = mapping.get("target", "")

        if not source_pattern or not target_path:
            continue

        # Find source files matching pattern
        source_files = list(brand_path.glob(source_pattern))

        if not source_files:
            print_verbose("BUILD", f"No files match pattern: {source_pattern}")
            continue

        # Use first match
        source_file = source_files[0]

        # Build target path (preserve extension from source)
        target = build_dir / "PSAppDeployToolkit" / target_path
        target_with_ext = target.with_suffix(source_file.suffix)

        # Ensure parent directory exists
        target_with_ext.parent.mkdir(parents=True, exist_ok=True)

        # Copy file
        shutil.copy2(source_file, target_with_ext)
        print_verbose("BUILD", f"  {source_file.name} → {target_with_ext.name}")

    print_verbose("BUILD", "✓ Branding applied")


def build_package(
    recipe_path: Path,
    downloads_dir: Path | None = None,
    output_dir: Path | None = None,
    verbose: bool = False,
    debug: bool = False,
) -> dict[str, Any]:
    """
    Build a PSADT package from a recipe and downloaded installer.

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

    Parameters
    ----------
    recipe_path : Path
        Path to the recipe YAML file.
    downloads_dir : Path, optional
        Directory containing the downloaded installer.
        Default: Path("downloads")
    output_dir : Path, optional
        Base directory for build output.
        Default: From config or Path("builds")
    verbose : bool, optional
        Show verbose progress output.
    debug : bool, optional
        Show debug output.

    Returns
    -------
    dict
        Build results containing:
        - app_id : str
        - app_name : str
        - version : str
        - build_dir : Path
        - psadt_version : str
        - status : str

    Raises
    ------
    FileNotFoundError
        If recipe or installer doesn't exist.
    RuntimeError
        If build process fails.

    Examples
    --------
    Basic build:

        >>> result = build_package(Path("recipes/Google/chrome.yaml"))
        >>> print(result['build_dir'])
        builds/napt-chrome/141.0.7390.123

    Custom output directory:

        >>> result = build_package(
        ...     Path("recipes/Google/chrome.yaml"),
        ...     output_dir=Path("custom/builds")
        ... )

    Notes
    -----
    - Requires installer to be downloaded first (run 'napt discover')
    - Version extracted from installer file, not state cache
    - Overwrites existing build directory if it exists
    - PSADT files are copied pristine from cache
    - Invoke-AppDeployToolkit.ps1 is generated (not copied)
    """
    from notapkgtool.cli import print_step, print_verbose

    # Load configuration
    print_step(1, 6, "Loading configuration...")
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
    print_step(2, 6, "Finding installer...")
    installer_file = _find_installer_file(downloads_dir, config)

    # Extract version from installer (filesystem is source of truth)
    print_step(3, 6, "Extracting version from installer...")
    version = _get_installer_version(installer_file, config)

    print_verbose("BUILD", f"Building {app_name} v{version}")

    # Get PSADT release
    print_step(4, 6, "Getting PSADT release...")
    psadt_config = config.get("defaults", {}).get("psadt", {})
    release_spec = psadt_config.get("release", "latest")
    cache_dir = Path(psadt_config.get("cache_dir", "cache/psadt"))

    psadt_cache_dir = get_psadt_release(
        release_spec, cache_dir, verbose=verbose, debug=debug
    )
    psadt_version = psadt_cache_dir.name  # Directory name is the version

    print_verbose("BUILD", f"Using PSADT {psadt_version}")

    # Create build directory
    print_step(5, 6, "Creating build structure...")
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
    print_verbose("BUILD", "✓ Generated Invoke-AppDeployToolkit.ps1")

    # Copy installer
    _copy_installer(installer_file, build_dir)

    # Apply branding
    print_step(6, 6, "Applying branding...")
    _apply_branding(config, build_dir)

    print_verbose("BUILD", f"✓ Build complete: {build_dir}")

    return {
        "app_id": app_id,
        "app_name": app_name,
        "version": version,
        "build_dir": build_dir,
        "psadt_version": psadt_version,
        "status": "success",
    }
