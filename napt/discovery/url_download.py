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

"""url_download discovery flow.

This module is intentionally not a
[DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy]. The
strategies in [napt.discovery.base][] produce a
[RemoteVersion][napt.discovery.base.RemoteVersion] from configuration
alone (version-first). ``url_download`` cannot do that — it has no
remote endpoint to query for the version, so it must download the
installer and extract the version from the file's metadata. The
discovery orchestrator special-cases ``strategy: url_download`` and
dispatches to
[run_url_download][napt.discovery.url_download.run_url_download] directly.

Cache Strategy:
    Uses HTTP conditional requests. If a previous run stored an ``ETag``
    or ``Last-Modified`` header in state, those are sent as
    ``If-None-Match`` / ``If-Modified-Since`` on the next request. A
    server response of HTTP 304 reuses the cached file without a
    re-download. This is a different mechanism than the version-first
    strategies, which compare version strings (no HTTP round-trip
    required to detect "no change" beyond the initial discovery query).

Supported File Types:
    - ``.msi`` — version is read from the MSI ProductVersion property.
    - Other extensions raise [ConfigError][napt.exceptions.ConfigError].
        For non-MSI installers, use a version-first strategy.

Recipe Example:
    ```yaml
    discovery:
      strategy: url_download
      url: "https://vendor.example.com/installer.msi"
    ```

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from napt.download import download_file
from napt.exceptions import ConfigError, NetworkError, NotModifiedError
from napt.versioning.msi import extract_msi_metadata

from .base import StrategyResult


def run_url_download(
    app_config: dict[str, Any],
    output_dir: Path,
    cache: dict[str, Any] | None = None,
) -> StrategyResult:
    """Downloads a fixed URL and extracts the version from the resulting file.

    Issues a conditional HTTP request when ``cache`` carries an ``ETag``
    or ``Last-Modified``. On HTTP 304 the cached file is reused; otherwise
    the fresh download is used. Either way, the version is extracted from
    the file (MSI ProductVersion today).

    Args:
        app_config: Merged recipe configuration dict containing
            ``discovery.url`` and ``id``.
        output_dir: Base directory to download into. The file lands
            in ``output_dir / app_id``.
        cache: Cached state for this recipe (``etag``, ``last_modified``,
            ``file_path``, ``sha256``), or ``None`` when no prior state
            exists or stateless mode is on.

    Returns:
        Resolved version, file path, and download metadata. The
        ``cached`` field is True when HTTP 304 was used to reuse the
        previously downloaded file.

    Raises:
        ConfigError: If ``discovery.url`` is missing, or if the
            downloaded file is not an MSI (version extraction is
            not supported for other file types).
        NetworkError: On download or version-extraction failures.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    source = app_config.get("discovery", {})
    url = source.get("url")
    if not url:
        raise ConfigError("url_download strategy requires 'discovery.url' in config")

    app_id = app_config["id"]

    logger.verbose("DISCOVERY", "Strategy: url_download (file-first)")
    logger.verbose("DISCOVERY", f"Source URL: {url}")

    etag = cache.get("etag") if cache else None
    last_modified = cache.get("last_modified") if cache else None
    if etag:
        logger.verbose("DISCOVERY", f"Using cached ETag: {etag}")
    if last_modified:
        logger.verbose("DISCOVERY", f"Using cached Last-Modified: {last_modified}")

    try:
        dl = download_file(
            url,
            output_dir / app_id,
            etag=etag,
            last_modified=last_modified,
        )
    except NotModifiedError:
        return _resolve_not_modified(url, cache, output_dir, app_id, logger)
    except (NetworkError, ConfigError):
        raise
    except Exception as err:
        raise NetworkError(f"Failed to download {url}: {err}") from err

    version = _extract_version(dl.file_path)
    return StrategyResult(
        version=version,
        version_source="url_download",
        file_path=dl.file_path,
        sha256=dl.sha256,
        headers=dl.headers,
        download_url=url,
        cached=False,
    )


def validate_url_download_config(app_config: dict[str, Any]) -> list[str]:
    """Validates url_download configuration fields.

    Called by [napt.validation.validate_config][] to compose the
    url_download field rules into the overall recipe validation.

    Args:
        app_config: Merged recipe configuration dict.

    Returns:
        Human-readable error messages. Empty when configuration is valid.

    """
    errors: list[str] = []
    source = app_config.get("discovery", {})

    if "url" not in source:
        errors.append("Missing required field: discovery.url")
    elif not isinstance(source["url"], str):
        errors.append("discovery.url must be a string")
    elif not source["url"].strip():
        errors.append("discovery.url cannot be empty")

    return errors


def _resolve_not_modified(
    url: str,
    cache: dict[str, Any] | None,
    output_dir: Path,
    app_id: str,
    logger: Any,
) -> StrategyResult:
    """Handles HTTP 304 by reusing the cached file or forcing re-download.

    When the server reports the file is unchanged, this attempts to reuse
    the cached file path. If the cache is incomplete or the file is gone
    from disk, it falls back to an unconditional re-download.

    Args:
        url: Original download URL (used for re-download fallback).
        cache: Cached state for this recipe, if any.
        output_dir: Base directory to download into for the fallback path.
        app_id: Recipe app id, used for the per-app subdirectory.
        logger: Global logger instance, passed in to avoid repeated lookups.

    Returns:
        Resolved version, file path, and download metadata. The
        ``cached`` field is True when the previously cached file was
        reused; False when the fallback re-download was used.

    Raises:
        NetworkError: On re-download or version-extraction failure.
        ConfigError: If the cached file is not an MSI.

    """
    logger.info("CACHE", "File not modified (HTTP 304), using cached version")

    cached_path_str = cache.get("file_path") if cache else None
    cached_sha = cache.get("sha256") if cache else None
    cached_path = Path(cached_path_str) if cached_path_str else None

    if cache and cached_sha and cached_path is not None and cached_path.exists():
        version = _extract_version(cached_path)
        preserved_headers: dict[str, str] = {}
        if cache.get("etag"):
            preserved_headers["ETag"] = cache["etag"]
        if cache.get("last_modified"):
            preserved_headers["Last-Modified"] = cache["last_modified"]
        return StrategyResult(
            version=version,
            version_source="url_download",
            file_path=cached_path,
            sha256=cached_sha,
            headers=preserved_headers,
            download_url=url,
            cached=True,
        )

    logger.warning(
        "CACHE",
        "Cache incomplete or cached file not found, forcing re-download",
    )
    dl = download_file(url, output_dir / app_id)
    version = _extract_version(dl.file_path)
    return StrategyResult(
        version=version,
        version_source="url_download",
        file_path=dl.file_path,
        sha256=dl.sha256,
        headers=dl.headers,
        download_url=url,
        cached=False,
    )


def _extract_version(file_path: Path) -> str:
    """Extracts a version string from an installer file's metadata.

    Currently supports MSI files via
    [extract_msi_metadata][napt.versioning.msi.extract_msi_metadata].
    Other file types raise [ConfigError][napt.exceptions.ConfigError] —
    use a version-first strategy for those instead.

    Args:
        file_path: Path to the downloaded installer file.

    Returns:
        Version string from the file's metadata.

    Raises:
        ConfigError: If ``file_path`` is not an MSI installer.
        NetworkError: If MSI metadata extraction fails.

    """
    if file_path.suffix.lower() != ".msi":
        raise ConfigError(
            f"Cannot extract version from file type: {file_path.suffix!r}. "
            f"url_download strategy currently supports MSI files only. "
            f"For other file types, use a version-first strategy "
            f"(api_github, api_json, web_scrape) or ensure the file "
            f"is an MSI installer."
        )

    try:
        return extract_msi_metadata(file_path).product_version
    except Exception as err:
        raise NetworkError(
            f"Failed to extract MSI ProductVersion from {file_path}: {err}"
        ) from err
