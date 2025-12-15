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
        from notapkgtool.build.packager import create_intunewin

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

from notapkgtool.exceptions import ConfigError, NetworkError, PackagingError
from notapkgtool.results import PackageResult

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


def _get_intunewin_tool(cache_dir: Path, verbose: bool = False) -> Path:
    """Download and cache IntuneWinAppUtil.exe.

    Args:
        cache_dir: Directory to cache the tool.
        verbose: Show verbose output. Default is False.

    Returns:
        Path to the IntuneWinAppUtil.exe tool.

    Raises:
        NetworkError: If download fails.
    """
    from notapkgtool.logging import get_global_logger

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
    verbose: bool = False,
) -> Path:
    """Execute IntuneWinAppUtil.exe to create .intunewin package.

    Args:
        tool_path: Path to IntuneWinAppUtil.exe.
        source_dir: Source directory (build directory).
        setup_file: Name of the setup file (e.g., "Invoke-AppDeployToolkit.exe").
        output_dir: Output directory for .intunewin file.
        verbose: Show verbose output. Default is False.

    Returns:
        Path to the created .intunewin file.

    Raises:
        PackagingError: If packaging fails.
    """
    from notapkgtool.logging import get_global_logger

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

        if verbose and result.stdout:
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
    verbose: bool = False,
    debug: bool = False,
) -> PackageResult:
    """Create a .intunewin package from a PSADT build directory.

    Uses Microsoft's IntuneWinAppUtil.exe tool to package a PSADT build
    directory into a .intunewin file suitable for Intune deployment.

    Args:
        build_dir: Path to the built PSADT package directory.
        output_dir: Directory for the .intunewin output.
            Default: packages/{app_id}/
        clean_source: If True, remove the build directory
            after packaging. Default is False.
        verbose: Show verbose output. Default is False.
        debug: Show debug output. Default is False.

    Returns:
        PackageResult dataclass with the following fields:

            - build_dir (Path): Path to the PSADT build directory that was packaged.
                This directory may have been removed if clean_source=True.
            - package_path (Path): Path to the created .intunewin file, located at
                {output_dir}/{app_id}/Invoke-AppDeployToolkit.intunewin (named by IntuneWinAppUtil.exe).
            - app_id (str): Unique application identifier extracted from build directory
                structure.
            - version (str): Application version extracted from build directory structure.
            - status (str): Packaging status, typically "success" for completed packaging.

    Raises:
        ConfigError: If build directory structure is invalid.
        PackagingError: If packaging fails.
        NetworkError: If IntuneWinAppUtil.exe download fails.

    Example:
        Basic packaging:
            ```python
            result = create_intunewin(
                build_dir=Path("builds/napt-chrome/141.0.7390.123")
            )
            print(result.package_path)
            # packages/napt-chrome/Invoke-AppDeployToolkit.intunewin
            ```

        With cleanup:
            ```python
            result = create_intunewin(
                build_dir=Path("builds/napt-chrome/141.0.7390.123"),
                clean_source=True
            )
            # Build directory is removed after packaging
            ```

    Note:
        Requires build directory from 'napt build' command. IntuneWinAppUtil.exe
        is downloaded and cached on first use. Setup file is always
        "Invoke-AppDeployToolkit.exe". Output file is named by IntuneWinAppUtil.exe:
        packages/{app_id}/Invoke-AppDeployToolkit.intunewin
    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()

    build_dir = build_dir.resolve()

    if not build_dir.exists():
        raise PackagingError(f"Build directory not found: {build_dir}")

    # Extract app_id and version from directory structure
    # Structure: {base_dir}/{app_id}/{version}/packagefiles/
    # build_dir is packagefiles/, so:
    # - version = build_dir.parent.name
    # - app_id = build_dir.parent.parent.name
    version = build_dir.parent.name
    app_id = build_dir.parent.parent.name

    logger.verbose("PACKAGE", f"Packaging {app_id} v{version}")

    # Verify build structure
    logger.step(1, 4, "Verifying build structure...")
    _verify_build_structure(build_dir)

    # Determine output directory
    if output_dir is None:
        output_dir = Path("packages") / app_id

    output_dir = output_dir.resolve()

    # Get IntuneWinAppUtil tool
    logger.step(2, 4, "Getting IntuneWinAppUtil tool...")
    tool_cache = Path("cache/tools")
    tool_path = _get_intunewin_tool(tool_cache, verbose=verbose)

    # Create .intunewin package
    logger.step(3, 4, "Creating .intunewin package...")
    package_path = _execute_packaging(
        tool_path,
        build_dir,
        "Invoke-AppDeployToolkit.exe",
        output_dir,
        verbose=verbose,
    )

    # Optionally clean source
    if clean_source:
        logger.step(4, 4, "Cleaning source build directory...")
        shutil.rmtree(build_dir)
        logger.verbose("PACKAGE", f"[OK] Removed build directory: {build_dir}")
    else:
        logger.step(4, 4, "Package complete")

    logger.verbose("PACKAGE", f"[OK] Package created: {package_path}")

    return PackageResult(
        build_dir=build_dir,
        package_path=package_path,
        app_id=app_id,
        version=version,
        status="success",
    )
