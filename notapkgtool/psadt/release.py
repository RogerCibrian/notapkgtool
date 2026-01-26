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
releases from the official GitHub repository. It reuses NAPT's existing
GitHub release discovery infrastructure for consistency.

Key Features:

- Fetch latest PSADT version from GitHub API
- Download and cache specific PSADT versions
- Extract releases to cache directory
- Version resolution ("latest" keyword support)

Example:
    Get and cache PSADT releases:
        ```python
        from pathlib import Path
        from notapkgtool.psadt import get_psadt_release, is_psadt_cached

        # Get latest PSADT
        psadt_dir = get_psadt_release("latest", Path("cache/psadt"))

        # Get specific version
        psadt_dir = get_psadt_release("4.1.7", Path("cache/psadt"))

        # Check if cached
        if is_psadt_cached("4.1.7", Path("cache/psadt")):
            print("Already cached!")
        ```

Note:
    - Reuses notapkgtool.discovery.api_github for API calls
    - Caches releases by version: cache/psadt/{version}/
    - Downloads .zip releases and extracts to cache
    - Validates extracted PSADT structure (PSAppDeployToolkit/ folder exists)

"""

from __future__ import annotations

from pathlib import Path
import re
import zipfile

import requests

from notapkgtool.exceptions import NetworkError, PackagingError

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
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    logger.verbose("PSADT", f"Querying GitHub API: {PSADT_GITHUB_API}")

    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        response = requests.get(PSADT_GITHUB_API, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as err:
        raise NetworkError(
            f"Failed to fetch latest PSADT release from GitHub: {err}"
        ) from err

    data = response.json()
    tag_name = data.get("tag_name", "")

    if not tag_name:
        raise NetworkError("GitHub API response missing 'tag_name' field")

    # Extract version from tag (e.g., "4.1.7" or "v4.1.7")
    # PSADT uses tags without 'v' prefix
    version_match = re.match(r"v?(\d+\.\d+\.\d+)", tag_name)
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
        NetworkError: If download fails.
        PackagingError: If extraction fails.
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
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    # Resolve "latest" to actual version
    if release_spec == "latest":
        logger.verbose("PSADT", "Resolving 'latest' to current version...")
        version = fetch_latest_psadt_version()
    else:
        version = release_spec

    logger.verbose("PSADT", f"PSADT version: {version}")

    # Check if already cached
    if is_psadt_cached(version, cache_dir):
        version_dir = cache_dir / version
        logger.verbose("PSADT", f"Using cached PSADT: {version_dir}")
        return version_dir

    # Need to download
    logger.verbose("PSADT", f"Downloading PSADT {version}...")

    # Get release info from GitHub
    release_url = f"https://api.github.com/repos/{PSADT_REPO}/releases/tags/{version}"

    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        response = requests.get(release_url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as err:
        raise NetworkError(
            f"Failed to fetch PSADT release {version} from GitHub: {err}"
        ) from err

    release_data = response.json()

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

    # Download the .zip file
    try:
        zip_response = requests.get(download_url, timeout=300)
        zip_response.raise_for_status()
    except requests.RequestException as err:
        raise NetworkError(f"Failed to download PSADT release: {err}") from err

    # Create cache directory
    version_dir = cache_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)

    # Save .zip temporarily
    zip_path = version_dir / f"psadt_{version}.zip"
    zip_path.write_bytes(zip_response.content)

    logger.verbose("PSADT", f"Extracting to: {version_dir}")

    # Extract .zip
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(version_dir)
    except zipfile.BadZipFile as err:
        raise PackagingError(f"Failed to extract PSADT archive: {err}") from err
    finally:
        # Clean up .zip file
        if zip_path.exists():
            zip_path.unlink()

    # Verify extracted structure
    if not is_psadt_cached(version, cache_dir):
        raise PackagingError(
            f"PSADT extraction failed: PSAppDeployToolkit/ folder "
            f"not found in {version_dir}"
        )

    logger.verbose("PSADT", f"PSADT {version} cached successfully")

    return version_dir
