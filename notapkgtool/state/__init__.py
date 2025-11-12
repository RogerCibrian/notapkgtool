"""State tracking and version management for NAPT.

This module provides state persistence for tracking discovered application
versions, ETags, and file metadata between runs. This enables:

- Efficient conditional downloads (HTTP 304 Not Modified)
- Version change detection
- Bandwidth optimization for scheduled workflows

The state file is a JSON file that stores:

- Discovered versions from vendors
- HTTP ETags and Last-Modified headers for conditional requests
- File paths and SHA-256 hashes for cached installers
- Last checked timestamps for monitoring

State tracking is enabled by default and can be disabled with --stateless flag.

Public API:

- StateTracker: Main interface for state management operations
- load_state: Load state from JSON file
- save_state: Save state to JSON file with pretty-printing

Example:
    Basic usage:

        from pathlib import Path
        from notapkgtool.state import load_state, save_state

        state = load_state(Path("state/versions.json"))

        app_id = "napt-chrome"
        cache = state.get("apps", {}).get(app_id)

        state["apps"][app_id] = {
            "url": "https://dl.google.com/chrome.msi",
            "etag": 'W/"abc123"',
            "sha256": "abc123...",
            "known_version": "130.0.0"
        }

        save_state(state, Path("state/versions.json"))

"""

from .tracker import StateTracker, load_state, save_state

__all__ = ["StateTracker", "load_state", "save_state"]
