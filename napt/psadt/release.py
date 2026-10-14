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

This module fetches, verifies, and caches PSAppDeployToolkit releases from
the official GitHub repository through [napt.github][].

Key Features:

- Resolve "latest" to the current release, or find a pinned version's
  release however the repository tags it
- Download the Template_v4 archive and check it against what the release
  publishes for it
- Extract into the cache only once the archive holds what NAPT builds from

Note:
    - Caches releases by version: cache/psadt/{version}/
    - Checks the download against the digest (or size) the release
      publishes for the asset
    - Extracts in a working folder beside the entry, and moves the result
      into place only once verified, so an interrupted run leaves no entry
      behind; a working folder a killed run left behind is removed once it
      is a day old
    - A cache entry counts only when it holds every Template_v4 entry NAPT
      builds from, the same check the download passes
    - ``GITHUB_TOKEN`` in the environment is sent on the API calls, which
      otherwise count against the unauthenticated limit of 60 per hour

"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
import zipfile

from napt.download.download import make_session
from napt.exceptions import NetworkError, PackagingError
from napt.github import (
    asset_names,
    asset_url,
    download,
    env_token,
    find_asset,
    latest_release,
    normalize_release_spec,
    release_by_version,
    release_tag,
    verify_size,
    version_from_tag,
)
from napt.logging import get_global_logger

PSADT_REPO = "PSAppDeployToolkit/PSAppDeployToolkit"

# What NAPT's build reads from a Template_v4 archive: the module, the invoke
# script it generates from, the launcher, and the folder the installer is
# copied into. A trailing slash marks a folder.
REQUIRED_TEMPLATE_ENTRIES = (
    "PSAppDeployToolkit/PSAppDeployToolkit.psd1",
    "Invoke-AppDeployToolkit.ps1",
    "Invoke-AppDeployToolkit.exe",
    "Files/",
)

# Age after which a working folder is taken to be a killed run's leftover.
_STALE_WORK_DIR_SECONDS = 24 * 60 * 60


def missing_template_entries(root: Path) -> list[str]:
    """Lists the Template_v4 entries NAPT needs that a folder lacks.

    Args:
        root: An extracted archive, a cache entry, or a build directory.

    Returns:
        The missing entries, in the order NAPT lists them; empty when the
        layout is the one NAPT builds from.
    """
    missing = []
    for entry in REQUIRED_TEMPLATE_ENTRIES:
        path = root / entry.rstrip("/")
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
        verify_size(name, content, size)
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


def is_psadt_cached(version: str, cache_dir: Path) -> bool:
    """Reports whether a PSADT version is cached and complete.

    Args:
        version: PSADT version to check (e.g., "4.1.7").
        cache_dir: Base cache directory (e.g., Path("cache/psadt")).

    Returns:
        True if the cache entry holds every Template_v4 entry NAPT builds
        from, False otherwise.

    Example:
        Check if PSADT version is cached:
            ```python
            from pathlib import Path

            if is_psadt_cached("4.1.7", Path("cache/psadt")):
                print("Already downloaded!")
            ```

    """
    return not missing_template_entries(cache_dir / version)


def _template_archive(tag: str, release: dict[str, Any]) -> dict[str, Any]:
    """Picks the Template_v4 archive out of a release's assets.

    Args:
        tag: The release tag, for the message.
        release: The release object.

    Returns:
        The asset entry.

    Raises:
        NetworkError: If the release has no Template_v4 zip; NAPT builds
            from nothing else.
    """
    asset = find_asset(
        release, lambda name: name.endswith(".zip") and "Template_v4" in name
    )
    if asset is None:
        raise NetworkError(
            f"PSADT release {tag} has no Template_v4 archive, which NAPT builds "
            f"from. Assets: {', '.join(asset_names(release)) or '(none)'}"
        )
    return asset


def _install_archive(content: bytes, name: str, version: str, cache_dir: Path) -> Path:
    """Extracts a verified archive into the cache.

    Extraction happens in a working folder beside the cache entry, and
    the result is moved into place only once it is complete and holds
    what NAPT builds from. A run killed part-way then leaves no cache
    entry.

    Args:
        content: The archive bytes.
        name: The asset name, for messages.
        version: The version the entry is cached under.
        cache_dir: Base cache directory for PSADT releases.

    Returns:
        The cache entry.

    Raises:
        PackagingError: If the archive cannot be extracted, lacks the
            Template_v4 entries NAPT builds from, or the cache cannot be
            written.
    """
    logger = get_global_logger()
    version_dir = cache_dir / version
    work_dir = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=cache_dir))
    try:
        staging = work_dir / "extracted"
        staging.mkdir()
        logger.verbose("PSADT", f"Extracting to: {staging}")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                zf.extractall(staging)
        except zipfile.BadZipFile as err:
            raise PackagingError(f"Failed to extract PSADT archive: {err}") from err

        # NAPT builds from the Template_v4 layout; say exactly what is
        # missing when a release does not have it.
        missing = missing_template_entries(staging)
        if missing:
            raise PackagingError(
                f"PSADT {version} ({name}) does not have the Template_v4 layout "
                f"NAPT builds from; missing: {', '.join(missing)}"
            )

        # A partial entry from an older NAPT, or an interrupted extraction
        # that still landed, is replaced; is_psadt_cached did not accept it.
        if version_dir.exists():
            shutil.rmtree(version_dir)
        staging.replace(version_dir)
    except OSError as err:
        raise PackagingError(
            f"Cannot write the PSADT cache entry {version_dir}: {err}"
        ) from err
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return version_dir


def get_psadt_release(release_spec: str, cache_dir: Path) -> Path:
    """Returns the cache entry for a PSADT release, downloading it if needed.

    Resolves "latest" to the current release, or finds a pinned version's
    release under either tag spelling, then downloads the Template_v4
    archive, verifies it, and extracts it into the cache.

    Args:
        release_spec: Version specifier - either "latest" or specific version
            (e.g., "4.1.7" or "v4.1.7").
        cache_dir: Base cache directory for PSADT releases.

    Returns:
        Path to the cached PSADT directory (cache_dir/{version}).

    Raises:
        NetworkError: If the lookup or download fails, the release has no
            Template_v4 archive, or the download does not match what the
            release publishes for it.
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

    """
    logger = get_global_logger()
    token = env_token()
    with make_session() as session:
        release: dict[str, Any] | None = None
        if release_spec == "latest":
            logger.verbose("PSADT", "Resolving 'latest' to current version...")
            release = latest_release(session, PSADT_REPO, token=token)
            tag = release_tag(release)
            version = version_from_tag(tag)
            logger.verbose("PSADT", f"Latest PSADT version: {version}")
        else:
            version = normalize_release_spec(release_spec, "psadt.release", "4.1.7")

        logger.verbose("PSADT", f"PSADT version: {version}")
        cache_dir.mkdir(parents=True, exist_ok=True)
        _remove_stale_work_dirs(cache_dir)

        if is_psadt_cached(version, cache_dir):
            version_dir = cache_dir / version
            logger.info("PSADT", f"Using cached PSADT: {version_dir}")
            return version_dir

        logger.info("PSADT", f"Downloading PSADT {version}...")
        if release is None:
            _, release = release_by_version(session, PSADT_REPO, version, token=token)

        asset = _template_archive(release_tag(release), release)
        name = str(asset.get("name"))
        logger.verbose("PSADT", f"Downloading: {name}")
        content = download(session, asset_url(asset), what=name)

    # Check it is the archive the release published before trusting
    # anything inside it.
    _verify_download(asset, content)
    version_dir = _install_archive(content, name, version, cache_dir)
    logger.verbose("PSADT", f"PSADT {version} cached successfully")
    return version_dir
