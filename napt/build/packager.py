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

""".intunewin package generation for NAPT.

This module handles creating .intunewin packages from built PSADT directories
using Microsoft's IntuneWinAppUtil.exe tool.

Design Principles:
    - IntuneWinAppUtil.exe is cached globally (not per-build)
    - Package output is named by IntuneWinAppUtil.exe: Invoke-AppDeployToolkit.intunewin
    - Build directory can optionally be cleaned after packaging
    - Tool is downloaded from Microsoft's official GitHub repository

Example:
    Basic usage:
        ```python
        from pathlib import Path
        from napt.build.packager import create_intunewin

        result = create_intunewin(
            build_dir=Path("builds/napt-chrome/141.0.7390.123"),
            output_dir=Path("packages")
        )

        print(f"Package: {result.package_path}")
        ```
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import requests

from napt.exceptions import ConfigError, NetworkError, PackagingError
from napt.results import PackageResult

# TODO: Add version tracking for IntuneWinAppUtil.exe
# Currently downloads from master branch (always latest), with no version tracking.
# Future enhancements:
#   - Track tool version in cache metadata
#   - Allow pinning to specific commit/release
#   - Auto-detect when tool updates are available
#   - Optional: Add config setting for tool version/source
INTUNEWIN_TOOL_URL = (
    "https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool"
    "/raw/master/IntuneWinAppUtil.exe"
)


def _verify_build_structure(build_dir: Path) -> None:
    """Verify that the build directory has a valid PSADT structure.

    Args:
        build_dir: Build directory to verify.

    Raises:
        ValueError: If required files/directories are missing.
    """
    required = [
        "PSAppDeployToolkit",
        "Files",
        "Invoke-AppDeployToolkit.ps1",
        "Invoke-AppDeployToolkit.exe",
    ]

    missing = []
    for item in required:
        if not (build_dir / item).exists():
            missing.append(item)

    if missing:
        raise ConfigError(
            f"Invalid PSADT build directory: {build_dir}\n"
            f"Missing: {', '.join(missing)}"
        )


def _get_intunewin_tool(cache_dir: Path) -> Path:
    """Download and cache IntuneWinAppUtil.exe.

    Args:
        cache_dir: Directory to cache the tool.

    Returns:
        Path to the IntuneWinAppUtil.exe tool.

    Raises:
        NetworkError: If download fails.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    tool_path = cache_dir / "IntuneWinAppUtil.exe"

    if tool_path.exists():
        logger.verbose("PACKAGE", f"Using cached IntuneWinAppUtil: {tool_path}")
        return tool_path

    logger.verbose("PACKAGE", "Downloading IntuneWinAppUtil.exe...")

    # Download the tool
    try:
        response = requests.get(INTUNEWIN_TOOL_URL, timeout=60)
        response.raise_for_status()
    except requests.RequestException as err:
        raise NetworkError(f"Failed to download IntuneWinAppUtil.exe: {err}") from err

    # Save to cache
    cache_dir.mkdir(parents=True, exist_ok=True)
    tool_path.write_bytes(response.content)

    logger.verbose("PACKAGE", f"[OK] IntuneWinAppUtil.exe cached: {tool_path}")

    return tool_path


def _execute_packaging(
    tool_path: Path,
    source_dir: Path,
    setup_file: str,
    output_dir: Path,
) -> Path:
    """Execute IntuneWinAppUtil.exe to create .intunewin package.

    Args:
        tool_path: Path to IntuneWinAppUtil.exe.
        source_dir: Source directory (build directory).
        setup_file: Name of the setup file (e.g., "Invoke-AppDeployToolkit.exe").
        output_dir: Output directory for .intunewin file.

    Returns:
        Path to the created .intunewin file.

    Raises:
        PackagingError: If packaging fails.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build command
    # IntuneWinAppUtil.exe -c <source> -s <setup file> -o <output> -q
    cmd = [
        str(tool_path),
        "-c",
        str(source_dir),
        "-s",
        setup_file,
        "-o",
        str(output_dir),
        "-q",  # Quiet mode
    ]

    logger.verbose("PACKAGE", f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                logger.verbose("PACKAGE", f"  {line}")

    except subprocess.CalledProcessError as err:
        error_msg = f"IntuneWinAppUtil.exe failed (exit code {err.returncode})"
        if err.stderr:
            error_msg += f"\n{err.stderr}"
        raise PackagingError(error_msg) from err
    except subprocess.TimeoutExpired as err:
        raise PackagingError(
            f"IntuneWinAppUtil.exe timed out after {err.timeout}s"
        ) from err

    # Find the generated .intunewin file
    intunewin_files = list(output_dir.glob("*.intunewin"))

    if not intunewin_files:
        raise PackagingError(
            f"IntuneWinAppUtil.exe completed but no .intunewin file found in {output_dir}"
        )

    # Return the most recently created file
    intunewin_path = max(intunewin_files, key=lambda p: p.stat().st_mtime)
    logger.verbose("PACKAGE", f"[OK] Created: {intunewin_path.name}")

    return intunewin_path


def create_intunewin(
    build_dir: Path,
    output_dir: Path | None = None,
    clean_source: bool = False,
) -> PackageResult:
    """Create a .intunewin package from a PSADT build version directory.

    Uses Microsoft's IntuneWinAppUtil.exe tool to package the PSADT build
    into a .intunewin file for Intune deployment.

    The output directory is versioned: packages/{app_id}/{version}/.
    Any previously packaged version for the same app is removed before the
    new one is created (single-slot: one package on disk per app at a time).
    Detection and requirements scripts are copied into the output directory
    so that 'napt upload' is self-contained and does not need the builds
    directory.

    Args:
        build_dir: Path to the version directory produced by 'napt build'
            (e.g., builds/napt-chrome/144.0.7559.110/). Must contain a
            packagefiles/ subdirectory with a valid PSADT structure.
        output_dir: Parent directory for package output.
            Default: packages/
        clean_source: If True, remove the build version directory
            after packaging. Default is False.

    Returns:
        Package metadata including .intunewin path, app ID, and version.

    Raises:
        ConfigError: If the build directory structure is invalid.
        PackagingError: If packaging fails or build_dir is missing.
        NetworkError: If IntuneWinAppUtil.exe download fails.

    Example:
        Basic packaging:
            ```python
            result = create_intunewin(
                build_dir=Path("builds/napt-chrome/144.0.7559.110")
            )
            print(result.package_path)
            # packages/napt-chrome/144.0.7559.110/Invoke-AppDeployToolkit.intunewin
            ```

        With cleanup:
            ```python
            result = create_intunewin(
                build_dir=Path("builds/napt-chrome/144.0.7559.110"),
                clean_source=True
            )
            # Build directory is removed after packaging
            ```

    Note:
        Requires build directory from 'napt build' command. IntuneWinAppUtil.exe
        is downloaded and cached on first use. Setup file is always
        "Invoke-AppDeployToolkit.exe". Output file is named by IntuneWinAppUtil.exe:
        packages/{app_id}/{version}/Invoke-AppDeployToolkit.intunewin
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    build_dir = build_dir.resolve()

    if not build_dir.exists():
        raise PackagingError(f"Build directory not found: {build_dir}")

    # build_dir is the version directory: builds/{app_id}/{version}/
    version = build_dir.name
    app_id = build_dir.parent.name
    packagefiles_dir = build_dir / "packagefiles"

    logger.verbose("PACKAGE", f"Packaging {app_id} v{version}")

    # Verify PSADT structure inside packagefiles/
    logger.step(1, 5, "Verifying build structure...")
    _verify_build_structure(packagefiles_dir)

    # Determine versioned output directory: packages/{app_id}/{version}/
    packages_root = output_dir.resolve() if output_dir else Path("packages").resolve()
    app_package_dir = packages_root / app_id
    version_output_dir = app_package_dir / version

    # Remove any previous version dirs for this app (single-slot)
    if app_package_dir.exists():
        for existing in [d for d in app_package_dir.iterdir() if d.is_dir()]:
            if existing != version_output_dir:
                logger.info("PACKAGE", f"Removing previous package: {existing.name}")
                shutil.rmtree(existing)

    version_output_dir.mkdir(parents=True, exist_ok=True)

    # Get IntuneWinAppUtil tool
    logger.step(2, 5, "Getting IntuneWinAppUtil tool...")
    tool_cache = Path("cache/tools")
    tool_path = _get_intunewin_tool(tool_cache)

    # Create .intunewin package
    logger.step(3, 5, "Creating .intunewin package...")
    package_path = _execute_packaging(
        tool_path,
        packagefiles_dir,
        "Invoke-AppDeployToolkit.exe",
        version_output_dir,
    )

    # Copy detection/requirements scripts and build manifest into the package
    # output directory so napt upload is self-contained and does not need
    # the builds directory.
    logger.step(4, 5, "Copying detection scripts...")
    for script in sorted(build_dir.glob("*-Detection.ps1")):
        shutil.copy2(script, version_output_dir / script.name)
        logger.verbose("PACKAGE", f"Copied: {script.name}")
    for script in sorted(build_dir.glob("*-Requirements.ps1")):
        shutil.copy2(script, version_output_dir / script.name)
        logger.verbose("PACKAGE", f"Copied: {script.name}")
    manifest_src = build_dir.parent / "build-manifest.json"
    if manifest_src.exists():
        shutil.copy2(manifest_src, version_output_dir / "build-manifest.json")
        logger.verbose("PACKAGE", "Copied: build-manifest.json")

    # Optionally clean source
    if clean_source:
        logger.step(5, 5, "Cleaning source build directory...")
        shutil.rmtree(build_dir)
        logger.verbose("PACKAGE", f"[OK] Removed build directory: {build_dir}")
    else:
        logger.step(5, 5, "Package complete")

    logger.verbose("PACKAGE", f"[OK] Package created: {package_path}")

    return PackageResult(
        build_dir=build_dir,
        package_path=package_path,
        app_id=app_id,
        version=version,
        status="success",
    )
