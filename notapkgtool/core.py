"""
Core orchestration for NAPT.

This module provides high-level orchestration functions that coordinate the
complete workflow for recipe validation, package building, and deployment.

The orchestration follows this pipeline:
  1. Load and merge configuration (org defaults + vendor + recipe)
  2. Dispatch to appropriate discovery strategy
  3. Download installer from source
  4. Extract version information
  5. Generate reports or build packages

Functions
---------
discover_recipe : function
    Discover the latest version and download installer.
    This is the entry point for the 'napt discover' command.

Future functions:
    validate_recipe : Validate recipe syntax without downloading
    build_package : Build a PSADT package from a validated recipe
    upload_package : Upload a built package to Microsoft Intune
    update_recipe : Full workflow (discover -> compare -> build -> upload)

Design Principles
-----------------
- Each function has a single, clear responsibility
- Functions return structured data (dicts) for easy testing and extension
- Error handling uses exceptions; CLI layer formats for user display
- Discovery strategies are dynamically loaded via registry pattern
- Configuration is immutable once loaded

Example
-------
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
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from notapkgtool.config.loader import load_effective_config
from notapkgtool.discovery import get_strategy
from notapkgtool.state import load_state, save_state


def discover_recipe(
    recipe_path: Path,
    output_dir: Path,
    state_file: Path | None = Path("state/versions.json"),
    stateless: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> dict[str, Any]:
    """
    Discover the latest version by loading config and downloading installer.

    This is the main entry point for the 'napt discover' command. It orchestrates
    the entire discovery workflow including version detection and file download.

    The function performs these steps:
      1. Load effective configuration (org + vendor + recipe merged)
      2. Extract the first app from the recipe
      3. Identify the discovery strategy from app config
      4. Import and initialize the strategy (e.g., http_static)
      5. Execute discovery: download installer and extract version
      6. Return structured results for display or further processing

    Parameters
    ----------
    recipe_path : Path
        Path to the recipe YAML file. Must exist and be readable.
        The path is resolved to absolute form.
    output_dir : Path
        Directory to download the installer to. Created if it doesn't exist.
        The downloaded file will be named based on Content-Disposition header
        or URL path.
    state_file : Path, optional
        Path to state file for version tracking and ETag caching.
        Default is "state/versions.json". Set to None to disable.
    stateless : bool, optional
        If True, disable state tracking (no caching, always download).
        Default is False.

    Returns
    -------
    dict[str, Any]
        Results dictionary containing:
        - app_name : str - Application display name
        - app_id : str - Unique identifier for the app
        - strategy : str - Discovery strategy used (e.g., "http_static")
        - version : str - Extracted version string
        - version_source : str - How version was determined (e.g., "msi_product_version_from_file")
        - file_path : Path - Absolute path to downloaded installer
        - sha256 : str - SHA-256 hash of the downloaded file (hex)
        - status : str - Always "success" if no exception raised

    Raises
    ------
    SystemExit
        On YAML parse errors or missing recipe file (handled by config loader).
    ValueError
        On missing or invalid configuration fields:
        - No apps defined in recipe
        - Missing 'source.strategy' field
        - Unknown discovery strategy name
    RuntimeError
        On download failures or version extraction errors.
    FileNotFoundError
        If recipe file doesn't exist (before config loading).

    Examples
    --------
    Basic version discovery:

        >>> from pathlib import Path
        >>> result = discover_recipe(
        ...     Path("recipes/Google/chrome.yaml"),
        ...     Path("./downloads")
        ... )
        >>> print(result['version'])
        141.0.7390.123

    Handling errors:

        >>> try:
        ...     result = discover_recipe(Path("invalid.yaml"), Path("."))
        ... except ValueError as e:
        ...     print(f"Config error: {e}")
        ... except RuntimeError as e:
        ...     print(f"Download error: {e}")

    Notes
    -----
    - Only the first app in a recipe is currently processed
    - The discovery strategy must be registered before calling this function
    - Downloaded files are written atomically (.part then renamed)
    - Progress output goes to stdout via the download module
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
                "metadata": {"napt_version": "0.1.0", "schema_version": "1"},
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
    import notapkgtool.discovery.github_release  # noqa: F401
    import notapkgtool.discovery.http_json  # noqa: F401
    import notapkgtool.discovery.http_static  # noqa: F401
    import notapkgtool.discovery.url_regex  # noqa: F401

    strategy = get_strategy(strategy_name)

    # Get cache for this recipe from state
    cache = None
    if state and app_id:
        cache = state.get("apps", {}).get(app_id)
        if cache:
            print_verbose("STATE", f"Using cache for {app_id}")
            print_verbose("STATE", f"  Cached version: {cache.get('version')}")
            if cache.get("etag"):
                print_verbose("STATE", f"  Cached ETag: {cache.get('etag')}")

    # 5. Run discovery: download and extract version
    print_step(3, 4, "Downloading installer...")
    discovered_version, file_path, sha256, headers = strategy.discover_version(
        app, output_dir, cache=cache, verbose=verbose, debug=debug
    )

    print_step(4, 4, "Extracting version...")

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
            print_verbose("STATE", f"Saving Last-Modified for next run: {last_modified}")

        # Build cache entry with new schema v2
        cache_entry = {
            "url": str(app.get("source", {}).get("url", "")),
            "etag": etag,
            "last_modified": last_modified,
            "sha256": sha256,
        }
        
        # Optional fields
        if discovered_version.version:
            cache_entry["known_version"] = discovered_version.version
        if strategy_name:
            cache_entry["strategy"] = strategy_name
        
        state["apps"][app_id] = cache_entry

        state["metadata"] = {
            "napt_version": "0.1.0",
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
