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

This module provides the JSON load/save helpers for the discovery cache: a
disposable optimization file (default ``cache/discovery.json``) that tracks
discovered versions, ETags, and download metadata between runs. Deleting it
costs one full re-download per app and nothing else — the filesystem and
deployment state remain the source of truth.

The cached fields serve two optimization approaches, both implemented by
the discovery flows that consume this file:

- VERSION-FIRST (api_github, api_json, web_scrape): known_version comparison
- FILE-FIRST (url_download): etag/last_modified HTTP conditional requests
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def cache_file_path(config: dict[str, Any]) -> Path:
    """Returns the discovery cache file path from merged configuration.

    Args:
        config: Merged configuration containing ``directories.cache``.

    Returns:
        Path to the discovery cache file (``<directories.cache>/discovery.json``).

    """
    return Path(config["directories"]["cache"]) / "discovery.json"


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
