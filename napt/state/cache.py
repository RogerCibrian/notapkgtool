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

"""Discovery cache persistence for NAPT.

This module implements the discovery cache: a disposable optimization file
(default ``cache/discovery.json``) that tracks discovered versions, ETags,
and download metadata between runs. Deleting it costs one full re-download
per app and nothing else — the filesystem and deployment state remain the
source of truth.

The cache supports two optimization approaches:

- VERSION-FIRST (url_pattern, api_github, api_json): Uses known_version for comparison
- FILE-FIRST (url_download): Uses etag/last_modified for HTTP conditional requests

Key Features:

- JSON-based cache storage (fast parsing, standard library)
- Automatic ETag/Last-Modified tracking for conditional requests
- Version change detection for version-first strategies
- Robust error handling (corrupted files, missing data)
- Auto-creation of cache files and directories

Example:
    High-level API with DiscoveryCache:
        ```python
        from pathlib import Path
        from napt.state import DiscoveryCache

        cache = DiscoveryCache(Path("cache/discovery.json"))
        cache.load()

        # Get entry for conditional requests
        entry = cache.get_cache("napt-chrome")

        # Update after discovery
        cache.update_cache("napt-chrome", version="130.0.0", ...)
        cache.save()
        ```

    Low-level API with functions:
        ```python
        from pathlib import Path
        from napt.state import load_cache, save_cache

        data = load_cache(Path("cache/discovery.json"))
        # ... modify cache dict ...
        save_cache(data, Path("cache/discovery.json"))
        ```

"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from napt import __version__
from napt.exceptions import PackagingError


def cache_file_path(config: dict[str, Any]) -> Path:
    """Returns the discovery cache file path from merged configuration.

    Args:
        config: Merged configuration containing ``directories.cache``.

    Returns:
        Path to the discovery cache file (``<directories.cache>/discovery.json``).

    """
    return Path(config["directories"]["cache"]) / "discovery.json"


class DiscoveryCache:
    """Manages the discovery cache with automatic persistence.

    This class provides a high-level interface for loading, querying, and
    updating the cache file. It handles file I/O, error recovery, and
    provides convenience methods for common operations.

    Attributes:
        cache_file: Path to the JSON cache file.
        data: In-memory cache dictionary.

    Example:
        Basic usage:
            ```python
            from pathlib import Path

            cache = DiscoveryCache(Path("cache/discovery.json"))
            cache.load()
            entry = cache.get_cache("napt-chrome")
            cache.update_cache(
                "napt-chrome",
                url="https://...",
                sha256="...",
                known_version="130.0.0"
            )
            cache.save()
            ```

    """

    def __init__(self, cache_file: Path):
        """Initialize discovery cache.

        Args:
            cache_file: Path to JSON cache file. Created if doesn't exist.

        """
        self.cache_file = cache_file
        self.data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """Load cache from file.

        Creates default cache structure if file doesn't exist.
        Handles corrupted files by creating backup and starting fresh.

        Returns:
            Loaded cache dictionary.

        Raises:
            OSError: If file permissions prevent reading.

        """
        try:
            self.data = load_cache(self.cache_file)
        except FileNotFoundError:
            # First run, create default cache
            self.data = create_default_cache()
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.save()
        except json.JSONDecodeError as err:
            # Corrupted file, backup and create new
            backup = self.cache_file.with_suffix(".json.backup")
            self.cache_file.rename(backup)
            self.data = create_default_cache()
            self.save()
            raise PackagingError(
                f"Corrupted cache file backed up to {backup}. "
                f"Created fresh cache file."
            ) from err

        return self.data

    def save(self) -> None:
        """Save current cache to file.

        Updates metadata.last_updated timestamp automatically.
        Creates parent directories if needed.

        Raises:
            OSError: If file permissions prevent writing.

        """
        # Update metadata
        self.data.setdefault("metadata", {})
        self.data["metadata"]["last_updated"] = datetime.now(UTC).isoformat()

        # Ensure parent directory exists
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

        save_cache(self.data, self.cache_file)

    def get_cache(self, recipe_id: str) -> dict[str, Any] | None:
        """Get cached information for a recipe.

        Args:
            recipe_id: Recipe identifier (from recipe's 'id' field).

        Returns:
            Cached data if available, None otherwise.

        Example:
            Retrieve cached information:
                ```python
                entry = cache.get_cache("napt-chrome")
                if entry:
                    etag = entry.get('etag')
                    known_version = entry.get('known_version')
                ```

        """
        return self.data.get("apps", {}).get(recipe_id)

    def update_cache(
        self,
        recipe_id: str,
        url: str,
        sha256: str,
        etag: str | None = None,
        last_modified: str | None = None,
        known_version: str | None = None,
        strategy: str | None = None,
    ) -> None:
        """Update cached information for a recipe.

        Args:
            recipe_id: Recipe identifier.
            url: Download URL for provenance tracking. For version-first strategies
                (url_pattern, api_github, api_json), this is the actual download URL
                from version_info. For file-first (url_download), this is discovery.url.
            sha256: SHA-256 hash of file (for integrity checks).
            etag: ETag header from download response. Used by url_download for HTTP 304
                conditional requests. Saved but unused by version-first strategies.
            last_modified: Last-Modified header from download response.
                Used by url_download as fallback for conditional requests.
                Saved but unused by version-first.
            known_version: Version string. PRIMARY cache key for
                version-first strategies (compared to skip downloads).
                Informational only for url_download.
            strategy: Discovery strategy used (for debugging).

        Example:
            Update cache entry:
                ```python
                cache.update_cache(
                    "napt-chrome",
                    url="https://dl.google.com/chrome.msi",
                    sha256="abc123...",
                    etag='W/"def456"',
                    known_version="130.0.0"
                )
                ```

        Note:
            Schema v2: Removed file_path, last_checked, and renamed
            version -> known_version.

            Field usage differs by strategy type:

            - Version-first: known_version is PRIMARY cache key,
                etag/last_modified unused
            - File-first: etag/last_modified are PRIMARY cache keys,
                known_version informational

            The cache is for optimization only; the filesystem and
            deployment state are the source of truth.

        """
        if "apps" not in self.data:
            self.data["apps"] = {}

        cache_entry = {
            "url": url,
            "etag": etag,
            "last_modified": last_modified,
            "sha256": sha256,
        }

        # Optional fields (only add if provided)
        if known_version is not None:
            cache_entry["known_version"] = known_version
        if strategy is not None:
            cache_entry["strategy"] = strategy

        self.data["apps"][recipe_id] = cache_entry

    def has_version_changed(self, recipe_id: str, new_version: str) -> bool:
        """Check if discovered version differs from cached known_version.

        Args:
            recipe_id: Recipe identifier.
            new_version: Newly discovered version.

        Returns:
            True if version changed or no cached version exists.

        Example:
            Check if version has changed:
                ```python
                if cache.has_version_changed("napt-chrome", "130.0.0"):
                    print("New version available!")
                ```

        Note:
            Uses 'known_version' field which is informational only.
            Real version should be extracted from filesystem during build.

        """
        entry = self.get_cache(recipe_id)
        if not entry:
            return True  # No cache, treat as changed

        return entry.get("known_version") != new_version


def create_default_cache() -> dict[str, Any]:
    """Create a default empty cache structure.

    Returns:
        Empty cache with metadata section.

    Example:
        Create default cache structure:
            ```python
            data = create_default_cache()
            data["apps"] = {}
            ```

    """
    return {
        "metadata": {
            "napt_version": __version__,
            "schema_version": "2",
            "last_updated": datetime.now(UTC).isoformat(),
        },
        "apps": {},
    }


def load_cache(cache_file: Path) -> dict[str, Any]:
    """Load cache from JSON file.

    Args:
        cache_file: Path to JSON cache file.

    Returns:
        Loaded cache dictionary.

    Raises:
        FileNotFoundError: If cache file doesn't exist.
        json.JSONDecodeError: If file contains invalid JSON.
        OSError: If file cannot be read due to permissions.

    Example:
        Load cache from file:
            ```python
            from pathlib import Path

            data = load_cache(Path("cache/discovery.json"))
            apps = data.get("apps", {})
            ```

    """
    with open(cache_file, encoding="utf-8") as f:
        return json.load(f)


def save_cache(data: dict[str, Any], cache_file: Path) -> None:
    """Save cache to JSON file with pretty-printing.

    Creates parent directories if needed. Uses 2-space indentation
    and sorted keys for consistent diffs in version control.

    Args:
        data: Cache dictionary to save.
        cache_file: Path to JSON cache file.

    Raises:
        OSError: If file cannot be written due to permissions.

    Example:
        Save cache to file:
            ```python
            from pathlib import Path

            data = {"metadata": {}, "apps": {}}
            save_cache(data, Path("cache/discovery.json"))
            ```

    Note:
        - Uses 2-space indentation for readability
        - Sorts keys alphabetically for consistent diffs
        - Adds trailing newline for git compatibility

    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")  # Trailing newline for git
