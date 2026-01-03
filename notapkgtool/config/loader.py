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

"""Configuration loading and merging for NAPT.

This module implements a sophisticated three-layer configuration system that
allows organization-wide defaults to be overridden by vendor-specific settings
and finally by recipe-specific configuration. This design promotes DRY
(Don't Repeat Yourself) principles and makes recipes easier to maintain.

Configuration Layers:
    1. **Organization defaults** (defaults/org.yaml)
       - Base configuration for all apps
       - Defines PSADT settings, update policies, deployment waves, etc.
       - Required if a defaults directory is found

    2. **Vendor defaults** (defaults/vendors/<Vendor>.yaml)
       - Vendor-specific overrides (e.g., Google-specific settings)
       - Optional; only loaded if vendor is detected
       - Overrides organization defaults

    3. **Recipe configuration** (recipes/<Vendor>/<app>.yaml)
       - App-specific configuration
       - Always required; defines the app itself
       - Overrides vendor and organization defaults

Merge Behavior:
    The loader performs deep merging with "last wins" semantics:

    - **Dicts**: Recursively merged (keys from overlay override base)
    - **Lists**: Completely replaced (NOT appended/extended)
    - **Scalars**: Overwritten (strings, numbers, booleans)

Path Resolution:
    Relative paths in configuration are resolved against the RECIPE FILE location,
    making recipes relocatable and portable. Currently resolved paths:

    - defaults.psadt.brand_pack.path

Dynamic Injection:
    Some fields are injected at load time:

    - defaults.psadt.app_vars.AppScriptDate: Today's date (YYYY-MM-DD)

Error Handling:
    - ConfigError: Recipe file doesn't exist, YAML parse errors, empty files,
        or invalid structure
    - All errors are chained with "from err" for better debugging

Example:
    Basic usage:
        ```python
        from pathlib import Path
        from notapkgtool.config import load_effective_config

        cfg = load_effective_config(Path("recipes/Google/chrome.yaml"))
        print(cfg["apps"][0]["name"])  # Output: Google Chrome
        ```

    Access merged defaults:
        ```python
        psadt_release = cfg["defaults"]["psadt"]["release"]
        print(psadt_release)  # Output: latest
        ```

    Override vendor detection:
        ```python
        cfg = load_effective_config(
            Path("recipes/Google/chrome.yaml"),
            vendor="CustomVendor"
        )
        ```

Note:
    - The loader walks upward from the recipe to find defaults/org.yaml
    - Vendor is detected from directory name (recipes/Google/) or recipe content
    - Paths are resolved relative to the recipe, not the working directory
    - Dynamic fields are best-effort (warnings on failure, not errors)

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from notapkgtool.exceptions import ConfigError

# -------------------------------
# Data types
# -------------------------------


@dataclass(frozen=True)
class LoadContext:
    """Metadata describing how the config was resolved.
    Useful for debugging and logging.
    """

    recipe_path: Path
    defaults_root: Path | None
    vendor_name: str | None
    org_defaults_path: Path | None
    vendor_defaults_path: Path | None


# -------------------------------
# YAML helpers
# -------------------------------


def _load_yaml_file(p: Path) -> Any:
    """Load a YAML file and return the parsed Python object.

    Raises:
        ConfigError: When file does not exist, invalid YAML (parse error),
            or empty files.

    """
    if not p.exists():
        raise ConfigError(f"file not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as err:
        raise ConfigError(f"Error parsing YAML: {p}: {err}") from err
    if data is None:
        raise ConfigError(f"YAML file is empty: {p}")
    return data


# -------------------------------
# Merge logic
# -------------------------------


def _deep_merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two dicts with "overlay wins".

    Rules:
      - dict + dict -> deep merge
      - list + list -> overlay REPLACES base (not concatenated)
      - everything else -> overlay overwrites base

    This function does not mutate inputs; returns a new dict.
    """
    result: dict[str, Any] = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dicts(result[k], v)
        else:
            # Replace lists and scalars entirely
            result[k] = v
    return result


# -------------------------------
# Defaults discovery
# -------------------------------


def _find_defaults_root(start_dir: Path) -> Path | None:
    """Walk upward from 'start_dir' looking for a 'defaults/org.yaml'.
    Returns the directory containing 'defaults' or None if not found.
    """
    for parent in [start_dir] + list(start_dir.parents):
        candidate = parent / "defaults" / "org.yaml"
        if candidate.exists():
            return parent / "defaults"
    return None


def _detect_vendor(recipe_path: Path, recipe_obj: dict[str, Any]) -> str | None:
    """Determine the vendor name for this recipe.

    Priority:
      1) Folder name under 'recipes/' (e.g., recipes/Google/chrome.yaml -> Google)
      2) recipe.apps[0].psadt.app_vars.AppVendor (if present)
      3) None if not found
    """
    # Try directory name one level up from the recipe file
    parent_name = recipe_path.parent.name or None

    # Try reading from the recipe content
    vendor_from_recipe: str | None = None
    try:
        apps = recipe_obj.get("apps", [])
        if apps and isinstance(apps[0], dict):
            psadt = apps[0].get("psadt", {})
            app_vars = psadt.get("app_vars", {})
            v = app_vars.get("AppVendor")
            if isinstance(v, str) and v.strip():
                vendor_from_recipe = v
    except Exception:
        vendor_from_recipe = None

    # Prefer folder naming if it exists; else fallback to recipe
    return parent_name or vendor_from_recipe


# -------------------------------
# Path resolution
# -------------------------------


def _resolve_known_paths(
    cfg: dict[str, Any], recipe_dir: Path, defaults_root: Path | None = None
) -> None:
    """Resolve relative path fields inside the merged config.

    We keep this explicit and conservative to avoid unexpected rewrites.
    Currently handled:
      - cfg["defaults"]["psadt"]["brand_pack"]["path"]

    Brand pack paths are resolved relative to defaults_root (if available),
    otherwise relative to recipe_dir as fallback.
    Modifies cfg in place.
    """
    try:
        brand_pack = cfg["defaults"]["psadt"]["brand_pack"]
        raw_path = brand_pack.get("path")
        if isinstance(raw_path, str) and raw_path:
            p = Path(raw_path)
            # Resolve only if the path is relative
            if not p.is_absolute():
                # Resolve relative to defaults_root if available, else recipe_dir
                if defaults_root:
                    brand_pack["path"] = str((defaults_root / p).resolve())
                else:
                    brand_pack["path"] = str((recipe_dir / p).resolve())
    except KeyError:
        # Field missing; nothing to resolve
        pass


# -------------------------------
# Dynamic injection
# -------------------------------


def _inject_dynamic_values(cfg: dict[str, Any]) -> None:
    """Inject dynamic fields that should be set at load/build time.

    Currently:
      - defaults.psadt.app_vars.AppScriptDate = today's date (YYYY-MM-DD)
    """
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        app_vars = (
            cfg.setdefault("defaults", {})
            .setdefault("psadt", {})
            .setdefault("app_vars", {})
        )
        # Do not overwrite if explicitly set in recipe; only set if absent
        app_vars.setdefault("AppScriptDate", today_str)
    except Exception as err:
        # Be defensive but quiet; dynamic injection is best-effort
        from notapkgtool.logging import get_global_logger

        logger = get_global_logger()
        logger.warning("CONFIG", f"Could not inject AppScriptDate: {err}")


# -------------------------------
# Verbose helpers
# -------------------------------


def _print_yaml_content(data: dict[str, Any], debug: bool, indent: int = 0) -> None:
    """Print YAML content in a readable format for debug mode."""
    if not debug:
        return

    import yaml

    # Convert to YAML string and print with indentation
    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    for line in yaml_str.split("\n"):
        if line.strip():  # Skip empty lines
            print(" " * indent + line)


# -------------------------------
# Public API
# -------------------------------


def load_effective_config(
    recipe_path: Path,
    *,
    vendor: str | None = None,
    verbose: bool = False,
    debug: bool = False,
) -> dict[str, Any]:
    """Load and merge the effective configuration for a recipe.

    Steps:
        1. Read recipe YAML
        2. Find defaults root by scanning upwards for 'defaults/org.yaml'
        3. Load org defaults (required if defaults root exists)
        4. Determine vendor (param 'vendor' > folder name > recipe contents)
        5. Load vendor defaults if present
        6. Merge: org -> vendor -> recipe (dicts deep-merge, lists replace)
        7. Resolve known relative paths (relative to the recipe directory)
        8. Inject dynamic fields (AppScriptDate = today if absent)

    Returns:
        A merged configuration dict ready for downstream processors.
        If no defaults were found in the tree, the recipe is returned
        as-is (with path resolution + injection).

    Raises:
        ConfigError: On YAML parse errors, empty files, invalid structure,
            or if the recipe file is missing.

    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    recipe_path = recipe_path.resolve()
    recipe_dir = recipe_path.parent

    logger.verbose("CONFIG", f"Loading recipe: {recipe_path}")

    # 1) Read recipe
    recipe_obj = _load_yaml_file(recipe_path)
    if not isinstance(recipe_obj, dict):
        raise ConfigError(f"top-level YAML must be a mapping (dict): {recipe_path}")

    # 2) Find defaults root
    defaults_root = _find_defaults_root(recipe_dir)
    if defaults_root and verbose:
        logger.verbose("CONFIG", f"Found defaults root: {defaults_root}")

    merged: dict[str, Any] = {}
    layers_merged = 0

    org_defaults_path: Path | None = None
    vendor_name: str | None = vendor

    if defaults_root:
        # 3) Load org defaults
        org_defaults_path = defaults_root / "org.yaml"
        if org_defaults_path.exists():
            logger.verbose(
                "CONFIG",
                f"Loading: {org_defaults_path.relative_to(defaults_root.parent)}",
            )
            org_defaults = _load_yaml_file(org_defaults_path)
            if isinstance(org_defaults, dict):
                if debug:
                    logger.debug("CONFIG", "--- Content from org.yaml ---")
                    _print_yaml_content(org_defaults, debug)
                merged = _deep_merge_dicts(merged, org_defaults)
                layers_merged += 1

        # 4) Determine vendor
        if vendor_name is None:
            vendor_name = _detect_vendor(recipe_path, recipe_obj)

        if vendor_name and verbose:
            logger.verbose("CONFIG", f"Detected vendor: {vendor_name}")

        # 5) Load vendor defaults if present
        if vendor_name:
            candidate = defaults_root / "vendors" / f"{vendor_name}.yaml"
            if candidate.exists():
                logger.verbose(
                    "CONFIG", f"Loading: {candidate.relative_to(defaults_root.parent)}"
                )
                vendor_defaults = _load_yaml_file(candidate)
                if isinstance(vendor_defaults, dict):
                    if debug:
                        logger.debug(
                            "CONFIG", f"--- Content from {vendor_name}.yaml ---"
                        )
                        _print_yaml_content(vendor_defaults, debug)
                    merged = _deep_merge_dicts(merged, vendor_defaults)
                    layers_merged += 1

    # Show recipe content if verbose
    if verbose:
        logger.verbose("CONFIG", f"Loading: {recipe_path.name}")
    if debug:
        logger.debug("CONFIG", f"--- Content from {recipe_path.name} ---")
        _print_yaml_content(recipe_obj, debug)

    # 6) Merge recipe on top
    merged = _deep_merge_dicts(merged, recipe_obj)
    layers_merged += 1

    if verbose:
        logger.verbose("CONFIG", f"Deep merging {layers_merged} layer(s)")
        # Show final config structure
        top_level_keys = list(merged.keys())
        logger.verbose(
            "CONFIG",
            (
                f"Final config has {len(top_level_keys)} top-level keys: "
                f"{', '.join(top_level_keys)}"
            ),
        )
    # Show the complete merged configuration in debug mode
    if debug:
        logger.debug("CONFIG", "--- Final Merged Configuration ---")
        _print_yaml_content(merged, debug)

    # 7) Resolve relative paths (branding paths relative to defaults_root)
    _resolve_known_paths(merged, recipe_dir, defaults_root)

    # 8) Inject dynamic values (e.g., AppScriptDate)
    _inject_dynamic_values(merged)

    # Optionally attach context for debugging (commented out by default)
    # merged["_load_context"] = LoadContext(
    #     recipe_path=recipe_path,
    #     defaults_root=defaults_root,
    #     vendor_name=vendor_name,
    #     org_defaults_path=org_defaults_path,
    #     vendor_defaults_path=vendor_defaults_path,
    # ).__dict__

    return merged
