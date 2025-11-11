"""PSADT release management for NAPT.

This module handles fetching, downloading, and caching PSAppDeployToolkit
releases from the official GitHub repository. It reuses NAPT's existing
GitHub release discovery infrastructure for consistency.

Key Features:
- Fetch latest PSADT version from GitHub API
- Download and cache specific PSADT versions
- Extract releases to cache directory
- Version resolution ("latest" keyword support)

Public API:

- fetch_latest_psadt_version: Query GitHub for the latest PSADT release version
- get_psadt_release: Download and extract a PSADT release to cache
- is_psadt_cached: Check if a PSADT version is already cached

Example:
    Get and cache PSADT releases:

        from pathlib import Path
        from notapkgtool.psadt import get_psadt_release, is_psadt_cached

        # Get latest PSADT
        psadt_dir = get_psadt_release("latest", Path("cache/psadt"))

        # Get specific version
        psadt_dir = get_psadt_release("4.1.7", Path("cache/psadt"))

        # Check if cached
        if is_psadt_cached("4.1.7", Path("cache/psadt")):
            print("Already cached!")

Note:
    - Reuses notapkgtool.discovery.github_release for API calls
    - Caches releases by version: cache/psadt/{version}/
    - Downloads .zip releases and extracts to cache
    - Validates extracted PSADT structure (PSAppDeployToolkit/ folder exists)

"""

from __future__ import annotations

from pathlib import Path
import re
import zipfile

import requests

PSADT_REPO = "PSAppDeployToolkit/PSAppDeployToolkit"
PSADT_GITHUB_API = f"https://api.github.com/repos/{PSADT_REPO}/releases/latest"


def fetch_latest_psadt_version(verbose: bool = False) -> str:
    """Fetch the latest PSADT release version from GitHub.

    Queries the GitHub API for the latest release and extracts the version
    number from the tag name (e.g., "4.1.7" from tag "4.1.7").

    Args:
    verbose : bool, optional
        If True, print verbose output about the API request.

    Returns:
    str
        Version number (e.g., "4.1.7").

    Raises:
    RuntimeError
        If the GitHub API request fails or version cannot be extracted.

    Example:
        Get latest PSADT version from GitHub:

            version = fetch_latest_psadt_version()
            print(version)  # Output: "4.1.7"

    Note:
        - Uses GitHub's public API (60 requests/hour limit without auth)
        - Version is extracted from release tag name
        - For higher rate limits, set GITHUB_TOKEN environment variable

    """
    from notapkgtool.cli import print_verbose

    print_verbose("PSADT", f"Querying GitHub API: {PSADT_GITHUB_API}")

    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        response = requests.get(PSADT_GITHUB_API, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as err:
        raise RuntimeError(
            f"Failed to fetch latest PSADT release from GitHub: {err}"
        ) from err

    data = response.json()
    tag_name = data.get("tag_name", "")

    if not tag_name:
        raise RuntimeError("GitHub API response missing 'tag_name' field")

    # Extract version from tag (e.g., "4.1.7" or "v4.1.7")
    # PSADT uses tags without 'v' prefix
    version_match = re.match(r"v?(\d+\.\d+\.\d+)", tag_name)
    if not version_match:
        raise RuntimeError(f"Could not extract version from tag: {tag_name!r}")

    version = version_match.group(1)
    print_verbose("PSADT", f"Latest PSADT version: {version}")

    return version


def is_psadt_cached(version: str, cache_dir: Path) -> bool:
    """Check if a PSADT version is already cached.

    Args:
    version : str
        PSADT version to check (e.g., "4.1.7").
    cache_dir : Path
        Base cache directory (e.g., Path("cache/psadt")).

    Returns:
    bool
        True if the version is cached and valid, False otherwise.

    Example:
        Check if PSADT version is cached:

            from pathlib import Path

            if is_psadt_cached("4.1.7", Path("cache/psadt")):
                print("Already downloaded!")

    Note:
        Validates that the cache contains the expected PSADT structure:

        - PSAppDeployToolkit/ folder must exist
        - PSAppDeployToolkit.psd1 manifest must exist

    """
    version_dir = cache_dir / version
    psadt_dir = version_dir / "PSAppDeployToolkit"
    manifest = psadt_dir / "PSAppDeployToolkit.psd1"

    return psadt_dir.exists() and manifest.exists()


def get_psadt_release(
    release_spec: str, cache_dir: Path, verbose: bool = False, debug: bool = False
) -> Path:
    """Download and extract a PSADT release to the cache directory.

    Resolves "latest" to the current latest version from GitHub, then
    downloads the release .zip file and extracts it to the cache.

    Args:
    release_spec : str
        Version specifier - either "latest" or specific version (e.g., "4.1.7").
    cache_dir : Path
        Base cache directory for PSADT releases.
    verbose : bool, optional
        Show verbose progress output.
    debug : bool, optional
        Show debug output.

    Returns:
    Path
        Path to the cached PSADT directory (cache_dir/{version}).

    Raises:
    RuntimeError
        If download fails or extraction fails.
    ValueError
        If release_spec is invalid.

    Example:
        Get latest version:

            from pathlib import Path

            psadt = get_psadt_release("latest", Path("cache/psadt"))
            print(psadt)  # Output: cache/psadt/4.1.7

        Get specific version:

            psadt = get_psadt_release("4.1.7", Path("cache/psadt"))

    Note:
        - Caches by version: cache/psadt/{version}/PSAppDeployToolkit/
        - If already cached, returns path immediately (no re-download)
        - Downloads from GitHub releases as .zip files
        - Extracts entire archive to version directory

    """
    from notapkgtool.cli import print_verbose

    # Resolve "latest" to actual version
    if release_spec == "latest":
        print_verbose("PSADT", "Resolving 'latest' to current version...")
        version = fetch_latest_psadt_version(verbose=verbose)
    else:
        version = release_spec

    print_verbose("PSADT", f"PSADT version: {version}")

    # Check if already cached
    if is_psadt_cached(version, cache_dir):
        version_dir = cache_dir / version
        print_verbose("PSADT", f"Using cached PSADT: {version_dir}")
        return version_dir

    # Need to download
    print_verbose("PSADT", f"Downloading PSADT {version}...")

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
        raise RuntimeError(
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
        raise RuntimeError(
            f"No .zip asset found in PSADT release {version}. "
            f"Available assets: {[a.get('name') for a in assets]}"
        )

    download_url = zip_asset.get("browser_download_url")
    if not download_url:
        raise RuntimeError(f"Asset missing download URL: {zip_asset}")

    print_verbose("PSADT", f"Downloading: {zip_asset['name']}")

    # Download the .zip file
    try:
        zip_response = requests.get(download_url, timeout=300)
        zip_response.raise_for_status()
    except requests.RequestException as err:
        raise RuntimeError(f"Failed to download PSADT release: {err}") from err

    # Create cache directory
    version_dir = cache_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)

    # Save .zip temporarily
    zip_path = version_dir / f"psadt_{version}.zip"
    zip_path.write_bytes(zip_response.content)

    print_verbose("PSADT", f"Extracting to: {version_dir}")

    # Extract .zip
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(version_dir)
    except zipfile.BadZipFile as err:
        raise RuntimeError(f"Failed to extract PSADT archive: {err}") from err
    finally:
        # Clean up .zip file
        if zip_path.exists():
            zip_path.unlink()

    # Verify extracted structure
    if not is_psadt_cached(version, cache_dir):
        raise RuntimeError(
            f"PSADT extraction failed: PSAppDeployToolkit/ folder not found in {version_dir}"
        )

    print_verbose("PSADT", f"PSADT {version} cached successfully")

    return version_dir
