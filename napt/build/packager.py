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
    - Tool is downloaded from Microsoft's official GitHub repository

Verification:
    The build manifest is the link between steps. Before packaging, the
    installer inside the build is re-hashed against the manifest's
    ``installer_sha256``, and that hash is checked against the release
    deployment state records when the caller supplies it. After packaging,
    the manifest copied into the package folder gains the .intunewin's
    filename and hash, which ``napt upload`` re-checks before sending.
    Two runs of IntuneWinAppUtil never produce the same bytes (it generates
    a fresh encryption key each time), so the .intunewin hash only ever
    ties one package to one upload.

Filing:
    The package folder for the version being packaged is cleared and
    rebuilt, so it holds exactly what this run produced. Other versions'
    package folders are never touched.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import requests

from napt.download.download import make_session, sha256_file
from napt.exceptions import ConfigError, NetworkError, PackagingError
from napt.files import write_text_atomic
from napt.paths import is_safe_path_component
from napt.results import PackageResult

INTUNEWIN_REPO = "microsoft/Microsoft-Win32-Content-Prep-Tool"
INTUNEWIN_GITHUB_API = f"https://api.github.com/repos/{INTUNEWIN_REPO}/releases/latest"
INTUNEWIN_DOWNLOAD_URL = (
    f"https://github.com/{INTUNEWIN_REPO}/raw/{{tag}}/IntuneWinAppUtil.exe"
)


def fetch_latest_intunewin_version() -> str:
    """Fetch the latest IntuneWinAppUtil.exe release version from GitHub.

    Queries the GitHub API for the latest release and extracts the version
    number from the tag name (e.g., "1.8.6" from tag "v1.8.6").

    Returns:
        Version number without "v" prefix (e.g., "1.8.6").

    Raises:
        NetworkError: If the GitHub API request fails or the version cannot
            be extracted from the response.

    Example:
        Get latest IntuneWinAppUtil version from GitHub:
            ```python
            version = fetch_latest_intunewin_version()
            print(version)  # Output: "1.8.6"
            ```

    Note:
        Uses GitHub's public API (60 requests/hour limit without auth).
        Set GITHUB_TOKEN environment variable for higher rate limits.
    """
    import os

    from napt.logging import get_global_logger

    logger = get_global_logger()
    logger.verbose("PACKAGE", f"Querying GitHub API: {INTUNEWIN_GITHUB_API}")

    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with make_session() as session:
            response = session.get(INTUNEWIN_GITHUB_API, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as err:
        raise NetworkError(
            f"Failed to fetch latest IntuneWinAppUtil version: {err}"
        ) from err

    # The whole tag must be the version: a suffix such as "-rc1" would
    # otherwise be dropped and the download by tag would miss.
    tag = data.get("tag_name", "")
    match = re.fullmatch(r"v?(\d+(?:\.\d+)+)", tag)
    if not match:
        raise NetworkError(
            f"Could not extract version from IntuneWinAppUtil release tag: {tag!r}"
        )

    version = match.group(1)
    logger.verbose("PACKAGE", f"Latest IntuneWinAppUtil release: {version}")
    return version


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


def _get_intunewin_tool(cache_dir: Path, release: str) -> Path:
    """Download and cache IntuneWinAppUtil.exe for a specific release.

    Resolves "latest" to the current release via the GitHub API, then
    downloads and caches the tool under a versioned subdirectory.

    Args:
        cache_dir: Base directory for caching tool releases.
        release: Release specifier, either "latest" or a specific version
            (e.g., "1.8.6" or "v1.8.6").

    Returns:
        Path to the cached IntuneWinAppUtil.exe.

    Raises:
        ConfigError: If release is not "latest" or a plain version.
        NetworkError: If the GitHub API query or download fails.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    if release == "latest":
        logger.verbose("PACKAGE", "Resolving 'latest' IntuneWinAppUtil release...")
        version = fetch_latest_intunewin_version()
    else:
        version = release.lstrip("v")

    # The version names the cache folder, so it must be a plain folder name.
    if not is_safe_path_component(version):
        raise ConfigError(
            f"Invalid intunewin.release {release!a}: use 'latest' or a version "
            "such as '1.8.6'"
        )

    tool_path = cache_dir / version / "IntuneWinAppUtil.exe"

    if tool_path.exists():
        logger.info("PACKAGE", f"Using cached IntuneWinAppUtil.exe {version}")
        return tool_path

    logger.info("PACKAGE", f"Downloading IntuneWinAppUtil.exe {version}...")

    # The repo uses inconsistent tag formats (e.g. "v1.8.6" and "1.8.3"),
    # so try both and use whichever resolves.
    response = None
    with make_session() as session:
        for tag in [f"v{version}", version]:
            url = INTUNEWIN_DOWNLOAD_URL.format(tag=tag)
            try:
                r = session.get(url, timeout=60)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                response = r
                break
            except requests.RequestException as err:
                raise NetworkError(
                    f"Failed to download IntuneWinAppUtil.exe {version}: {err}"
                ) from err

    if response is None:
        raise NetworkError(
            f"IntuneWinAppUtil.exe {version} not found "
            f"(tried tags v{version} and {version})"
        )

    tool_path.parent.mkdir(parents=True, exist_ok=True)
    tool_path.write_bytes(response.content)

    logger.info("PACKAGE", f"IntuneWinAppUtil.exe {version} cached successfully")

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

    # The output folder was empty, so the tool's package is the only one.
    intunewin_files = list(output_dir.glob("*.intunewin"))

    if not intunewin_files:
        raise PackagingError(
            "IntuneWinAppUtil.exe completed but no .intunewin file found in "
            f"{output_dir}"
        )
    if len(intunewin_files) > 1:
        names = ", ".join(sorted(p.name for p in intunewin_files))
        raise PackagingError(
            f"Expected exactly one .intunewin file in {output_dir} after "
            f"packaging, found: {names}"
        )

    intunewin_path = intunewin_files[0]
    logger.verbose("PACKAGE", f"[OK] Created: {intunewin_path.name}")

    return intunewin_path


def _read_build_manifest(build_dir: Path) -> dict[str, Any]:
    """Reads the manifest 'napt build' wrote beside the build.

    Args:
        build_dir: Build version directory (holds ``packagefiles/``).

    Returns:
        The parsed manifest.

    Raises:
        ConfigError: If the manifest is missing, not JSON, or lacks the
            installer hash or the detection script name.
    """
    manifest_path = build_dir / "build-manifest.json"
    if not manifest_path.is_file():
        raise ConfigError(
            f"Build manifest not found: {manifest_path}. Run 'napt build' to "
            "create the build again."
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ConfigError(
            f"Cannot read build-manifest.json in {build_dir}: {err}. Run "
            "'napt build' to create the build again."
        ) from err
    if not isinstance(manifest, dict):
        raise ConfigError(
            f"build-manifest.json in {build_dir} is not a JSON object. Run "
            "'napt build' to create the build again."
        )
    for key in ("installer_sha256", "detection_script_path"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ConfigError(
                f"build-manifest.json in {build_dir} has no {key}. Run "
                "'napt build' to create the build again."
            )
    return manifest


def _verify_installer(packagefiles_dir: Path, installer_sha256: str) -> None:
    """Checks that the installer inside the build is the one the manifest names.

    Args:
        packagefiles_dir: The build's ``packagefiles/`` directory.
        installer_sha256: Hash recorded by ``napt build``.

    Raises:
        PackagingError: If no file under ``Files/`` has that hash.
    """
    files_dir = packagefiles_dir / "Files"
    for candidate in sorted(p for p in files_dir.iterdir() if p.is_file()):
        if sha256_file(candidate) == installer_sha256:
            return
    raise PackagingError(
        f"No file in {files_dir} matches the installer hash the build manifest "
        f"records ({installer_sha256}); the build does not match its "
        "manifest. Run 'napt build' to create the build again."
    )


def _copy_named_script(build_dir: Path, name: str, destination: Path) -> None:
    """Copies a script the manifest names into the package folder.

    Args:
        build_dir: Build version directory holding the script.
        name: The script's filename from the manifest.
        destination: The package folder.

    Raises:
        PackagingError: If the named script is not in the build.
    """
    from napt.logging import get_global_logger

    source = build_dir / name
    if not source.is_file():
        raise PackagingError(
            f"The build manifest names {name}, which is not in {build_dir}. "
            "Run 'napt build' to create the build again."
        )
    shutil.copy2(source, destination / name)
    get_global_logger().verbose("PACKAGE", f"Copied: {name}")


def create_intunewin(
    build_dir: Path,
    output_dir: Path | None = None,
    tool_release: str = "latest",
    expected_sha256: str | None = None,
) -> PackageResult:
    """Create a .intunewin package from a PSADT build version directory.

    Uses Microsoft's IntuneWinAppUtil.exe tool to package the PSADT build
    into a .intunewin file for Intune deployment.

    The output directory is versioned: packages/{app_id}/{version}/. That
    folder is cleared and rebuilt so it holds exactly what this run
    produced; other versions' package folders are never touched.
    Detection and requirements scripts are copied into the output directory
    so that 'napt upload' is self-contained and does not need the builds
    directory.

    Args:
        build_dir: Path to the version directory produced by 'napt build'
            (e.g., builds/napt-chrome/144.0.7559.110/). Must contain a
            packagefiles/ subdirectory with a valid PSADT structure.
        output_dir: Parent directory for package output.
            Default: packages/ (configurable via directories.package in
            org.yaml).
        tool_release: IntuneWinAppUtil.exe release to use, "latest" or a
            specific version (e.g., "1.8.6"). Default is "latest".
        expected_sha256: Hash of the release deployment state records, or
            None when no release is recorded. The build's installer must
            match it.

    Returns:
        Package metadata including .intunewin path, app ID, and version.

    Raises:
        ConfigError: If the build directory structure is invalid, or its
            manifest is missing or unusable.
        PackagingError: If the build's installer does not match its
            manifest or the recorded release, a script the manifest names
            is missing, packaging fails, or build_dir is missing.
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

    # Verify PSADT structure inside packagefiles/ and the build against
    # its manifest and the recorded release, before anything is written.
    logger.step(1, 5, "Verifying build...")
    _verify_build_structure(packagefiles_dir)
    manifest = _read_build_manifest(build_dir)
    installer_sha256: str = manifest["installer_sha256"]
    if expected_sha256 is not None and installer_sha256 != expected_sha256:
        raise PackagingError(
            f"The build in {build_dir} was made from a different installer "
            f"(sha256 {installer_sha256}) than the recorded release "
            f"(sha256 {expected_sha256}). Run 'napt build' so the build "
            "matches the recorded release."
        )
    _verify_installer(packagefiles_dir, installer_sha256)
    logger.verbose("PACKAGE", f"Installer sha256 {installer_sha256} verified")

    # Get IntuneWinAppUtil tool
    logger.step(2, 5, "Getting IntuneWinAppUtil tool...")
    tool_cache = Path("cache/tools")
    tool_path = _get_intunewin_tool(tool_cache, tool_release)

    # Versioned output directory: packages/{app_id}/{version}/. This run
    # replaces it wholesale; other versions' folders are never touched.
    packages_root = output_dir.resolve() if output_dir else Path("packages").resolve()
    version_output_dir = packages_root / app_id / version
    if version_output_dir.exists():
        logger.info("PACKAGE", f"Replacing the earlier package of {version}")
        shutil.rmtree(version_output_dir)
    version_output_dir.mkdir(parents=True)

    # Create .intunewin package
    logger.step(3, 5, "Creating .intunewin package...")
    package_path = _execute_packaging(
        tool_path,
        packagefiles_dir,
        "Invoke-AppDeployToolkit.exe",
        version_output_dir,
    )

    # Copy the scripts the manifest names into the package folder so napt
    # upload is self-contained, then write the manifest with the package
    # named in it, for upload to verify what it sends.
    logger.step(4, 5, "Copying detection scripts...")
    _copy_named_script(build_dir, manifest["detection_script_path"], version_output_dir)
    requirements_name = manifest.get("requirements_script_path")
    if isinstance(requirements_name, str) and requirements_name:
        _copy_named_script(build_dir, requirements_name, version_output_dir)
    manifest["intunewin_filename"] = package_path.name
    manifest["intunewin_sha256"] = sha256_file(package_path)
    write_text_atomic(
        version_output_dir / "build-manifest.json",
        json.dumps(manifest, indent=2) + "\n",
    )
    logger.verbose("PACKAGE", "Wrote: build-manifest.json")

    logger.step(5, 5, "Package complete")
    logger.verbose("PACKAGE", f"[OK] Package created: {package_path}")

    return PackageResult(
        build_dir=build_dir,
        package_path=package_path,
        app_id=app_id,
        version=version,
        status="success",
    )
