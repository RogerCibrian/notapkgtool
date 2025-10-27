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
check_recipe : function
    Validate a recipe by downloading and extracting version information.
    This is the entry point for the 'napt check' command.

Future functions:
    build_package : Build a PSADT package from a validated recipe
    upload_package : Upload a built package to Microsoft Intune
    sync_recipe : Full workflow (check -> build -> upload)

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
    from notapkgtool.core import check_recipe

    result = check_recipe(
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


def check_recipe(recipe_path: Path, output_dir: Path) -> dict[str, Any]:
    """
    Validate a recipe by loading config, discovering version, and downloading.

    This is the main entry point for the 'napt check' command. It orchestrates
    the entire validation flow without uploading or packaging.

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
    Basic validation:

        >>> from pathlib import Path
        >>> result = check_recipe(
        ...     Path("recipes/Google/chrome.yaml"),
        ...     Path("./downloads")
        ... )
        >>> print(result['version'])
        141.0.7390.123

    Handling errors:

        >>> try:
        ...     result = check_recipe(Path("invalid.yaml"), Path("."))
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
    # 1. Load and merge configuration
    config = load_effective_config(recipe_path)

    # 2. Extract the first app (for now we only process one app per recipe)
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
    # Import http_static to ensure it's registered
    import notapkgtool.discovery.http_static  # noqa: F401

    strategy = get_strategy(strategy_name)

    # 5. Run discovery: download and extract version
    discovered_version, file_path, sha256 = strategy.discover_version(app, output_dir)

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
