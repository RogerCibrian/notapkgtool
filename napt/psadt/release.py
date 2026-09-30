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

"""PSADT release management for NAPT.

This module handles fetching, downloading, and caching PSAppDeployToolkit
releases from the official GitHub repository. Queries the GitHub releases API
for PSAppDeployToolkit directly.

Key Features:

- Fetch latest PSADT version from GitHub API
- Download and cache specific PSADT versions
- Extract releases to cache directory
- Version resolution ("latest" keyword support)

Note:
    - Caches releases by version: cache/psadt/{version}/
    - Checks the download against the digest (or size) the release
      publishes for the asset
    - Downloads and extracts in a working folder beside the entry, and moves
      the result into place only once verified, so an interrupted run leaves
      no entry behind and the zip never lands in the cache; a working folder
      a killed run left behind is removed once it is a day old
    - Checks the extracted archive for the Template_v4 entries NAPT builds
      from, and names what is missing when a release lacks them

"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any
import zipfile

import requests

from napt.download.download import make_session
from napt.exceptions import ConfigError, NetworkError, PackagingError
from napt.paths import is_safe_path_component

# What NAPT's build reads from a Template_v4 archive: the module, the invoke
# script it generates from, the launcher, and the folder the installer is
# copied into. A trailing slash marks a folder.
_REQUIRED_TEMPLATE_ENTRIES = (
    "PSAppDeployToolkit/PSAppDeployToolkit.psd1",
    "Invoke-AppDeployToolkit.ps1",
    "Invoke-AppDeployToolkit.exe",
    "Files/",
)

# Age after which a working folder is taken to be a killed run's leftover.
_STALE_WORK_DIR_SECONDS = 24 * 60 * 60


def _missing_template_entries(extracted: Path) -> list[str]:
    """Lists the Template_v4 entries NAPT needs that an archive lacks.

    Args:
        extracted: Where the archive was extracted.

    Returns:
        The missing entries, in the order NAPT lists them; empty when the
        layout is the one NAPT builds from.
    """
    missing = []
    for entry in _REQUIRED_TEMPLATE_ENTRIES:
        path = extracted / entry.rstrip("/")
        present = path.is_dir() if entry.endswith("/") else path.is_file()
        if not present:
            missing.append(entry)
    return missing


def _verify_download(asset: dict[str, Any], content: bytes) -> None:
    """Checks a downloaded asset against what the release published for it.

    GitHub publishes a SHA-256 digest for assets of recent releases (PSADT
    from the 4.1 line on) and a size for every asset. The digest is
    checked when present, the size otherwise; a release that publishes
    neither is accepted with a note. Either way this verifies transport,
    not provenance: the values come from the same API response as the
    download link.

    Args:
        asset: The release asset entry from the GitHub API.
        content: The downloaded bytes.

    Raises:
        NetworkError: If the download does not match the digest or size.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    name = asset.get("name", "asset")
    digest = asset.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        actual = hashlib.sha256(content).hexdigest()
        if actual != digest.removeprefix("sha256:").lower():
            raise NetworkError(
                f"Downloaded {name} does not match the digest the release "
                f"publishes (expected {digest}, got sha256:{actual}). Try again; "
                "if it persists, the download is being altered in transit."
            )
        logger.verbose("PSADT", f"Download matches the published digest: {digest}")
        return
    size = asset.get("size")
    if isinstance(size, int):
        if len(content) != size:
            raise NetworkError(
                f"Downloaded {name} is {len(content)} bytes; the release "
                f"publishes {size} bytes. The download was cut short; try again."
            )
        logger.verbose("PSADT", f"Download matches the published size: {size} bytes")
        return
    logger.verbose("PSADT", f"The release publishes no digest or size for {name}")


def _remove_stale_work_dirs(cache_dir: Path) -> None:
    """Removes working folders old enough to be a killed run's leftovers.

    A fresh one may belong to another run still extracting, so it is left
    alone.

    Args:
        cache_dir: Base cache directory for PSADT releases.
    """
    cutoff = time.time() - _STALE_WORK_DIR_SECONDS
    for folder in cache_dir.glob(".*-*"):
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def _release_json(response: requests.Response) -> dict[str, Any]:
    """Reads a GitHub releases API response body as a JSON object.

    Args:
        response: A successful response from the releases API.

    Returns:
        The parsed object.

    Raises:
        NetworkError: If the body is not JSON, or not an object.
    """
    try:
        data = response.json()
    except ValueError as err:
        raise NetworkError(
            f"Invalid JSON response from the GitHub API. Response: "
            f"{response.text[:200]}"
        ) from err
    if not isinstance(data, dict):
        raise NetworkError(f"Unexpected GitHub API response: {response.text[:200]}")
    return data


PSADT_REPO = "PSAppDeployToolkit/PSAppDeployToolkit"
PSADT_GITHUB_API = f"https://api.github.com/repos/{PSADT_REPO}/releases/latest"


def fetch_latest_psadt_version() -> str:
    """Fetch the latest PSADT release version from GitHub.

    Queries the GitHub API for the latest release and extracts the version
    number from the tag name (e.g., "4.1.7" from tag "4.1.7").

    Returns:
        Version number (e.g., "4.1.7").

    Raises:
        RuntimeError: If the GitHub API request fails or version cannot be
            extracted.

    Example:
        Get latest PSADT version from GitHub:
            ```python
            version = fetch_latest_psadt_version()
            print(version)  # Output: "4.1.7"
            ```

    Note:
        - Uses GitHub's public API (60 requests/hour limit without auth)
        - Version is extracted from release tag name
        - For higher rate limits, set GITHUB_TOKEN environment variable

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    logger.verbose("PSADT", f"Querying GitHub API: {PSADT_GITHUB_API}")

    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        with make_session() as session:
            response = session.get(PSADT_GITHUB_API, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as err:
        raise NetworkError(
            f"Failed to fetch latest PSADT release from GitHub: {err}"
        ) from err

    data = _release_json(response)
    tag_name = data.get("tag_name", "")

    if not tag_name:
        raise NetworkError("GitHub API response missing 'tag_name' field")

    # The whole tag must be the version (PSADT tags without a "v" prefix):
    # a suffix such as "-rc1" would otherwise be dropped and the release
    # fetched by that tag would be a different one.
    version_match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", tag_name)
    if not version_match:
        raise NetworkError(f"Could not extract version from tag: {tag_name!r}")

    version = version_match.group(1)
    logger.verbose("PSADT", f"Latest PSADT version: {version}")

    return version


def is_psadt_cached(version: str, cache_dir: Path) -> bool:
    """Check if a PSADT version is already cached.

    Args:
        version: PSADT version to check (e.g., "4.1.7").
        cache_dir: Base cache directory (e.g., Path("cache/psadt")).

    Returns:
        True if the version is cached and valid, False otherwise.

    Example:
        Check if PSADT version is cached:
            ```python
            from pathlib import Path

            if is_psadt_cached("4.1.7", Path("cache/psadt")):
                print("Already downloaded!")
            ```

    Note:
        Validates that the cache contains the expected PSADT structure:

        - PSAppDeployToolkit/ folder must exist
        - PSAppDeployToolkit.psd1 manifest must exist

    """
    version_dir = cache_dir / version
    psadt_dir = version_dir / "PSAppDeployToolkit"
    manifest = psadt_dir / "PSAppDeployToolkit.psd1"

    return psadt_dir.exists() and manifest.exists()


def get_psadt_release(release_spec: str, cache_dir: Path) -> Path:
    """Download and extract a PSADT release to the cache directory.

    Resolves "latest" to the current latest version from GitHub, then
    downloads the release .zip file and extracts it to the cache.

    Args:
        release_spec: Version specifier - either "latest" or specific version
            (e.g., "4.1.7").
        cache_dir: Base cache directory for PSADT releases.

    Returns:
        Path to the cached PSADT directory (cache_dir/{version}).

    Raises:
        NetworkError: If the lookup or download fails, or the download
            does not match what the release publishes for it.
        PackagingError: If extraction fails, the archive lacks the
            Template_v4 entries NAPT builds from, or the cache cannot be
            written.
        ConfigError: If release_spec is invalid.

    Example:
        Get latest version:
            ```python
            from pathlib import Path

            psadt = get_psadt_release("latest", Path("cache/psadt"))
            print(psadt)  # Output: cache/psadt/4.1.7
            ```

        Get specific version:
            ```python
            psadt = get_psadt_release("4.1.7", Path("cache/psadt"))
            ```

    Note:
        - Caches by version: cache/psadt/{version}/PSAppDeployToolkit/
        - If already cached, returns path immediately (no re-download)
        - Downloads from GitHub releases as .zip files
        - Extracts entire archive to version directory

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    # Resolve "latest" to actual version
    if release_spec == "latest":
        logger.verbose("PSADT", "Resolving 'latest' to current version...")
        version = fetch_latest_psadt_version()
    else:
        version = release_spec

    # The version names the cache folder, so it must be a plain folder name.
    if not is_safe_path_component(version):
        raise ConfigError(
            f"Invalid psadt.release {version!a}: use 'latest' or a version "
            "such as '4.1.7'"
        )

    logger.verbose("PSADT", f"PSADT version: {version}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    _remove_stale_work_dirs(cache_dir)

    # Check if already cached
    if is_psadt_cached(version, cache_dir):
        version_dir = cache_dir / version
        logger.verbose("PSADT", f"Using cached PSADT: {version_dir}")
        return version_dir

    # Need to download
    logger.info("PSADT", f"Downloading PSADT {version}...")

    # Get release info from GitHub
    release_url = f"https://api.github.com/repos/{PSADT_REPO}/releases/tags/{version}"

    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        with make_session() as session:
            response = session.get(release_url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as err:
        raise NetworkError(
            f"Failed to fetch PSADT release {version} from GitHub: {err}"
        ) from err

    release_data = _release_json(response)

    # Find the Template_v4 .zip asset (the full v4 template structure)
    assets = release_data.get("assets", [])
    zip_asset = None

    # Look for Template_v4 version specifically
    for asset in assets:
        name = asset.get("name", "")
        if name.endswith(".zip") and "Template_v4" in name:
            zip_asset = asset
            break

    # Fallback to any PSADT zip if Template_v4 not found
    if not zip_asset:
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(".zip") and "PSAppDeployToolkit" in name:
                zip_asset = asset
                break

    if not zip_asset:
        raise NetworkError(
            f"No .zip asset found in PSADT release {version}. "
            f"Available assets: {[a.get('name') for a in assets]}"
        )

    download_url = zip_asset.get("browser_download_url")
    if not download_url:
        raise NetworkError(f"Asset missing download URL: {zip_asset}")

    logger.verbose("PSADT", f"Downloading: {zip_asset['name']}")

    # Download the .zip file and check it is the archive the release
    # published, before trusting anything inside it.
    try:
        with make_session() as session:
            zip_response = session.get(download_url, timeout=300)
        zip_response.raise_for_status()
    except requests.RequestException as err:
        raise NetworkError(f"Failed to download PSADT release: {err}") from err
    _verify_download(zip_asset, zip_response.content)

    # Extract in a working folder beside the cache entry, and move the
    # result into place only once it is complete and verified. A run killed
    # part-way then leaves no cache entry, and the zip never sits in a
    # folder that build copies wholesale into every package.
    version_dir = cache_dir / version
    work_dir = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=cache_dir))
    try:
        zip_path = work_dir / f"psadt_{version}.zip"
        zip_path.write_bytes(zip_response.content)
        staging = work_dir / "extracted"
        staging.mkdir()
        logger.verbose("PSADT", f"Extracting to: {staging}")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(staging)
        except zipfile.BadZipFile as err:
            raise PackagingError(f"Failed to extract PSADT archive: {err}") from err

        # NAPT builds from the Template_v4 layout; say exactly what is
        # missing when a release does not have it.
        missing = _missing_template_entries(staging)
        if missing:
            raise PackagingError(
                f"PSADT {version} ({zip_asset['name']}) does not have the "
                f"Template_v4 layout NAPT builds from; missing: "
                f"{', '.join(missing)}"
            )

        # A partial entry from an older NAPT, or a folder with no manifest,
        # is replaced; is_psadt_cached would not have accepted it.
        if version_dir.exists():
            shutil.rmtree(version_dir)
        staging.replace(version_dir)
    except OSError as err:
        raise PackagingError(
            f"Cannot write the PSADT cache entry {version_dir}: {err}"
        ) from err
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    logger.verbose("PSADT", f"PSADT {version} cached successfully")

    return version_dir
