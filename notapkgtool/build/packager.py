"""
.intunewin package generation for NAPT.

This module handles creating .intunewin packages from built PSADT directories
using Microsoft's IntuneWinAppUtil.exe tool.

Functions
---------
create_intunewin : function
    Create a .intunewin package from a PSADT build directory.

Private Helpers
---------------
_get_intunewin_tool : Download and cache IntuneWinAppUtil.exe
_execute_packaging : Run IntuneWinAppUtil.exe to create .intunewin
_verify_build_structure : Validate PSADT build directory

Design Principles
-----------------
- IntuneWinAppUtil.exe is cached globally (not per-build)
- Package output follows convention: {app_id}-{version}.intunewin
- Build directory can optionally be cleaned after packaging
- Tool is downloaded from Microsoft's official GitHub repository

Example
-------
    from pathlib import Path
    from notapkgtool.build.packager import create_intunewin
    
    result = create_intunewin(
        build_dir=Path("builds/napt-chrome/141.0.7390.123"),
        output_dir=Path("packages")
    )
    
    print(f"Package: {result['package_path']}")
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Any

import requests

INTUNEWIN_TOOL_URL = (
    "https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool"
    "/raw/master/IntuneWinAppUtil.exe"
)


def _verify_build_structure(build_dir: Path) -> None:
    """
    Verify that the build directory has a valid PSADT structure.
    
    Parameters
    ----------
    build_dir : Path
        Build directory to verify.
    
    Raises
    ------
    ValueError
        If required files/directories are missing.
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
        raise ValueError(
            f"Invalid PSADT build directory: {build_dir}\n"
            f"Missing: {', '.join(missing)}"
        )


def _get_intunewin_tool(cache_dir: Path, verbose: bool = False) -> Path:
    """
    Download and cache IntuneWinAppUtil.exe.
    
    Parameters
    ----------
    cache_dir : Path
        Directory to cache the tool.
    verbose : bool, optional
        Show verbose output.
    
    Returns
    -------
    Path
        Path to the IntuneWinAppUtil.exe tool.
    
    Raises
    ------
    RuntimeError
        If download fails.
    """
    from notapkgtool.cli import print_verbose
    
    tool_path = cache_dir / "IntuneWinAppUtil.exe"
    
    if tool_path.exists():
        print_verbose("PACKAGE", f"Using cached IntuneWinAppUtil: {tool_path}")
        return tool_path
    
    print_verbose("PACKAGE", "Downloading IntuneWinAppUtil.exe...")
    
    # Download the tool
    try:
        response = requests.get(INTUNEWIN_TOOL_URL, timeout=60)
        response.raise_for_status()
    except requests.RequestException as err:
        raise RuntimeError(
            f"Failed to download IntuneWinAppUtil.exe: {err}"
        ) from err
    
    # Save to cache
    cache_dir.mkdir(parents=True, exist_ok=True)
    tool_path.write_bytes(response.content)
    
    print_verbose("PACKAGE", f"✓ IntuneWinAppUtil.exe cached: {tool_path}")
    
    return tool_path


def _execute_packaging(
    tool_path: Path,
    source_dir: Path,
    setup_file: str,
    output_dir: Path,
    verbose: bool = False,
) -> Path:
    """
    Execute IntuneWinAppUtil.exe to create .intunewin package.
    
    Parameters
    ----------
    tool_path : Path
        Path to IntuneWinAppUtil.exe.
    source_dir : Path
        Source directory (build directory).
    setup_file : str
        Name of the setup file (e.g., "Invoke-AppDeployToolkit.exe").
    output_dir : Path
        Output directory for .intunewin file.
    verbose : bool, optional
        Show verbose output.
    
    Returns
    -------
    Path
        Path to the created .intunewin file.
    
    Raises
    ------
    RuntimeError
        If packaging fails.
    """
    from notapkgtool.cli import print_verbose
    
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
    
    print_verbose("PACKAGE", f"Running: {' '.join(cmd)}")
    
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
                print_verbose("PACKAGE", f"  {line}")
    
    except subprocess.CalledProcessError as err:
        error_msg = f"IntuneWinAppUtil.exe failed (exit code {err.returncode})"
        if err.stderr:
            error_msg += f"\n{err.stderr}"
        raise RuntimeError(error_msg) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(
            f"IntuneWinAppUtil.exe timed out after {err.timeout}s"
        ) from err
    
    # Find the generated .intunewin file
    intunewin_files = list(output_dir.glob("*.intunewin"))
    
    if not intunewin_files:
        raise RuntimeError(
            f"IntuneWinAppUtil.exe completed but no .intunewin file found in {output_dir}"
        )
    
    # Return the most recently created file
    intunewin_path = max(intunewin_files, key=lambda p: p.stat().st_mtime)
    print_verbose("PACKAGE", f"✓ Created: {intunewin_path.name}")
    
    return intunewin_path


def create_intunewin(
    build_dir: Path,
    output_dir: Path | None = None,
    clean_source: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> dict[str, Any]:
    """
    Create a .intunewin package from a PSADT build directory.
    
    Uses Microsoft's IntuneWinAppUtil.exe tool to package a PSADT build
    directory into a .intunewin file suitable for Intune deployment.
    
    Parameters
    ----------
    build_dir : Path
        Path to the built PSADT package directory.
    output_dir : Path, optional
        Directory for the .intunewin output.
        Default: packages/{app_id}/
    clean_source : bool, optional
        If True, remove the build directory after packaging.
        Default: False.
    verbose : bool, optional
        Show verbose output.
    debug : bool, optional
        Show debug output.
    
    Returns
    -------
    dict
        Packaging results containing:
        - build_dir : Path
        - package_path : Path
        - app_id : str (from directory structure)
        - version : str (from directory structure)
        - status : str
    
    Raises
    ------
    ValueError
        If build directory structure is invalid.
    RuntimeError
        If packaging fails.
    
    Examples
    --------
    Basic packaging:
    
        >>> result = create_intunewin(
        ...     build_dir=Path("builds/napt-chrome/141.0.7390.123")
        ... )
        >>> print(result['package_path'])
        packages/napt-chrome/napt-chrome-141.0.7390.123.intunewin
    
    With cleanup:
    
        >>> result = create_intunewin(
        ...     build_dir=Path("builds/napt-chrome/141.0.7390.123"),
        ...     clean_source=True
        ... )
        # Build directory is removed after packaging
    
    Notes
    -----
    - Requires build directory from 'napt build' command
    - IntuneWinAppUtil.exe is downloaded and cached on first use
    - Setup file is always "Invoke-AppDeployToolkit.exe"
    - Output follows convention: packages/{app_id}/{app_id}-{version}.intunewin
    """
    from notapkgtool.cli import print_step, print_verbose
    
    build_dir = build_dir.resolve()
    
    if not build_dir.exists():
        raise FileNotFoundError(f"Build directory not found: {build_dir}")
    
    # Extract app_id and version from directory structure (app_id/version/)
    version = build_dir.name
    app_id = build_dir.parent.name
    
    print_verbose("PACKAGE", f"Packaging {app_id} v{version}")
    
    # Verify build structure
    print_step(1, 4, "Verifying build structure...")
    _verify_build_structure(build_dir)
    
    # Determine output directory
    if output_dir is None:
        output_dir = Path("packages") / app_id
    
    output_dir = output_dir.resolve()
    
    # Get IntuneWinAppUtil tool
    print_step(2, 4, "Getting IntuneWinAppUtil tool...")
    tool_cache = Path("cache/tools")
    tool_path = _get_intunewin_tool(tool_cache, verbose=verbose)
    
    # Create .intunewin package
    print_step(3, 4, "Creating .intunewin package...")
    package_path = _execute_packaging(
        tool_path,
        build_dir,
        "Invoke-AppDeployToolkit.exe",
        output_dir,
        verbose=verbose,
    )
    
    # Optionally clean source
    if clean_source:
        print_step(4, 4, "Cleaning source build directory...")
        shutil.rmtree(build_dir)
        print_verbose("PACKAGE", f"✓ Removed build directory: {build_dir}")
    else:
        print_step(4, 4, "Package complete")
    
    print_verbose("PACKAGE", f"✓ Package created: {package_path}")
    
    return {
        "build_dir": build_dir,
        "package_path": package_path,
        "app_id": app_id,
        "version": version,
        "status": "success",
    }

