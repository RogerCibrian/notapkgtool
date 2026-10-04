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

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from napt.build.manifest import MANIFEST_NAME, read_build_manifest
from napt.download.download import make_session, sha256_file
from napt.exceptions import ConfigError, NetworkError, PackagingError
from napt.files import write_bytes_atomic, write_text_atomic
from napt.github import (
    download,
    env_token,
    latest_release,
    normalize_release_spec,
    release_tag,
    repo_file,
    verify_size,
    version_from_tag,
)
from napt.logging import get_global_logger
from napt.psadt.release import missing_template_entries

INTUNEWIN_REPO = "microsoft/Microsoft-Win32-Content-Prep-Tool"
# The tool's releases carry no assets; the executable lives in the
# repository, and the contents API reports its size, git blob hash, and
# download URL for a tag.
INTUNEWIN_TOOL_PATH = "IntuneWinAppUtil.exe"


def _git_blob_sha(content: bytes) -> str:
    """Computes the git blob SHA-1 the contents API reports for a file."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _verify_build_structure(build_dir: Path) -> None:
    """Verify that the build directory has the PSADT layout NAPT builds from.

    Args:
        build_dir: Build directory to verify.

    Raises:
        ConfigError: If required files or directories are missing.
    """
    missing = missing_template_entries(build_dir)
    if missing:
        raise ConfigError(
            f"Invalid PSADT build directory: {build_dir}\n"
            f"Missing: {', '.join(missing)}"
        )


def _get_intunewin_tool(cache_dir: Path, release: str) -> Path:
    """Download and cache IntuneWinAppUtil.exe for a specific release.

    Resolves "latest" to the current release via the GitHub API, then
    downloads and caches the tool under a versioned subdirectory. The
    executable is looked up through the contents API for the tag, which
    reports its size and git blob hash, and the download is checked against
    both before it is cached. That verifies the bytes are the file the
    repository holds at that tag, not that the tag is one you approved.

    Args:
        cache_dir: Base directory for caching tool releases.
        release: Release specifier, either "latest" or a specific version
            (e.g., "1.8.6" or "v1.8.6").

    Returns:
        Path to the cached IntuneWinAppUtil.exe.

    Raises:
        ConfigError: If release is not "latest" or a plain version.
        NetworkError: If the GitHub API query or download fails, the tag
            does not exist, or the download does not match what the
            repository reports.
        PackagingError: If the tool cannot be written to the cache.
    """
    logger = get_global_logger()
    token = env_token()

    with make_session() as session:
        if release == "latest":
            logger.verbose("PACKAGE", "Resolving 'latest' IntuneWinAppUtil release...")
            tag = release_tag(latest_release(session, INTUNEWIN_REPO, token=token))
            version = version_from_tag(tag)
            logger.verbose("PACKAGE", f"Latest IntuneWinAppUtil release: {version}")
            tags = [tag]
        else:
            version = normalize_release_spec(release, "intunewin.release", "1.8.6")
            # The repo uses inconsistent tag formats (e.g. "v1.8.6" and
            # "1.8.3"), so a pinned version is looked up under both.
            tags = [f"v{version}", version]

        tool_path = cache_dir / version / INTUNEWIN_TOOL_PATH
        if tool_path.exists():
            logger.info("PACKAGE", f"Using cached IntuneWinAppUtil.exe {version}")
            return tool_path

        logger.info("PACKAGE", f"Downloading IntuneWinAppUtil.exe {version}...")
        entry: dict[str, Any] | None = None
        for tag in tags:
            entry = repo_file(
                session, INTUNEWIN_REPO, INTUNEWIN_TOOL_PATH, tag, token=token
            )
            if entry is not None:
                break
        if entry is None:
            raise NetworkError(
                f"IntuneWinAppUtil.exe {version} not found "
                f"(tried tags {' and '.join(tags)})"
            )
        download_url = entry.get("download_url")
        if not isinstance(download_url, str) or not download_url:
            raise NetworkError(
                f"The GitHub API reports no download URL for IntuneWinAppUtil.exe "
                f"{version}"
            )
        content = download(
            session, download_url, what=f"IntuneWinAppUtil.exe {version}", timeout=60
        )

    # Check the download against what the repository reports for the file.
    verify_size(f"IntuneWinAppUtil.exe {version}", content, entry.get("size"))
    sha = entry.get("sha")
    if isinstance(sha, str) and _git_blob_sha(content) != sha.lower():
        raise NetworkError(
            f"Downloaded IntuneWinAppUtil.exe {version} does not match the hash "
            f"the repository reports for it ({sha}). Try again; if it persists, "
            "the download is being altered in transit."
        )
    logger.verbose("PACKAGE", "Download matches the repository's size and hash")

    # Land the file in one rename, so a run killed mid-write leaves no
    # partial exe that the cache check above would accept.
    try:
        write_bytes_atomic(tool_path, content)
    except OSError as err:
        raise PackagingError(f"Cannot write {tool_path}: {err}") from err

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
    except OSError as err:
        raise PackagingError(
            f"Cannot run IntuneWinAppUtil.exe ({tool_path}): {err}. The tool "
            "runs on Windows only; 'napt package' needs a Windows host."
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
    source = build_dir / name
    if not source.is_file():
        raise PackagingError(
            f"The build manifest names {name}, which is not in {build_dir}. "
            "Run 'napt build' to create the build again."
        )
    shutil.copy2(source, destination / name)
    get_global_logger().verbose("PACKAGE", f"Copied: {name}")


@dataclass(frozen=True)
class PackageResult:
    """Result from creating a .intunewin package.

    Attributes:
        build_dir: Path to the build directory.
        package_path: Path to the created .intunewin file.
        app_id: Unique application identifier.
        version: Application version.
    """

    build_dir: Path
    package_path: Path
    app_id: str
    version: str


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
    manifest = read_build_manifest(
        build_dir,
        ("installer_sha256", "detection_script_path"),
        "Run 'napt build' to create the build again.",
    )
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
        version_output_dir / MANIFEST_NAME,
        json.dumps(manifest, indent=2) + "\n",
    )
    logger.verbose("PACKAGE", f"Wrote: {MANIFEST_NAME}")

    logger.step(5, 5, "Package complete")
    logger.verbose("PACKAGE", f"[OK] Package created: {package_path}")

    return PackageResult(
        build_dir=build_dir,
        package_path=package_path,
        app_id=app_id,
        version=version,
    )
