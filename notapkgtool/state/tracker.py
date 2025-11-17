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

"""State tracking implementation for NAPT.

This module implements the state persistence layer for tracking discovered
application versions, ETags, and download metadata between runs.

The state file supports two optimization approaches:

- VERSION-FIRST (url_pattern, api_github, api_json): Uses known_version for comparison
- FILE-FIRST (url_download): Uses etag/last_modified for HTTP conditional requests

Key Features:

- JSON-based state storage (fast parsing, standard library)
- Automatic ETag/Last-Modified tracking for conditional requests
- Version change detection for version-first strategies
- Robust error handling (corrupted files, missing data)
- Auto-creation of state files and directories

Example:
    High-level API with StateTracker:
        ```python
        from pathlib import Path
        from notapkgtool.state import StateTracker

        tracker = StateTracker(Path("state/versions.json"))
        tracker.load()

        # Get cache for conditional requests
        cache = tracker.get_cache("napt-chrome")

        # Update after discovery
        tracker.update_cache("napt-chrome", version="130.0.0", ...)
        tracker.save()
        ```

    Low-level API with functions:
        ```python
        from pathlib import Path
        from notapkgtool.state import load_state, save_state

        state = load_state(Path("state/versions.json"))
        # ... modify state dict ...
        save_state(state, Path("state/versions.json"))
        ```

"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from notapkgtool import __version__
from notapkgtool.exceptions import PackagingError


class StateTracker:
    """Manages application state tracking with automatic persistence.

    This class provides a high-level interface for loading, querying, and
    updating the state file. It handles file I/O, error recovery, and
    provides convenience methods for common operations.

    Attributes:
        state_file: Path to the JSON state file.
        state: In-memory state dictionary.

    Example:
        Basic usage:
            ```python
            from pathlib import Path

            tracker = StateTracker(Path("state/versions.json"))
            tracker.load()
            cache = tracker.get_cache("napt-chrome")
            tracker.update_cache(
                "napt-chrome",
                url="https://...",
                sha256="...",
                known_version="130.0.0"
            )
            tracker.save()
            ```

    """

    def __init__(self, state_file: Path):
        """Initialize state tracker.

        Args:
            state_file: Path to JSON state file. Created if doesn't exist.

        """
        self.state_file = state_file
        self.state: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """Load state from file.

        Creates default state structure if file doesn't exist.
        Handles corrupted files by creating backup and starting fresh.

        Returns:
            Loaded state dictionary.

        Raises:
            OSError: If file permissions prevent reading.

        """
        try:
            self.state = load_state(self.state_file)
        except FileNotFoundError:
            # First run, create default state
            self.state = create_default_state()
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.save()
        except json.JSONDecodeError as err:
            # Corrupted file, backup and create new
            backup = self.state_file.with_suffix(".json.backup")
            self.state_file.rename(backup)
            self.state = create_default_state()
            self.save()
            raise PackagingError(
                f"Corrupted state file backed up to {backup}. "
                f"Created fresh state file."
            ) from err

        return self.state

    def save(self) -> None:
        """Save current state to file.

        Updates metadata.last_updated timestamp automatically.
        Creates parent directories if needed.

        Raises:
            OSError: If file permissions prevent writing.

        """
        # Update metadata
        self.state.setdefault("metadata", {})
        self.state["metadata"]["last_updated"] = datetime.now(UTC).isoformat()

        # Ensure parent directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        save_state(self.state, self.state_file)

    def get_cache(self, recipe_id: str) -> dict[str, Any] | None:
        """Get cached information for a recipe.

        Args:
            recipe_id: Recipe identifier (from recipe's 'id' field).

        Returns:
            Cached data if available, None otherwise.

        Example:
            Retrieve cached information:
                ```python
                cache = tracker.get_cache("napt-chrome")
                if cache:
                    etag = cache.get('etag')
                    known_version = cache.get('known_version')
                ```

        """
        return self.state.get("apps", {}).get(recipe_id)

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
                from version_info. For file-first (url_download), this is source.url.
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
                tracker.update_cache(
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

            Filesystem is the source of truth; state is for optimization only.

        """
        if "apps" not in self.state:
            self.state["apps"] = {}

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

        self.state["apps"][recipe_id] = cache_entry

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
                if tracker.has_version_changed("napt-chrome", "130.0.0"):
                    print("New version available!")
                ```

        Note:
            Uses 'known_version' field which is informational only.
            Real version should be extracted from filesystem during build.

        """
        cache = self.get_cache(recipe_id)
        if not cache:
            return True  # No cache, treat as changed

        return cache.get("known_version") != new_version


def create_default_state() -> dict[str, Any]:
    """Create a default empty state structure.

    Returns:
        Empty state with metadata section.

    Example:
        Create default state structure:
            ```python
            state = create_default_state()
            state["apps"] = {}
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


def load_state(state_file: Path) -> dict[str, Any]:
    """Load state from JSON file.

    Args:
        state_file: Path to JSON state file.

    Returns:
        Loaded state dictionary.

    Raises:
        FileNotFoundError: If state file doesn't exist.
        json.JSONDecodeError: If file contains invalid JSON.
        OSError: If file cannot be read due to permissions.

    Example:
        Load state from file:
            ```python
            from pathlib import Path

            state = load_state(Path("state/versions.json"))
            apps = state.get("apps", {})
            ```

    """
    with open(state_file, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict[str, Any], state_file: Path) -> None:
    """Save state to JSON file with pretty-printing.

    Creates parent directories if needed. Uses 2-space indentation
    and sorted keys for consistent diffs in version control.

    Args:
        state: State dictionary to save.
        state_file: Path to JSON state file.

    Raises:
        OSError: If file cannot be written due to permissions.

    Example:
        Save state to file:
            ```python
            from pathlib import Path

            state = {"metadata": {}, "apps": {}}
            save_state(state, Path("state/versions.json"))
            ```

    Note:
        - Uses 2-space indentation for readability
        - Sorts keys alphabetically for consistent diffs
        - Adds trailing newline for git compatibility

    """
    state_file.parent.mkdir(parents=True, exist_ok=True)

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")  # Trailing newline for git
