"""
State tracking implementation for NAPT.

This module implements the state persistence layer for tracking discovered
application versions, ETags, and download metadata between runs.

Key Features
------------
- JSON-based state storage (fast parsing, standard library)
- Automatic ETag/Last-Modified tracking for conditional requests
- Version change detection
- Robust error handling (corrupted files, missing data)
- Auto-creation of state files and directories

State File Schema
-----------------
Schema v2 (filesystem-first approach):
{
  "metadata": {
    "napt_version": "0.1.0",
    "schema_version": "2",
    "last_updated": "2024-10-28T10:30:00Z"
  },
  "apps": {
    "recipe-id": {
      "url": "https://vendor.com/installer.msi",
      "etag": "W/\"abc123\"",
      "last_modified": "Mon, 28 Oct 2024 10:30:00 GMT",
      "sha256": "def456...",
      "known_version": "1.2.3",
      "strategy": "http_static"
    }
  }
}

Key Changes from v1:
- url: Added for provenance tracking (what URL does this ETag apply to)
- etag/last_modified/sha256: Kept (HTTP optimization, integrity checks)
- known_version: Renamed from "version" (informational only, not source of truth)
- strategy: Kept for debugging
- Removed: file_path (use convention), last_checked (use file mtime), source (renamed)

Usage
-----
High-level API with StateTracker:

    from notapkgtool.state import StateTracker

    tracker = StateTracker(Path("state/versions.json"))
    tracker.load()

    # Get cache for conditional requests
    cache = tracker.get_cache("napt-chrome")

    # Update after discovery
    tracker.update_cache("napt-chrome", version="130.0.0", ...)
    tracker.save()

Low-level API with functions:

    from notapkgtool.state import load_state, save_state

    state = load_state(Path("state/versions.json"))
    # ... modify state dict ...
    save_state(state, Path("state/versions.json"))
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class StateTracker:
    """
    Manages application state tracking with automatic persistence.

    This class provides a high-level interface for loading, querying, and
    updating the state file. It handles file I/O, error recovery, and
    provides convenience methods for common operations.

    Attributes
    ----------
    state_file : Path
        Path to the JSON state file.
    state : dict
        In-memory state dictionary.

    Examples
    --------
    Basic usage:

        >>> tracker = StateTracker(Path("state/versions.json"))
        >>> tracker.load()
    >>> cache = tracker.get_cache("napt-chrome")
    >>> tracker.update_cache("napt-chrome",
    ...     url="https://...", sha256="...", known_version="130.0.0")
    >>> tracker.save()
    """

    def __init__(self, state_file: Path):
        """
        Initialize state tracker.

        Parameters
        ----------
        state_file : Path
            Path to JSON state file. Created if doesn't exist.
        """
        self.state_file = state_file
        self.state: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """
        Load state from file.

        Creates default state structure if file doesn't exist.
        Handles corrupted files by creating backup and starting fresh.

        Returns
        -------
        dict
            Loaded state dictionary.

        Raises
        ------
        OSError
            If file permissions prevent reading.
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
            raise RuntimeError(
                f"Corrupted state file backed up to {backup}. "
                f"Created fresh state file."
            ) from err

        return self.state

    def save(self) -> None:
        """
        Save current state to file.

        Updates metadata.last_updated timestamp automatically.
        Creates parent directories if needed.

        Raises
        ------
        OSError
            If file permissions prevent writing.
        """
        # Update metadata
        self.state.setdefault("metadata", {})
        self.state["metadata"]["last_updated"] = datetime.now(UTC).isoformat()

        # Ensure parent directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        save_state(self.state, self.state_file)

    def get_cache(self, recipe_id: str) -> dict[str, Any] | None:
        """
        Get cached information for a recipe.

        Parameters
        ----------
        recipe_id : str
            Recipe identifier (from recipe's 'id' field).

        Returns
        -------
        dict or None
            Cached data if available, None otherwise.

        Examples
        --------
        >>> cache = tracker.get_cache("napt-chrome")
        >>> if cache:
        ...     etag = cache.get('etag')
        ...     known_version = cache.get('known_version')
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
        """
        Update cached information for a recipe.

        Parameters
        ----------
        recipe_id : str
            Recipe identifier.
        url : str
            Download URL (for ETag association and provenance).
        sha256 : str
            SHA-256 hash of file (for integrity checks).
        etag : str, optional
            ETag header from download response (for HTTP 304).
        last_modified : str, optional
            Last-Modified header from download response.
        known_version : str, optional
            Version string (informational only, not source of truth).
        strategy : str, optional
            Discovery strategy used (for debugging).

        Examples
        --------
        >>> tracker.update_cache(
        ...     "napt-chrome",
        ...     url="https://dl.google.com/chrome.msi",
        ...     sha256="abc123...",
        ...     etag='W/"def456"',
        ...     known_version="130.0.0"
        ... )

        Notes
        -----
        Schema v2: Removed file_path, last_checked, and renamed version→known_version.
        Filesystem is the source of truth; state is for HTTP optimization only.
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
        """
        Check if discovered version differs from cached known_version.

        Parameters
        ----------
        recipe_id : str
            Recipe identifier.
        new_version : str
            Newly discovered version.

        Returns
        -------
        bool
            True if version changed or no cached version exists.

        Examples
        --------
        >>> if tracker.has_version_changed("napt-chrome", "130.0.0"):
        ...     print("New version available!")

        Notes
        -----
        Uses 'known_version' field which is informational only.
        Real version should be extracted from filesystem during build.
        """
        cache = self.get_cache(recipe_id)
        if not cache:
            return True  # No cache, treat as changed

        return cache.get("known_version") != new_version


def create_default_state() -> dict[str, Any]:
    """
    Create a default empty state structure.

    Returns
    -------
    dict
        Empty state with metadata section.

    Examples
    --------
    >>> state = create_default_state()
    >>> state["apps"] = {}
    """
    return {
        "metadata": {
            "napt_version": "0.1.0",  # TODO: Import from __init__.__version__
            "schema_version": "2",
            "last_updated": datetime.now(UTC).isoformat(),
        },
        "apps": {},
    }


def load_state(state_file: Path) -> dict[str, Any]:
    """
    Load state from JSON file.

    Parameters
    ----------
    state_file : Path
        Path to JSON state file.

    Returns
    -------
    dict
        Loaded state dictionary.

    Raises
    ------
    FileNotFoundError
        If state file doesn't exist.
    json.JSONDecodeError
        If file contains invalid JSON.
    OSError
        If file cannot be read due to permissions.

    Examples
    --------
    >>> from pathlib import Path
    >>> state = load_state(Path("state/versions.json"))
    >>> apps = state.get("apps", {})
    """
    with open(state_file, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict[str, Any], state_file: Path) -> None:
    """
    Save state to JSON file with pretty-printing.

    Creates parent directories if needed. Uses 2-space indentation
    and sorted keys for consistent diffs in version control.

    Parameters
    ----------
    state : dict
        State dictionary to save.
    state_file : Path
        Path to JSON state file.

    Raises
    ------
    OSError
        If file cannot be written due to permissions.

    Examples
    --------
    >>> from pathlib import Path
    >>> state = {"metadata": {}, "apps": {}}
    >>> save_state(state, Path("state/versions.json"))

    Notes
    -----
    - Uses 2-space indentation for readability
    - Sorts keys alphabetically for consistent diffs
    - Adds trailing newline for git compatibility
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")  # Trailing newline for git
