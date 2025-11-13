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

"""Core orchestration for NAPT.

This module provides high-level orchestration functions that coordinate the
complete workflow for recipe validation, package building, and deployment.

Design Principles:

- Each function has a single, clear responsibility
- Functions return structured data (dicts) for easy testing and extension
- Error handling uses exceptions; CLI layer formats for user display
- Discovery strategies are dynamically loaded via registry pattern
- Configuration is immutable once loaded
- Two-path architecture optimizes for different strategy types

Example:
    Programmatic usage:

        from pathlib import Path
        from notapkgtool.core import discover_recipe

        result = discover_recipe(
            recipe_path=Path("recipes/Google/chrome.yaml"),
            output_dir=Path("./downloads"),
        )

        print(f"App: {result['app_name']}")
        print(f"Version: {result['version']}")
        print(f"SHA-256: {result['sha256']}")

        # Version-first strategies: may have skipped download if unchanged!

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from notapkgtool import __version__
from notapkgtool.config.loader import load_effective_config
from notapkgtool.discovery import get_strategy
from notapkgtool.io import download_file
from notapkgtool.state import load_state, save_state
from notapkgtool.versioning.keys import DiscoveredVersion


def derive_file_path_from_url(url: str, output_dir: Path) -> Path:
    """Derive file path from URL using same logic as download_file.

    This function ensures version-first strategies can locate cached files
    without downloading by following the same naming convention as the
    download module.

    Args:
        url: Download URL.
        output_dir: Directory where file would be downloaded.

    Returns:
        Expected path to the file.

    Example:
        Get expected file path for a download URL:

            from pathlib import Path

            path = derive_file_path_from_url(
                "https://example.com/app.msi",
                Path("./downloads")
            )
            # Returns: Path('./downloads/app.msi')

    """
    from urllib.parse import urlparse

    filename = Path(urlparse(url).path).name
    return output_dir / filename


def discover_recipe(
    recipe_path: Path,
    output_dir: Path,
    state_file: Path | None = Path("state/versions.json"),
    stateless: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> dict[str, Any]:
    """Discover the latest version by loading config and downloading installer.

    This is the main entry point for the 'napt discover' command. It orchestrates
    the entire discovery workflow using a two-path architecture optimized for
    version-first strategies.

    The function uses duck typing to detect strategy capabilities:

    VERSION-FIRST PATH (if strategy has get_version_info method):

    1. Load effective configuration (org + vendor + recipe merged)
    2. Call strategy.get_version_info() to discover version (no download)
    3. Compare discovered version to cached known_version
    4. If match and file exists -> skip download entirely (fast path!)
    5. If changed or missing -> download installer via download_file()
    6. Update state and return results

    FILE-FIRST PATH (if strategy has only discover_version method):

    1. Load effective configuration (org + vendor + recipe merged)
    2. Call strategy.discover_version() with cached ETag
    3. Strategy handles conditional request (HTTP 304 vs 200)
    4. Extract version from downloaded file
    5. Update state and return results

    Args:
        recipe_path: Path to the recipe YAML file. Must exist and be
            readable. The path is resolved to absolute form.
        output_dir: Directory to download the installer to. Created if
            it doesn't exist. The downloaded file will be named based on
            Content-Disposition header or URL path.
        state_file: Path to state file for version tracking
            and ETag caching. Default is "state/versions.json". Set to None
            to disable.
        stateless: If True, disable state tracking (no caching,
            always download). Default is False.
        verbose: If True, print verbose progress output.
            Default is False.
        debug: If True, print debug output. Default is False.

    Returns:
        A dict (app_name, app_id, strategy, version, version_source,
            file_path, sha256, status), where app_name is the application
            display name, app_id is the unique identifier, strategy is the
            discovery strategy used, version is the extracted version string,
            version_source describes how version was determined, file_path
            is the Path to the downloaded installer, sha256 is the file hash,
            and status is always "success".

    Raises:
        SystemExit: On YAML parse errors or missing recipe file (handled by
            config loader).
        ValueError: On missing or invalid configuration fields (no apps defined,
            missing 'source.strategy' field, unknown discovery strategy name).
        RuntimeError: On download failures or version extraction errors.
        FileNotFoundError: If recipe file doesn't exist (before config loading).

    Example:
        Basic version discovery:

            from pathlib import Path
            result = discover_recipe(
                Path("recipes/Google/chrome.yaml"),
                Path("./downloads")
            )
            print(result['version'])  # 141.0.7390.123

        Handling errors:

            try:
                result = discover_recipe(Path("invalid.yaml"), Path("."))
            except ValueError as e:
                print(f"Config error: {e}")
            except RuntimeError as e:
                print(f"Download error: {e}")

    Note:
        Only the first app in a recipe is currently processed. The discovery
        strategy must be registered before calling this function. Version-first
        strategies (url_regex, github_release, http_json) can skip downloads
        entirely when version unchanged (fast path optimization). File-first
        strategy (http_static) uses ETag conditional requests. Downloaded files
        are written atomically (.part then renamed). Progress output goes to
        stdout via the download module. Strategy type detected via duck typing
        (hasattr for get_version_info).

    """
    from notapkgtool.cli import print_step, print_verbose

    # Load state file unless running in stateless mode
    state = None
    if not stateless and state_file:
        try:
            state = load_state(state_file)
            print_verbose("STATE", f"Loaded state from {state_file}")
        except FileNotFoundError:
            print_verbose("STATE", f"State file not found, will create: {state_file}")
            state = {
                "metadata": {"napt_version": __version__, "schema_version": "2"},
                "apps": {},
            }
        except Exception as err:
            print_verbose("STATE", f"Warning: Failed to load state: {err}")
            print_verbose("STATE", "Continuing without state tracking")
            state = None

    # 1. Load and merge configuration
    print_step(1, 4, "Loading configuration...")
    config = load_effective_config(recipe_path, verbose=verbose, debug=debug)

    # 2. Extract the first app (for now we only process one app per recipe)
    print_step(2, 4, "Discovering version...")
    apps = config.get("apps", [])
    if not apps:
        raise ValueError(f"No apps defined in recipe: {recipe_path}")

    app = apps[0]
    app_name = app.get("name", "Unknown")
    app_id = app.get("id", "unknown-id")

    # 3. Get the discovery strategy name
    source = app.get("source", {})
    strategy_name = source.get("strategy")
    if not strategy_name:
        raise ValueError(f"No 'source.strategy' defined for app: {app_name}")

    # 4. Get the strategy implementation
    # Import strategies to ensure they're registered
    import notapkgtool.discovery.api_github  # noqa: F401
    import notapkgtool.discovery.api_json  # noqa: F401
    import notapkgtool.discovery.url_download  # noqa: F401
    import notapkgtool.discovery.web_scrape  # noqa: F401

    strategy = get_strategy(strategy_name)

    # Get cache for this recipe from state
    cache = None
    if state and app_id:
        cache = state.get("apps", {}).get(app_id)
        if cache:
            print_verbose("STATE", f"Using cache for {app_id}")
            if cache.get("known_version"):
                print_verbose(
                    "STATE", f"  Cached version: {cache.get('known_version')}"
                )
            if cache.get("etag"):
                print_verbose("STATE", f"  Cached ETag: {cache.get('etag')}")

    # 5. Run discovery: version-first or file-first path
    print_step(3, 4, "Discovering version...")

    # Check if strategy supports version-first (has get_version_info method)
    download_url = None  # Track actual download URL for state file
    if hasattr(strategy, "get_version_info"):
        # VERSION-FIRST PATH (url_regex, github_release, http_json)
        # Get version without downloading
        version_info = strategy.get_version_info(app, verbose=verbose, debug=debug)
        download_url = version_info.download_url  # Save for state file

        print_verbose("DISCOVERY", f"Version discovered: {version_info.version}")

        # Check if we can use cached file (version match + file exists)
        if cache and cache.get("known_version") == version_info.version:
            # Derive file path from URL using same logic as download_file
            file_path = derive_file_path_from_url(version_info.download_url, output_dir)

            if file_path.exists():
                # Fast path: version unchanged, file exists, skip download!
                print_verbose(
                    "CACHE",
                    f"Version {version_info.version} unchanged, using cached file",
                )
                print_step(4, 4, "Using cached file...")
                sha256 = cache.get("sha256")
                discovered_version = DiscoveredVersion(
                    version_info.version, version_info.source
                )
                headers = {}  # No download occurred, no headers
            else:
                # File was deleted, re-download
                print_verbose(
                    "WARNING",
                    f"Cached file {file_path} not found, re-downloading",
                )
                print_step(4, 4, "Downloading installer...")
                file_path, sha256, headers = download_file(
                    version_info.download_url,
                    output_dir,
                    verbose=verbose,
                    debug=debug,
                )
                discovered_version = DiscoveredVersion(
                    version_info.version, version_info.source
                )
        else:
            # Version changed or no cache, download new version
            if cache:
                print_verbose(
                    "DISCOVERY",
                    f"Version changed: {cache.get('known_version')} → {version_info.version}",
                )
            print_step(4, 4, "Downloading installer...")
            file_path, sha256, headers = download_file(
                version_info.download_url,
                output_dir,
                verbose=verbose,
                debug=debug,
            )
            discovered_version = DiscoveredVersion(
                version_info.version, version_info.source
            )
    else:
        # FILE-FIRST PATH (http_static only)
        # Must download to extract version
        print_step(4, 4, "Downloading installer...")
        discovered_version, file_path, sha256, headers = strategy.discover_version(
            app, output_dir, cache=cache, verbose=verbose, debug=debug
        )
        download_url = str(app.get("source", {}).get("url", ""))  # Use source.url

    # Update state with discovered information
    if state and app_id and state_file:
        from datetime import UTC, datetime

        if "apps" not in state:
            state["apps"] = {}

        # Extract ETag and Last-Modified from headers for next run
        etag = headers.get("ETag")
        last_modified = headers.get("Last-Modified")

        if etag:
            print_verbose("STATE", f"Saving ETag for next run: {etag}")
        if last_modified:
            print_verbose(
                "STATE", f"Saving Last-Modified for next run: {last_modified}"
            )

        # Build cache entry with new schema v2
        cache_entry = {
            "url": download_url
            or "",  # Actual download URL (from version_info or source.url)
            "etag": etag if etag else None,  # Only useful for http_static
            "last_modified": (
                last_modified if last_modified else None
            ),  # Only useful for http_static
            "sha256": sha256,
        }

        # Optional fields
        if discovered_version.version:
            cache_entry["known_version"] = discovered_version.version
        if strategy_name:
            cache_entry["strategy"] = strategy_name

        state["apps"][app_id] = cache_entry

        state["metadata"] = {
            "napt_version": __version__,
            "last_updated": datetime.now(UTC).isoformat(),
            "schema_version": "2",
        }

        try:
            save_state(state, state_file)
            print_verbose("STATE", f"Updated state file: {state_file}")
        except Exception as err:
            print_verbose("STATE", f"Warning: Failed to save state: {err}")

    # 6. Return results
    return {
        "app_name": app_name,
        "app_id": app_id,
        "strategy": strategy_name,
        "version": discovered_version.version,
        "version_source": discovered_version.source,
        "file_path": file_path,
        "sha256": sha256,
        "status": "success",
    }
