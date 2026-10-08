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
over the previous one.

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
       - Optional; loaded when the vendor is detected and defaults/org.yaml
         exists
       - Wins over organization defaults

    4. **Parent recipe** (the file named by the recipe's ``parent`` field)
       - Another recipe merged beneath this one
       - Optional; a parent may not itself declare a parent
       - Wins over vendor defaults
       - A parent under ``upstream/`` is foreign: it must match the hash
         ``upstream.yaml`` records, and only app-owned keys are merged
         (see [napt.upstream.vendored][])

    5. **Recipe configuration** (recipes/{Vendor}/{app}.yaml)
       - App-specific configuration
       - Always required; defines the app itself
       - Wins over all other layers

Merge Behavior:
    The loader performs deep merging with "last wins" semantics:

    - **Dicts**: Recursively merged (keys from overlay win over base)
    - **Lists**: Completely replaced (NOT appended/extended)
    - **Scalars**: Overwritten (strings, numbers, booleans)
    - **secrets**: Taken from defaults/org.yaml alone; a vendor file,
      parent, or recipe that declares one fails validation

Path Resolution:
    Relative paths in two fields are resolved after merging:

    - psadt.brand_pack.path resolves against defaults/ (the recipe directory
      when no defaults/org.yaml is found).
    - intune.logo_path resolves against the recipe directory, then defaults/
      if no file is there.

Dynamic Injection:
    Some fields are injected at load time, with the provenance layer
    ``computed``:

    - psadt.app_vars.AppScriptDate: Today's date (YYYY-MM-DD)
    - psadt.app_vars.RequireAdmin: true unless intune.run_as_account is user;
      a value set in any config layer wins

Error Handling:
    - ConfigError: A missing recipe or parent file, a YAML parse error, a
        file whose top level is not a mapping (in any layer), a parent
        chain, a foreign parent that is untracked or edited, or a vendored
        copy run directly
    - All errors are chained with "from err" for better debugging

Note:
    - Code defaults are always applied first (NAPT works without config files)
    - The loader walks upward from the recipe to find defaults/org.yaml
    - Organization and vendor defaults are optional; vendor defaults need
      defaults/org.yaml to be found
    - The vendor is the name of the recipe's directory (recipes/Google/)

"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from napt.config.defaults import DEFAULT_CONFIG
from napt.exceptions import ConfigError
from napt.logging import get_global_logger
from napt.upstream.vendored import (
    filter_foreign_parent,
    is_vendored_recipe,
    tracked_location,
    vendored_location,
    verify_vendored,
)


def _read_yaml_bytes(path: Path, what: str) -> bytes:
    """Reads a configuration file's bytes.

    Args:
        path: Path to the YAML file to read.
        what: The file's role in the error message ("Recipe", "org.yaml").

    Returns:
        The file's content, untouched.

    Raises:
        ConfigError: When the file does not exist or cannot be read.
    """
    if not path.exists():
        raise ConfigError(f"{what} not found: {path}")
    try:
        return path.read_bytes()
    except OSError as err:
        raise ConfigError(f"Cannot read {path}: {err}") from err


def _parse_yaml_mapping(data: bytes, path: Path) -> dict[str, Any]:
    """Parses configuration bytes that must hold a mapping at their top level.

    Args:
        data: The file's bytes, from
            [_read_yaml_bytes][napt.config.loader._read_yaml_bytes].
        path: Where the bytes came from, for error messages.

    Returns:
        The parsed mapping.

    Raises:
        ConfigError: When the bytes are not UTF-8, are not valid YAML, or
            their top level is not a mapping.
    """
    try:
        parsed = yaml.safe_load(data.decode("utf-8"))
    except yaml.YAMLError as err:
        raise ConfigError(f"Error parsing YAML: {path}: {err}") from err
    except UnicodeDecodeError as err:
        raise ConfigError(
            f"Cannot read {path}: the file is not UTF-8 (a file saved by "
            f"PowerShell's Out-File is often UTF-16). {err}"
        ) from err
    if parsed is None:
        raise ConfigError(f"YAML file is empty: {path}")
    if not isinstance(parsed, dict):
        raise ConfigError(f"top-level YAML must be a mapping (dict): {path}")
    return parsed


def _load_yaml_mapping(path: Path, what: str) -> dict[str, Any]:
    """Loads a YAML file that must hold a mapping at its top level.

    Every configuration layer goes through here, so a missing file, a
    parse error, or a file holding a list or a scalar is reported the same
    way whichever layer it is.

    Args:
        path: Path to the YAML file to load.
        what: The file's role in the error message ("Recipe", "org.yaml").

    Returns:
        The parsed mapping.

    Raises:
        ConfigError: When the file does not exist, is not UTF-8, is not
            valid YAML, or its top level is not a mapping.
    """
    return _parse_yaml_mapping(_read_yaml_bytes(path, what), path)


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
                # An earlier layer may have recorded this whole section as
                # one entry (its layer name). Expand that to one entry per
                # key so this layer's keys can be recorded beside them.
                existing = provenance.get(k)
                if isinstance(existing, dict):
                    sub_prov = existing
                else:
                    sub_prov = {key: existing for key in result[k]} if existing else {}
                provenance[k] = sub_prov
            result[k] = _deep_merge_dicts(
                result[k], v, provenance=sub_prov, layer_name=layer_name
            )
        else:
            # Replace lists and scalars entirely
            result[k] = v
            if provenance is not None and layer_name:
                provenance[k] = layer_name
    return result


@dataclass(frozen=True)
class LoadedParent:
    """A parent recipe as the loader hands it to the merge.

    Attributes:
        path: The resolved parent file.
        data: Its parsed contents, filtered to the allowed keys when the
            parent is foreign.
        dropped: The dotted names of the keys the filter removed; empty
            for a local parent.
    """

    path: Path
    data: dict[str, Any]
    dropped: tuple[str, ...] = ()


def load_parent(recipe_path: Path, recipe_obj: dict[str, Any]) -> LoadedParent | None:
    """Loads the parent recipe a recipe declares, if any.

    The ``parent`` field names another recipe file relative to the
    declaring recipe's directory. The parent is merged beneath the
    declaring recipe by
    [merge_config_layers][napt.config.loader.merge_config_layers].

    A parent under ``upstream/`` is foreign: its bytes must match the hash
    recorded in ``upstream.yaml``, and only the keys in
    [ALLOWED_PARENT_KEYS][napt.upstream.vendored.ALLOWED_PARENT_KEYS] are
    kept. See [napt.upstream.vendored][] for what makes a parent foreign.

    Args:
        recipe_path: Path to the recipe that may declare ``parent``.
        recipe_obj: The parsed recipe dictionary.

    Returns:
        The parent, or None when the recipe declares no parent.

    Raises:
        ConfigError: When ``parent`` is not a non-empty string, the parent
            file is missing or not a mapping, the parent itself declares a
            parent (chains are not supported), or a foreign parent is not
            tracked in ``upstream.yaml`` or does not match its recorded
            hash.
    """
    parent_ref = recipe_obj.get("parent")
    if parent_ref is None:
        return None
    if not isinstance(parent_ref, str) or not parent_ref.strip():
        raise ConfigError(f"parent must be a non-empty string: {recipe_path}")

    recipe_dir = recipe_path.resolve().parent
    parent_path = (recipe_dir / parent_ref).resolve()
    # Foreign by the reference as written, or by where the file really is.
    location = vendored_location(recipe_dir, parent_ref) or tracked_location(
        parent_path
    )

    data = _read_yaml_bytes(parent_path, "Parent recipe")
    if location is not None:
        verify_vendored(parent_path, location, data)
    parent_obj = _parse_yaml_mapping(data, parent_path)
    if "parent" in parent_obj:
        raise ConfigError(
            f"Parent chains are not supported: {parent_path} declares its own "
            f"parent (used as parent by {recipe_path})"
        )
    if location is None:
        return LoadedParent(path=parent_path, data=parent_obj)
    kept, dropped = filter_foreign_parent(parent_obj)
    return LoadedParent(path=parent_path, data=kept, dropped=dropped)


def collect_recipe_paths(recipes: Path) -> list[Path]:
    """Collects recipe file paths from a file or directory.

    Args:
        recipes: A recipe YAML file, or a directory scanned recursively
            for ``*.yaml`` / ``*.yml`` files.

    Returns:
        Sorted recipe file paths.

    Raises:
        ConfigError: If the path does not exist or contains no recipes.
    """
    if recipes.is_file():
        return [recipes]
    if recipes.is_dir():
        found = sorted(
            path for pattern in ("*.yaml", "*.yml") for path in recipes.rglob(pattern)
        )
        if not found:
            raise ConfigError(f"No recipe files found under {recipes}")
        return found
    raise ConfigError(f"Recipe path not found: {recipes}")


def resolve_state_dir(recipes: Path) -> Path:
    """Resolves the configured state directory for a run over recipes.

    ``directories.state`` is org policy (consistent across a project),
    so the first recipe's effective configuration determines it for a
    fleet-wide run. The load is quiet: this reads one setting and reports
    nothing about the recipe, so the command's own output (for example
    ``napt status --format json``) is not preceded by recipe diagnostics.

    Args:
        recipes: A recipe YAML file, or a directory scanned recursively.

    Returns:
        The configured state directory.

    Raises:
        ConfigError: If the recipes path is invalid or the first recipe
            cannot be loaded.

    """
    first = collect_recipe_paths(recipes)[0]
    config = load_effective_config(first, quiet=True)
    return Path(config["directories"]["state"])


def register_recipe_id(sources: dict[str, Path], app_id: str, path: Path) -> str | None:
    """Records which file declares a recipe id, reporting a second claimant.

    ``napt validate`` and ``napt promote`` both scan a directory and must
    agree on what a duplicate id is; this is the one place that decides.

    Args:
        sources: The ids seen so far, mapped to the file that declared each.
            A new id is recorded here.
        app_id: The id the file declares.
        path: The file declaring it.

    Returns:
        None when the id is new; otherwise the error message, naming both
            files and the usual cause, with the first declaration kept.
    """
    first = sources.get(app_id)
    if first is None:
        sources[app_id] = path
        return None
    return (
        f"Recipe id '{app_id}' is declared by both {first} and {path}. Give "
        f"each recipe its own id, or move a parent recipe that shares its "
        f"child's id out of the directory being scanned."
    )


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


def _detect_vendor(recipe_path: Path) -> str | None:
    """Names the vendor whose defaults file applies to a recipe.

    The vendor is the recipe's directory (recipes/Google/chrome.yaml is
    Google's), matched against defaults/vendors/<Vendor>.yaml.

    Args:
        recipe_path: Path to the recipe file.

    Returns:
        The directory name, or None for a recipe at a filesystem root.
    """
    return recipe_path.parent.name or None


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
    # A section or field of the wrong shape is left for validation to
    # report; there is nothing to resolve in it.
    psadt = cfg.get("psadt")
    brand_pack = psadt.get("brand_pack") if isinstance(psadt, dict) else None
    if isinstance(brand_pack, dict):
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


def _inject_dynamic_values(cfg: dict[str, Any], provenance: dict[str, Any]) -> None:
    """Injects the fields that are set at load time, labelled ``computed``.

    - ``psadt.app_vars.AppScriptDate``: Today's date (YYYY-MM-DD), unless a
      config layer set it.
    - ``psadt.app_vars.RequireAdmin``: Computed from
      ``intune.run_as_account`` (system -> True, user -> False), unless a
      config layer set it; a layer's value always wins over the computed
      one.

    A section that is missing, empty, or the wrong shape is left alone;
    validation reports it, and there is nothing to inject into.

    Args:
        cfg: The merged configuration, mutated in place.
        provenance: The layer that set each value, mirroring ``cfg``;
            injected values are recorded here as ``computed``.
    """
    psadt = cfg.get("psadt")
    intune = cfg.get("intune")
    if not isinstance(psadt, dict) or not isinstance(intune, dict):
        return
    app_vars = psadt.get("app_vars")
    if not isinstance(app_vars, dict) or "run_as_account" not in intune:
        return
    sources = provenance.setdefault("psadt", {}).setdefault("app_vars", {})

    if "AppScriptDate" not in app_vars:
        app_vars["AppScriptDate"] = date.today().strftime("%Y-%m-%d")
        sources["AppScriptDate"] = "computed"

    # A RequireAdmin written in any layer wins; only a value no layer set is
    # computed from the install scope.
    if sources.get("RequireAdmin") in (None, "code_default", "computed"):
        app_vars["RequireAdmin"] = intune["run_as_account"] != "user"
        sources["RequireAdmin"] = "computed"


def _print_yaml_content(data: dict[str, Any], indent: int = 0) -> None:
    """Logs a configuration layer as YAML at debug level.

    Serializing a layer costs more than the rest of a load, so nothing is
    built unless debug lines would print.
    """
    logger = get_global_logger()
    if not logger.debug_enabled:
        return

    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    for line in yaml_str.split("\n"):
        if line.strip():  # Skip empty lines
            logger.debug("CONFIG", " " * indent + line)


def merge_effective_config(
    recipe_path: Path, *, quiet: bool = False
) -> tuple[dict[str, Any], Path | None]:
    """Merges the configuration layers for a recipe without validating them.

    Reads the recipe and the parent it declares, then merges them with
    [merge_config_layers][napt.config.loader.merge_config_layers]. When
    a foreign parent set keys the allow list dropped, one always-visible
    line names them, because the effective configuration differs from
    what the vendored file says.

    Args:
        recipe_path: Path to the recipe YAML file.
        quiet: Skip the dropped-keys line, for a caller that reads one
            setting and reports nothing about the recipe.

    Returns:
        The merged configuration and the parent recipe's path (None when
            the recipe declares no parent).

    Raises:
        ConfigError: On a missing recipe or parent file, a YAML parse error,
            a layer whose top level is not a mapping, a parent chain, a
            recipe that is itself a vendored copy under ``upstream/``, or a
            foreign parent that fails its hash check.
    """
    logger = get_global_logger()
    if is_vendored_recipe(recipe_path):
        raise ConfigError(
            f"{recipe_path} is a vendored copy under upstream/. Run the "
            f"override in recipes/ that names it as parent instead."
        )
    recipe_path = recipe_path.resolve()
    logger.verbose("CONFIG", f"Loading recipe: {recipe_path}")

    recipe_obj = _load_yaml_mapping(recipe_path, "Recipe")
    parent = load_parent(recipe_path, recipe_obj)
    if parent is not None and parent.dropped and not quiet:
        logger.info(
            "CONFIG",
            "Ignoring from parent (not allowed from upstream recipes): "
            + ", ".join(parent.dropped),
        )
    merged = merge_config_layers(recipe_path, recipe_obj, parent)
    return merged, parent.path if parent is not None else None


def merge_config_layers(
    recipe_path: Path,
    recipe_obj: dict[str, Any],
    parent: LoadedParent | None = None,
) -> dict[str, Any]:
    """Merges the configuration layers for an already-parsed recipe.

    The recipe and its parent arrive as objects, so a recipe that is not on
    disk yet can be merged exactly as it will be once written. Performs the
    following operations:

    1. Find defaults root by scanning upwards from the recipe's directory
       for defaults/org.yaml
    2. Load org defaults from defaults/org.yaml
    3. Load the vendor defaults named after the recipe's directory, if present
    4. Merge: org -> vendor -> parent -> recipe (dicts deep-merge, lists
       replace); the ``secrets`` section is taken from org.yaml alone
    5. Resolve known relative paths (see Path resolution in the module
       docstring)
    6. Inject dynamic fields (AppScriptDate = today if absent)

    The merged dict carries the recipe's ``parent`` field and a
    ``_provenance`` entry naming the layer that set each value, so
    validation can check both.

    Args:
        recipe_path: Where the recipe lives or will live; its directory
            names the vendor and anchors relative paths and the search for
            defaults/org.yaml.
        recipe_obj: The parsed recipe.
        parent: The parent as [load_parent][napt.config.loader.load_parent]
            returns it, already filtered when foreign, or None when the
            recipe declares no parent.

    Returns:
        The merged configuration.

    Raises:
        ConfigError: On a missing or unreadable org.yaml or vendor file, or
            one whose top level is not a mapping.
    """
    logger = get_global_logger()
    recipe_path = recipe_path.resolve()
    recipe_dir = recipe_path.parent

    parent_path: Path | None = None
    parent_obj: dict[str, Any] | None = None
    if parent is not None:
        parent_path, parent_obj = parent.path, parent.data

    # 1) Find defaults root
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

    # The secrets section as org.yaml wrote it. Restored over the merge
    # below so no other layer can declare a secret or widen its hosts.
    org_secrets: Any = {}

    if defaults_root:
        # 2) Load org defaults; _find_defaults_root found this file.
        org_defaults_path = defaults_root / "org.yaml"
        logger.verbose(
            "CONFIG",
            f"Loading: {org_defaults_path.relative_to(defaults_root.parent)}",
        )
        org_defaults = _load_yaml_mapping(org_defaults_path, "org.yaml")
        logger.debug("CONFIG", "--- Content from org.yaml ---")
        _print_yaml_content(org_defaults)
        org_secrets = org_defaults.get("secrets", {})
        merged = _deep_merge_dicts(
            merged,
            org_defaults,
            provenance=provenance,
            layer_name="org_yaml",
        )
        layers_merged += 1

        # 3) Load vendor defaults if present
        vendor_name = _detect_vendor(recipe_path)
        if vendor_name:
            logger.verbose("CONFIG", f"Detected vendor: {vendor_name}")
            candidate = defaults_root / "vendors" / f"{vendor_name}.yaml"
            if candidate.exists():
                logger.verbose(
                    "CONFIG", f"Loading: {candidate.relative_to(defaults_root.parent)}"
                )
                vendor_defaults = _load_yaml_mapping(candidate, "Vendor defaults")
                logger.debug("CONFIG", f"--- Content from {vendor_name}.yaml ---")
                _print_yaml_content(vendor_defaults)
                merged = _deep_merge_dicts(
                    merged,
                    vendor_defaults,
                    provenance=provenance,
                    layer_name="vendor_yaml",
                )
                layers_merged += 1

    # 4) Merge the parent beneath the recipe, then the recipe on top
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

    # Secrets are org policy and nothing else may touch them. Provenance
    # still records what the other layers tried, and validation reports it.
    merged["secrets"] = copy.deepcopy(org_secrets)

    logger.verbose("CONFIG", f"Deep merging {layers_merged} layer(s)")
    # Show final config structure
    # A key that is not a string is reported by validation, not here.
    top_level_keys = [str(key) for key in merged]
    logger.verbose(
        "CONFIG",
        (
            f"Final config has {len(top_level_keys)} top-level keys: "
            f"{', '.join(top_level_keys)}"
        ),
    )
    # 5) Resolve relative paths (branding paths relative to defaults_root)
    _resolve_known_paths(merged, recipe_dir, defaults_root)

    # 6) Inject dynamic values (e.g., AppScriptDate, RequireAdmin)
    _inject_dynamic_values(merged, provenance)

    # The configuration the command runs with, in debug mode
    logger.debug("CONFIG", "--- Final Merged Configuration ---")
    _print_yaml_content(merged)

    # Store provenance for downstream consumers
    merged["_provenance"] = provenance
    return merged


def load_effective_config(recipe_path: Path, *, quiet: bool = False) -> dict[str, Any]:
    """Loads, merges, and validates the effective configuration for a recipe.

    Merges the layers with
    [merge_effective_config][napt.config.loader.merge_effective_config],
    then validates the result: errors raise, warnings are logged. The
    returned dict does not carry the ``parent`` field; the parent's contents
    are already merged in.

    Args:
        recipe_path: Path to the recipe YAML file.
        quiet: Skip the validation warnings and the dropped-keys line, for
            a caller that reads one setting and reports nothing about the
            recipe.

    Returns:
        The merged configuration; code defaults are always included.

    Raises:
        ConfigError: On a missing recipe or parent file, a YAML parse error,
            a layer whose top level is not a mapping, a parent chain, a
            foreign parent that fails its hash check, or a configuration
            that fails validation.
    """
    from napt.validation import validate_config

    logger = get_global_logger()
    merged, parent_path = merge_effective_config(recipe_path, quiet=quiet)

    result = validate_config(merged, recipe_path=str(recipe_path.resolve()))
    if result.errors:
        where = f" (parent: {parent_path})" if parent_path is not None else ""
        raise ConfigError(f"Invalid configuration{where}: {'; '.join(result.errors)}")
    if not quiet:
        for warning in result.warnings:
            logger.warning("CONFIG", warning)

    # The parent's contents are merged in; the pointer itself is not config.
    merged.pop("parent", None)
    merged["_provenance"].pop("parent", None)

    return merged
