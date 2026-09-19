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

This module implements a layered configuration system that allows NAPT to
work out of the box while supporting full customization. Each layer wins
over the previous, promoting DRY (Don't Repeat Yourself) principles.

Configuration Layers:
    1. **Code defaults** (napt/config/defaults.py)
       - Built-in defaults that ship with NAPT
       - Always present; ensures NAPT works without any config files
       - Provides sensible defaults for all settings

    2. **Organization defaults** (defaults/org.yaml)
       - Organization-wide settings
       - Optional; only loaded if file exists
       - Customizes settings for your organization

    3. **Vendor defaults** (defaults/vendors/{Vendor}.yaml)
       - Vendor-specific settings (e.g., Google-specific settings)
       - Optional; only loaded if vendor is detected
       - Wins over organization defaults

    4. **Parent recipe** (the file named by the recipe's ``parent`` field)
       - Another recipe merged beneath this one
       - Optional; a parent may not itself declare a parent
       - Wins over vendor defaults

    5. **Recipe configuration** (recipes/{Vendor}/{app}.yaml)
       - App-specific configuration
       - Always required; defines the app itself
       - Wins over all other layers

Merge Behavior:
    The loader performs deep merging with "last wins" semantics:

    - **Dicts**: Recursively merged (keys from overlay win over base)
    - **Lists**: Completely replaced (NOT appended/extended)
    - **Scalars**: Overwritten (strings, numbers, booleans)

Path Resolution:
    Relative paths in configuration are resolved against the RECIPE FILE
    location, making recipes relocatable and portable. A parent's relative
    paths resolve against the child recipe, not the parent file. Currently
    resolved paths:

    - psadt.brand_pack.path
    - intune.logo_path

Dynamic Injection:
    Some fields are injected at load time:

    - psadt.app_vars.AppScriptDate: Today's date (YYYY-MM-DD)

Error Handling:
    - ConfigError: Recipe file doesn't exist, YAML parse errors, empty files,
        invalid structure, a missing parent, or a parent chain
    - All errors are chained with "from err" for better debugging

Note:
    - Code defaults are always applied first (NAPT works without config files)
    - The loader walks upward from the recipe to find defaults/org.yaml
    - Organization and vendor defaults are optional layers
    - Vendor is detected from directory name (recipes/Google/) or recipe content
    - Paths are resolved relative to the recipe, not the working directory
    - Dynamic fields are best-effort (warnings on failure, not errors)

"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from napt.config.defaults import DEFAULT_CONFIG
from napt.exceptions import ConfigError


def _load_yaml_file(p: Path) -> Any:
    """Loads a YAML file and returns the parsed Python object.

    Args:
        p: Path to the YAML file to load.

    Returns:
        The parsed Python object from the YAML file.

    Raises:
        ConfigError: When file does not exist, invalid YAML (parse error), or empty files.
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


def _deep_merge_dicts(
    base: dict[str, Any],
    overlay: dict[str, Any],
    *,
    provenance: dict[str, Any] | None = None,
    layer_name: str = "",
) -> dict[str, Any]:
    """Deep-merges two dicts with "overlay wins" semantics.

    Merge behavior:

    - dict + dict -> deep merge
    - list + list -> overlay REPLACES base (not concatenated)
    - everything else -> overlay overwrites base

    This function does not mutate inputs; returns a new dict.

    Args:
        base: The base dictionary.
        overlay: The overlay dictionary that takes precedence.
        provenance: Optional dict that mirrors the config structure, tracking
            which layer set each value. When provided, each scalar/list key
            is recorded as ``provenance[key] = layer_name``.
        layer_name: Name of the current layer (e.g., ``"code_default"``,
            ``"org_yaml"``, ``"recipe"``). Only used when provenance is set.

    Returns:
        A new dictionary with the merged contents.
    """
    result: dict[str, Any] = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            # Recurse for nested dicts
            sub_prov: dict[str, Any] | None = None
            if provenance is not None:
                sub_prov = provenance.setdefault(k, {})
            result[k] = _deep_merge_dicts(
                result[k], v, provenance=sub_prov, layer_name=layer_name
            )
        else:
            # Replace lists and scalars entirely
            result[k] = v
            if provenance is not None and layer_name:
                provenance[k] = layer_name
    return result


def load_parent(
    recipe_path: Path, recipe_obj: dict[str, Any]
) -> tuple[Path, dict[str, Any]] | None:
    """Loads the parent recipe a recipe declares, if any.

    The ``parent`` field names another recipe file relative to the
    declaring recipe's directory. The parent is merged beneath the
    declaring recipe by [load_effective_config][napt.config.loader.load_effective_config]
    and by ``napt validate``.

    Args:
        recipe_path: Path to the recipe that may declare ``parent``.
        recipe_obj: The parsed recipe dictionary.

    Returns:
        The resolved parent path and its parsed contents, or None when the
            recipe declares no parent.

    Raises:
        ConfigError: When ``parent`` is not a non-empty string, the parent
            file is missing or not a mapping, or the parent itself declares
            a parent (chains are not supported).
    """
    parent_ref = recipe_obj.get("parent")
    if parent_ref is None:
        return None
    if not isinstance(parent_ref, str) or not parent_ref.strip():
        raise ConfigError(f"parent must be a non-empty string: {recipe_path}")

    parent_path = (recipe_path.resolve().parent / parent_ref).resolve()
    if not parent_path.is_file():
        raise ConfigError(
            f"Parent recipe not found: {parent_path} (declared in {recipe_path})"
        )

    parent_obj = _load_yaml_file(parent_path)
    if not isinstance(parent_obj, dict):
        raise ConfigError(f"top-level YAML must be a mapping (dict): {parent_path}")
    if "parent" in parent_obj:
        raise ConfigError(
            f"Parent chains are not supported: {parent_path} declares its own "
            f"parent (used as parent by {recipe_path})"
        )
    return parent_path, parent_obj


def merge_parent(
    recipe_path: Path, recipe_obj: dict[str, Any]
) -> tuple[dict[str, Any], Path | None]:
    """Merges a recipe over its parent without the other configuration layers.

    Used by ``napt validate``, which checks a recipe's own schema rather than
    the fully merged configuration. The recipe's ``parent`` field survives
    the merge so schema validation can see it.

    Args:
        recipe_path: Path to the recipe that may declare ``parent``.
        recipe_obj: The parsed recipe dictionary.

    Returns:
        The merged dictionary and the parent path, or the recipe unchanged
            and None when it declares no parent.

    Raises:
        ConfigError: See [load_parent][napt.config.loader.load_parent].
    """
    loaded = load_parent(recipe_path, recipe_obj)
    if loaded is None:
        return recipe_obj, None
    parent_path, parent_obj = loaded
    return _deep_merge_dicts(parent_obj, recipe_obj), parent_path


def _find_defaults_root(start_dir: Path) -> Path | None:
    """Walks upward from start_dir looking for a defaults/org.yaml file.

    Args:
        start_dir: The directory to start searching from.

    Returns:
        The directory containing defaults/ if found, None otherwise.
    """
    for parent in [start_dir] + list(start_dir.parents):
        candidate = parent / "defaults" / "org.yaml"
        if candidate.exists():
            return parent / "defaults"
    return None


def _detect_vendor(recipe_path: Path, recipe_obj: dict[str, Any]) -> str | None:
    """Determines the vendor name for this recipe.

    Uses the following priority order:

    1. Folder name under recipes/ (e.g., recipes/Google/chrome.yaml -> Google)
    2. recipe.psadt.app_vars.AppVendor (if present)
    3. None if not found

    Args:
        recipe_path: Path to the recipe file.
        recipe_obj: The parsed recipe dictionary.

    Returns:
        The vendor name if detected, None otherwise.
    """
    # Try directory name one level up from the recipe file
    parent_name = recipe_path.parent.name or None

    # Try reading from the recipe content
    vendor_from_recipe: str | None = None
    try:
        psadt = recipe_obj.get("psadt", {})
        if isinstance(psadt, dict):
            app_vars = psadt.get("app_vars", {})
            v = app_vars.get("AppVendor")
            if isinstance(v, str) and v.strip():
                vendor_from_recipe = v
    except Exception:
        vendor_from_recipe = None

    # Prefer folder naming if it exists; else fallback to recipe
    return parent_name or vendor_from_recipe


def _resolve_known_paths(
    cfg: dict[str, Any], recipe_dir: Path, defaults_root: Path | None = None
) -> None:
    """Resolves relative path fields inside the merged config.

    We keep this explicit and conservative to avoid unexpected rewrites.
    Currently handles cfg["psadt"]["brand_pack"]["path"] and
    cfg["intune"]["logo_path"].

    Brand pack paths are resolved relative to defaults_root (if available),
    otherwise relative to recipe_dir as fallback. Logo paths are resolved
    relative to recipe_dir; when no file exists there but one exists
    relative to defaults_root, the defaults_root path is used instead (so
    an org-wide logo set in defaults/org.yaml resolves next to org.yaml).
    Modifies cfg in place.

    Args:
        cfg: The merged configuration dictionary.
        recipe_dir: Directory containing the recipe file.
        defaults_root: Root directory containing defaults/, if found.
    """
    try:
        brand_pack = cfg["psadt"]["brand_pack"]
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

    intune = cfg.get("intune")
    if isinstance(intune, dict):
        raw_logo = intune.get("logo_path")
        if isinstance(raw_logo, str) and raw_logo:
            p = Path(raw_logo)
            if not p.is_absolute():
                resolved = (recipe_dir / p).resolve()
                if not resolved.exists() and defaults_root:
                    org_resolved = (defaults_root / p).resolve()
                    if org_resolved.exists():
                        resolved = org_resolved
                intune["logo_path"] = str(resolved)


def _inject_dynamic_values(
    cfg: dict[str, Any],
    provenance: dict[str, Any] | None = None,
) -> None:
    """Injects dynamic fields that should be set at load/build time.

    Injects the following fields:

    - ``psadt.app_vars.AppScriptDate``: Today's date (YYYY-MM-DD), unless
      explicitly set by a config layer.
    - ``psadt.app_vars.RequireAdmin``: Computed from
      ``intune.run_as_account`` (system -> True, user -> False), unless
      explicitly set by org.yaml, vendor defaults, a parent, or the recipe.

    Args:
        cfg: The configuration dictionary to inject values into.
        provenance: Optional provenance dict tracking which layer set each
            value. Used to detect whether ``RequireAdmin`` was explicitly
            overridden by the user.
    """
    try:
        app_vars = cfg.setdefault("psadt", {}).setdefault("app_vars", {})

        today_str = date.today().strftime("%Y-%m-%d")
        app_vars.setdefault("AppScriptDate", today_str)

        # RequireAdmin: compute from run_as_account unless explicitly set
        # by a user-controlled layer (org_yaml, vendor_yaml, parent, recipe).
        run_as_account = cfg["intune"]["run_as_account"]
        require_admin_source = None
        if provenance is not None:
            require_admin_source = (
                provenance.get("psadt", {}).get("app_vars", {}).get("RequireAdmin")
            )

        user_layers = {"org_yaml", "vendor_yaml", "parent", "recipe"}
        if require_admin_source in user_layers:
            # User explicitly set RequireAdmin — respect their value
            pass
        else:
            # Compute from run_as_account
            app_vars["RequireAdmin"] = run_as_account != "user"
    except Exception as err:
        # Be defensive but quiet; dynamic injection is best-effort
        from napt.logging import get_global_logger

        logger = get_global_logger()
        logger.warning("CONFIG", f"Could not inject dynamic values: {err}")


def _print_yaml_content(data: dict[str, Any], indent: int = 0) -> None:
    """Print YAML content in a readable format for debug mode."""
    import yaml

    from napt.logging import get_global_logger

    logger = get_global_logger()

    # Convert to YAML string and log with indentation
    # The logger.debug() call will only print if debug mode is enabled
    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    for line in yaml_str.split("\n"):
        if line.strip():  # Skip empty lines
            logger.debug("CONFIG", " " * indent + line)


def load_effective_config(
    recipe_path: Path,
    *,
    vendor: str | None = None,
) -> dict[str, Any]:
    """Loads and merges the effective configuration for a recipe.

    Performs the following operations:

    1. Read recipe YAML and its parent recipe, if it declares one
    2. Find defaults root by scanning upwards for defaults/org.yaml
    3. Load org defaults (required if defaults root exists)
    4. Determine vendor (param vendor > folder name > recipe contents)
    5. Load vendor defaults if present
    6. Merge: org -> vendor -> parent -> recipe (dicts deep-merge, lists
       replace)
    7. Resolve known relative paths (relative to the recipe directory)
    8. Inject dynamic fields (AppScriptDate = today if absent)

    The returned dict does not carry the ``parent`` field; the parent's
    contents are already merged in.

    Args:
        recipe_path: Path to the recipe YAML file.
        vendor: Optional vendor name. If not provided, vendor is detected
            from the folder name or recipe contents.

    Returns:
        A merged configuration dict ready for downstream processors. If no defaults
            were found in the tree, the recipe is returned as-is (with path
            resolution and injection).

    Raises:
        ConfigError: On YAML parse errors, empty files, invalid structure, a
            missing recipe or parent file, or a parent chain.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    recipe_path = recipe_path.resolve()
    recipe_dir = recipe_path.parent

    logger.verbose("CONFIG", f"Loading recipe: {recipe_path}")

    # 1) Read recipe and its parent, if any
    recipe_obj = _load_yaml_file(recipe_path)
    if not isinstance(recipe_obj, dict):
        raise ConfigError(f"top-level YAML must be a mapping (dict): {recipe_path}")

    parent_path: Path | None = None
    parent_obj: dict[str, Any] | None = None
    loaded_parent = load_parent(recipe_path, recipe_obj)
    if loaded_parent is not None:
        parent_path, parent_obj = loaded_parent

    # 2) Find defaults root
    defaults_root = _find_defaults_root(recipe_dir)
    if defaults_root:
        logger.verbose("CONFIG", f"Found defaults root: {defaults_root}")

    # Start with code defaults (always present baseline)
    merged = copy.deepcopy(DEFAULT_CONFIG)
    provenance: dict[str, Any] = {}
    layers_merged = 1  # Code defaults count as first layer

    # Initialize provenance: all DEFAULT_CONFIG keys start as "code_default"
    def _init_provenance(cfg: dict[str, Any], prov: dict[str, Any]) -> None:
        for k, v in cfg.items():
            if isinstance(v, dict):
                sub = prov.setdefault(k, {})
                _init_provenance(v, sub)
            else:
                prov[k] = "code_default"

    _init_provenance(DEFAULT_CONFIG, provenance)

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
                logger.debug("CONFIG", "--- Content from org.yaml ---")
                _print_yaml_content(org_defaults)
                merged = _deep_merge_dicts(
                    merged,
                    org_defaults,
                    provenance=provenance,
                    layer_name="org_yaml",
                )
                layers_merged += 1

        # 4) Determine vendor
        if vendor_name is None:
            vendor_name = _detect_vendor(recipe_path, recipe_obj)

        if vendor_name:
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
                    logger.debug("CONFIG", f"--- Content from {vendor_name}.yaml ---")
                    _print_yaml_content(vendor_defaults)
                    merged = _deep_merge_dicts(
                        merged,
                        vendor_defaults,
                        provenance=provenance,
                        layer_name="vendor_yaml",
                    )
                    layers_merged += 1

    # 6) Merge the parent beneath the recipe, then the recipe on top
    if parent_path is not None and parent_obj is not None:
        logger.verbose("CONFIG", f"Loading parent: {parent_path}")
        logger.debug("CONFIG", f"--- Content from {parent_path.name} ---")
        _print_yaml_content(parent_obj)
        merged = _deep_merge_dicts(
            merged, parent_obj, provenance=provenance, layer_name="parent"
        )
        layers_merged += 1

    # Show recipe content
    logger.verbose("CONFIG", f"Loading: {recipe_path.name}")
    logger.debug("CONFIG", f"--- Content from {recipe_path.name} ---")
    _print_yaml_content(recipe_obj)

    merged = _deep_merge_dicts(
        merged, recipe_obj, provenance=provenance, layer_name="recipe"
    )
    layers_merged += 1

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
    logger.debug("CONFIG", "--- Final Merged Configuration ---")
    _print_yaml_content(merged)

    # 7) Resolve relative paths (branding paths relative to defaults_root)
    _resolve_known_paths(merged, recipe_dir, defaults_root)

    # 8) Inject dynamic values (e.g., AppScriptDate, RequireAdmin)
    _inject_dynamic_values(merged, provenance)

    # Store provenance for downstream consumers
    merged["_provenance"] = provenance

    # 9) Validate the merged config (errors raise, warnings are logged)
    from napt.validation import validate_config

    result = validate_config(merged, recipe_path=str(recipe_path))
    if result.errors:
        where = f" (parent: {parent_path})" if parent_path is not None else ""
        raise ConfigError(f"Invalid configuration{where}: {'; '.join(result.errors)}")
    for warning in result.warnings:
        logger.warning("CONFIG", warning)

    # The parent's contents are merged in; the pointer itself is not config.
    merged.pop("parent", None)
    provenance.pop("parent", None)

    return merged
