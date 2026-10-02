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

"""Recipe validation module.

This module provides validation functions for checking recipe syntax and
configuration without making network calls or downloading files. This is
useful for quick feedback during recipe development and in CI/CD pipelines.
``napt validate`` checks the effective configuration (code defaults,
org.yaml, vendor defaults, parent, recipe), the same merge every other
command loads, so an error in any layer is reported before a pipeline
runs into it.

Validation Checks:

- YAML syntax is valid
- Required top-level fields present (apiVersion, name, id, discovery)
- apiVersion is present (a value other than napt/v1 is a warning)
- id is usable as a folder name (letters, digits, '.', '-', '_', '+',
  starting with a letter or digit)
- parent, when declared, is a string and the file carries the
  ``.override.yaml`` suffix (a mismatch either way is a warning)
- discovery.strategy exists and is registered
- Strategy-specific configuration is valid
- Every section (top level, discovery, psadt, psadt.brand_pack, intune,
  intune.detection, logging, directories, intunewin, deployment, secrets)
  is checked against its schema: field types, allowed values, integer
  bounds, and a warning for each unknown key naming the closest known one
- A section present but left empty is an error
- intune.minimum_supported_windows_release matches the Windows10_21H2 or
  Windows11_23H2 form
- psadt.app_vars only contains user-settable keys
- psadt.brand_pack.mappings entries each name a source and a target
- deployment ring names and groups are present and unique
- secrets section entries are shaped as ``NAME: {hosts: [...]}``, come
  from defaults/org.yaml alone, and every ``${NAME}`` a recipe sends is
  declared and bound to the request host (see [napt.secrets][])
- A directory of recipes contains no two files with the same id
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from difflib import get_close_matches
from pathlib import Path
import re
from typing import Any, NamedTuple

from napt.config.loader import (
    collect_recipe_paths,
    duplicate_recipe_id_message,
    merge_effective_config,
)
from napt.discovery.registry import get_strategy
from napt.discovery.url_download import (
    FIELDS as URL_DOWNLOAD_FIELDS,
    validate_url_download_config,
)
from napt.exceptions import ConfigError
from napt.logging import get_global_logger
from napt.paths import is_safe_path_component
from napt.results import ValidationResult


class _Field(NamedTuple):
    """The rules for one key of a configuration section.

    Attributes:
        type: The Python type the value must have. A ``dict`` field that is
            present but empty (YAML null) is reported as an empty section.
        allowed: The permitted values, or None when any value of the type
            is accepted.
        minimum: The lowest permitted value of an ``int`` field.
        maximum: The highest permitted value of an ``int`` field; set only
            together with ``minimum``.
    """

    type: type
    allowed: list[str] | None = None
    minimum: int | None = None
    maximum: int | None = None


_Schema = dict[str, _Field]

# Keys the config loader adds to a merged configuration; never recipe fields.
_INTERNAL_KEYS = frozenset({"_provenance"})

# The top level of a recipe or defaults file. Presence of the required
# fields is checked separately; this table drives types and unknown keys.
_TOP_LEVEL_FIELDS: _Schema = {
    "apiVersion": _Field(str),
    "name": _Field(str),
    "id": _Field(str),
    "parent": _Field(str),
    "discovery": _Field(dict),
    "psadt": _Field(dict),
    "intune": _Field(dict),
    "logging": _Field(dict),
    "deployment": _Field(dict),
    "directories": _Field(dict),
    "intunewin": _Field(dict),
    "secrets": _Field(dict),
}

_PSADT_FIELDS: _Schema = {
    "release": _Field(str),
    "cache_dir": _Field(str),
    "brand_pack": _Field(dict),
    "app_vars": _Field(dict),
    "override_msi_commands": _Field(bool),
    "override_msix_commands": _Field(bool),
    "install": _Field(str),
    "uninstall": _Field(str),
}

_BRAND_PACK_FIELDS: _Schema = {
    "path": _Field(str),
    "mappings": _Field(list),
}

# One psadt.brand_pack.mappings entry.
_BRAND_MAPPING_FIELDS: _Schema = {
    "source": _Field(str),
    "target": _Field(str),
}

_INTUNE_DETECTION_FIELDS: _Schema = {
    "display_name": _Field(str),
    "architecture": _Field(str, ["x86", "x64", "arm64", "any"]),
    "exact_match": _Field(bool),
    "override_msi_display_name": _Field(bool),
}

# The run time limit is Intune's: "Max timeout value is 1440 minutes" in
# https://learn.microsoft.com/en-us/intune/app-management/deployment/add-win32
_INTUNE_FIELDS: _Schema = {
    "build_types": _Field(str, ["both", "app_only", "update_only"]),
    "update_name_prefix": _Field(str),
    "minimum_supported_windows_release": _Field(str),
    "install_command": _Field(str),
    "uninstall_command": _Field(str),
    "is_featured": _Field(bool),
    "allow_available_uninstall": _Field(bool),
    "run_as_account": _Field(str, ["system", "user"]),
    "device_restart_behavior": _Field(
        str, ["allow", "suppress", "force", "basedOnReturnCode"]
    ),
    "max_run_time_minutes": _Field(int, minimum=1, maximum=1440),
    "enforce_signature_check": _Field(bool),
    "run_as_32_bit": _Field(bool),
    "description": _Field(str),
    "publisher": _Field(str),
    "privacy_url": _Field(str),
    "info_url": _Field(str),
    "logo_path": _Field(str),
    "developer": _Field(str),
    "owner": _Field(str),
    "detection": _Field(dict),
}

_LOGGING_FIELDS: _Schema = {
    "log_rotation_mb": _Field(int, minimum=1),
}

_DIRECTORIES_FIELDS: _Schema = {
    "discover": _Field(str),
    "build": _Field(str),
    "package": _Field(str),
    "icons": _Field(str),
    "state": _Field(str),
}

_INTUNEWIN_FIELDS: _Schema = {
    "release": _Field(str),
}

_DEPLOYMENT_FIELDS: _Schema = {
    "rings": _Field(list),
    "install": _Field(dict),
    "retain_versions": _Field(int, minimum=0),
    "require_pending": _Field(bool),
}

_DEPLOYMENT_INSTALL_FIELDS: _Schema = {
    "intent": _Field(str, ["available", "required"]),
    "groups": _Field(list),
}

# One deployment.rings entry.
_DEPLOYMENT_RING_FIELDS: _Schema = {
    "name": _Field(str),
    "groups": _Field(list),
    "promote_after_days": _Field(int, minimum=0),
}

# One secrets entry.
_SECRET_ENTRY_FIELDS: _Schema = {
    "hosts": _Field(list),
}

# An environment variable name, as the secrets section keys them.
_ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# A bare hostname for a secrets entry: no scheme, path, port, or wildcard.
_HOSTNAME = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9-]+)*")

# Provenance layers that may declare secrets, and how the others are named
# in error messages.
_SECRET_LAYERS = frozenset({"org_yaml", "code_default"})
_LAYER_NAMES = {
    "vendor_yaml": "the vendor defaults file",
    "parent": "the parent recipe",
    "recipe": "the recipe",
}

# Allowed keys for psadt.app_vars.
# NAPT-managed keys (AppArch, DeployAppScriptVersion, DeployAppScriptFriendlyName,
# DeployAppScriptParameters) are excluded; setting them in recipes is an error.
_PSADT_APP_VAR_KEYS: frozenset[str] = frozenset(
    {
        "AppVendor",
        "AppName",
        "AppVersion",
        "AppLang",
        "AppRevision",
        "AppSuccessExitCodes",
        "AppRebootExitCodes",
        "AppProcessesToClose",
        "AppScriptVersion",
        "AppScriptDate",
        "AppScriptAuthor",
        "RequireAdmin",
        "InstallName",
        "InstallTitle",
    }
)


# A section key that is present but has nothing under it. YAML reads it as
# null, which every consumer would then index as a dict.
_EMPTY_SECTION = (
    "{}: Must be a dictionary. The key is present but empty; remove it or "
    "add fields under it"
)

# The similarity (0 to 1) an unknown key needs to a known one before the
# known one is suggested. 0.6 accepts a dropped underscore or a one-letter
# slip in a short key and rejects keys that merely share a word.
_HINT_CUTOFF = 0.6


def _normalize_key(key: str) -> str:
    """Lowercases a key and drops the separators a typo most often loses."""
    return key.lower().replace("_", "").replace("-", "")


def _find_similar_field(unknown: str, known_fields: Iterable[str]) -> str | None:
    """Finds the known field an unknown key was most likely meant to be.

    The comparison ignores case and separators, so ``displayname`` finds
    ``display_name``, and takes the closest match by edit similarity above
    ``_HINT_CUTOFF``. Known fields are compared in sorted order, so the
    same unknown key always gets the same hint.

    Args:
        unknown: The unknown field name.
        known_fields: The valid field names of the section.

    Returns:
        The closest known field, or None when none is close enough.

    """
    by_normalized = {_normalize_key(k): k for k in sorted(known_fields)}
    matches = get_close_matches(
        _normalize_key(unknown), list(by_normalized), n=1, cutoff=_HINT_CUTOFF
    )
    return by_normalized[matches[0]] if matches else None


def _field_path(section_path: str, field_name: str) -> str:
    """Joins a section path and a field name; the top level has no prefix."""
    return f"{section_path}.{field_name}" if section_path else field_name


def _check_keys(
    section: dict,
    known_fields: Iterable[str],
    section_path: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Reports the keys of a section that are not strings or not in its schema.

    A key that is not a string (YAML reads ``1:`` as an integer and ``~:``
    as null) is an error. A string key the schema does not know is a
    warning naming the closest known key.

    Args:
        section: The configuration section.
        known_fields: The valid field names of the section.
        section_path: Full path to the section for messages; empty for the
            top level.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    prefix = f"{section_path}: " if section_path else ""
    known = set(known_fields)
    names: set[str] = set()
    for key in section:
        if isinstance(key, str):
            names.add(key)
        else:
            errors.append(f"{prefix}Key {key!r} must be a string")
    for unknown in sorted(names - known):
        message = f"Unknown field '{unknown}'"
        similar = _find_similar_field(unknown, known)
        if similar:
            message += f". Did you mean '{similar}'?"
        warnings.append(prefix + message)


def _validate_field_type(
    value: object,
    expected_type: type,
    field_path: str,
    errors: list[str],
) -> bool:
    """Validates that a field has the expected type.

    A ``dict`` field that is present but empty is reported as an empty
    section. A YAML boolean is not accepted for an ``int`` field, although
    Python's ``bool`` is a subclass of ``int``.

    Args:
        value: The value to check.
        expected_type: Expected Python type.
        field_path: Full path to field for error messages.
        errors: List to append errors to.

    Returns:
        True if type is valid, False otherwise.

    """
    if expected_type is dict:
        if value is None:
            errors.append(_EMPTY_SECTION.format(field_path))
            return False
        if not isinstance(value, dict):
            errors.append(f"{field_path}: Must be a dictionary")
            return False
        return True
    if not isinstance(value, expected_type) or (
        expected_type is int and isinstance(value, bool)
    ):
        type_name = expected_type.__name__
        actual_type = type(value).__name__
        errors.append(f"{field_path}: Must be {type_name}, got {actual_type}")
        return False
    return True


def _validate_field_value(
    value: object,
    allowed_values: list[str],
    field_path: str,
    errors: list[str],
) -> bool:
    """Validates that a field value is in the allowed set.

    Args:
        value: The value to check.
        allowed_values: List of allowed values.
        field_path: Full path to field for error messages.
        errors: List to append errors to.

    Returns:
        True if value is valid, False otherwise.

    """
    if value not in allowed_values:
        allowed_str = ", ".join(f"'{v}'" for v in allowed_values)
        errors.append(f"{field_path}: Invalid value '{value}'. Allowed: {allowed_str}")
        return False
    return True


def _validate_field_range(
    value: int,
    field: _Field,
    field_path: str,
    errors: list[str],
) -> bool:
    """Validates that an integer field is within its schema's bounds.

    Args:
        value: The value to check.
        field: The field's schema entry.
        field_path: Full path to field for error messages.
        errors: List to append errors to.

    Returns:
        True if the value is in range, False otherwise.

    """
    low, high = field.minimum, field.maximum
    if low is not None and high is not None:
        if not low <= value <= high:
            errors.append(
                f"{field_path}: Must be between {low} and {high}, got {value}"
            )
            return False
    elif low is not None and value < low:
        errors.append(f"{field_path}: Must be >= {low}, got {value}")
        return False
    return True


def _validate_section(
    section: dict,
    schema: _Schema,
    section_path: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validates a configuration section against its schema.

    Checks types, allowed values, and integer bounds, and warns on unknown
    fields. Presence of required fields is the caller's concern.

    Args:
        section: The configuration section to validate.
        schema: Schema definition for this section.
        section_path: Full path to section for error messages; empty for
            the top level.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    _check_keys(section, schema, section_path, errors, warnings)

    for field_name, field in schema.items():
        if field_name not in section:
            continue

        value = section[field_name]
        field_path = _field_path(section_path, field_name)

        if not _validate_field_type(value, field.type, field_path, errors):
            continue
        if field.allowed is not None:
            _validate_field_value(value, field.allowed, field_path, errors)
        elif field.type is int:
            _validate_field_range(value, field, field_path, errors)


def _validate_psadt_app_vars(
    app_vars: dict,
    app_vars_path: str,
    errors: list[str],
) -> None:
    """Validates that all keys in a psadt.app_vars dict are in the allowed set.

    NAPT-managed keys (AppArch, DeployAppScriptVersion, etc.) are excluded
    from the allowed set because NAPT sets them automatically.

    Args:
        app_vars: The app_vars value from the recipe.
        app_vars_path: Full path to the field for error messages.
        errors: List to append errors to.

    """
    allowed_sorted = ", ".join(sorted(_PSADT_APP_VAR_KEYS))
    for key in app_vars:
        if key not in _PSADT_APP_VAR_KEYS:
            errors.append(
                f"{app_vars_path}: Unknown key '{key}'. NAPT sets AppArch and "
                f"DeployAppScriptVersion automatically. "
                f"Allowed keys: {allowed_sorted}"
            )


def _validate_brand_pack(
    brand_pack: dict,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validates psadt.brand_pack and each of its mappings.

    A mapping's target is joined onto the build folder, so it must be a
    relative path of safe components: no leading separator, drive, or
    ``..``, and forward slashes only.

    Args:
        brand_pack: The brand_pack value from the configuration.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    _validate_section(
        brand_pack, _BRAND_PACK_FIELDS, "psadt.brand_pack", errors, warnings
    )
    mappings = brand_pack.get("mappings")
    if not isinstance(mappings, list):
        return
    for index, mapping in enumerate(mappings):
        path = f"psadt.brand_pack.mappings[{index}]"
        if not isinstance(mapping, dict):
            errors.append(f"{path}: Must be a dictionary")
            continue
        _validate_section(mapping, _BRAND_MAPPING_FIELDS, path, errors, warnings)
        for key in ("source", "target"):
            if key not in mapping or mapping[key] == "":
                errors.append(f"{path}: Missing required field: {key}")
        target = mapping.get("target")
        if (
            isinstance(target, str)
            and target
            and not all(is_safe_path_component(p) for p in target.split("/"))
        ):
            errors.append(
                f"{path}.target: Must be a relative path inside the build, "
                f"with forward slashes and no '..' (for example Assets/AppIcon)"
            )


def _validate_psadt_section(
    config: dict,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validates the top-level psadt: section.

    Checks field types, the brand pack shape, and that app_vars only
    contains known, user-settable keys. The section's own presence and
    type are checked by the top-level schema.

    Args:
        config: The full configuration dictionary.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    psadt = config.get("psadt")
    if not isinstance(psadt, dict):
        return

    _validate_section(psadt, _PSADT_FIELDS, "psadt", errors, warnings)

    app_vars = psadt.get("app_vars")
    if isinstance(app_vars, dict):
        _validate_psadt_app_vars(app_vars, "psadt.app_vars", errors)

    brand_pack = psadt.get("brand_pack")
    if isinstance(brand_pack, dict):
        _validate_brand_pack(brand_pack, errors, warnings)


def _validate_intune_section(
    config: dict,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validates the top-level intune: section.

    Validates field types, allowed values, and warns on unknown fields. Also
    validates the intune.detection subsection if present.

    Args:
        config: The full configuration dictionary.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    intune = config.get("intune")
    if not isinstance(intune, dict):
        return

    _validate_section(intune, _INTUNE_FIELDS, "intune", errors, warnings)

    # Validate minimum_supported_windows_release format (e.g. "Windows10_21H2")
    release = intune.get("minimum_supported_windows_release")
    if isinstance(release, str) and not re.fullmatch(
        r"Windows(?:10|11)_(?:\d{4}|\d{2}H[12])", release
    ):
        errors.append(
            "intune.minimum_supported_windows_release: Invalid format "
            f"{release!r}. "
            "Expected format: 'Windows10_21H2' or 'Windows11_23H2'"
        )

    detection = intune.get("detection")
    if isinstance(detection, dict):
        _validate_section(
            detection, _INTUNE_DETECTION_FIELDS, "intune.detection", errors, warnings
        )


def _validate_table_section(
    config: dict,
    section_name: str,
    schema: _Schema,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validates a top-level section that is fully described by a schema.

    Args:
        config: The full configuration dictionary.
        section_name: The top-level key of the section.
        schema: Schema definition for this section.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    section = config.get(section_name)
    if isinstance(section, dict):
        _validate_section(section, schema, section_name, errors, warnings)


def _validate_group_list(
    groups: list,
    field_path: str,
    errors: list[str],
) -> None:
    """Validate the entries of an Entra ID group list.

    Callers are responsible for the list type check (via
    [_validate_section][napt.validation._validate_section]); this only
    checks the entries.

    Args:
        groups: The groups list to check.
        field_path: Full path to the field for error messages.
        errors: List to append errors to.

    """
    for index, group in enumerate(groups):
        if not isinstance(group, str) or not group:
            errors.append(f"{field_path}[{index}]: Must be a non-empty string")


def _validate_deployment_section(
    config: dict,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validates the top-level deployment: section.

    Validates ring entries, the install subsection, retention, and the
    require_pending flag.

    Args:
        config: The full configuration dictionary.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    deployment = config.get("deployment")
    if not isinstance(deployment, dict):
        return

    _validate_section(deployment, _DEPLOYMENT_FIELDS, "deployment", errors, warnings)

    rings = deployment.get("rings")
    if isinstance(rings, list):
        ring_names: set[str] = set()
        for index, ring in enumerate(rings):
            ring_path = f"deployment.rings[{index}]"
            if not isinstance(ring, dict):
                errors.append(f"{ring_path}: Must be a dictionary")
                continue
            _validate_section(
                ring, _DEPLOYMENT_RING_FIELDS, ring_path, errors, warnings
            )
            # Wrong-typed fields are already reported by _validate_section;
            # the checks below only cover absence and value constraints.
            name = ring.get("name")
            if "name" not in ring or name == "":
                errors.append(f"{ring_path}: Missing required field: name")
            elif isinstance(name, str):
                if name in ring_names:
                    errors.append(f"{ring_path}: Duplicate ring name '{name}'")
                else:
                    ring_names.add(name)
            groups = ring.get("groups")
            if "groups" not in ring or groups == []:
                errors.append(f"{ring_path}: Missing required field: groups")
            elif isinstance(groups, list):
                _validate_group_list(groups, f"{ring_path}.groups", errors)

    install = deployment.get("install")
    if isinstance(install, dict):
        _validate_section(
            install, _DEPLOYMENT_INSTALL_FIELDS, "deployment.install", errors, warnings
        )
        if isinstance(install.get("groups"), list):
            _validate_group_list(install["groups"], "deployment.install.groups", errors)


def _foreign_layers(provenance: object) -> list[str]:
    """Names the layers other than org.yaml that set values under a key.

    Args:
        provenance: The provenance entry for the key: a layer name, or a
            dict of them for a section.

    Returns:
        Display names of the offending layers, sorted; empty when only
        org.yaml (or the code default) set the values.
    """
    found: set[str] = set()

    def _walk(entry: object) -> None:
        if isinstance(entry, dict):
            for value in entry.values():
                _walk(value)
        elif isinstance(entry, str) and entry not in _SECRET_LAYERS:
            found.add(entry)

    _walk(provenance)
    return [_LAYER_NAMES.get(layer, layer) for layer in sorted(found)]


def _validate_secrets_section(
    config: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validates the top-level secrets: section.

    Every entry must be shaped as ``NAME: {hosts: [hostname, ...]}`` and
    come from defaults/org.yaml. The config loader keeps other layers'
    entries out of the merged section; their attempt is still visible in
    the provenance and reported here so the author learns why the secret
    is not honored.

    Args:
        config: The full merged configuration.
        errors: List to append errors to.
        warnings: List to append warnings to.
    """
    provenance = config.get("_provenance")
    section_prov = provenance.get("secrets") if isinstance(provenance, dict) else None
    if isinstance(section_prov, dict):
        for name, entry_prov in section_prov.items():
            layers = _foreign_layers(entry_prov)
            if layers:
                errors.append(
                    f"secrets.{name}: declared in {', '.join(layers)}; secrets "
                    f"are declared only in defaults/org.yaml"
                )
    else:
        layers = _foreign_layers(section_prov)
        if layers:
            errors.append(
                f"secrets: declared in {', '.join(layers)}; secrets are declared "
                f"only in defaults/org.yaml"
            )

    secrets = config.get("secrets")
    if not isinstance(secrets, dict):
        return

    for name, entry in secrets.items():
        if not isinstance(name, str) or not _ENV_VAR_NAME.fullmatch(name):
            errors.append(
                f"secrets: {name!r} is not an environment variable name "
                f"(letters, digits, and underscores, not starting with a digit)"
            )
        path = f"secrets.{name}"
        if not isinstance(entry, dict):
            errors.append(f"{path}: Must be a dictionary")
            continue
        _validate_section(entry, _SECRET_ENTRY_FIELDS, path, errors, warnings)
        hosts = entry.get("hosts")
        if "hosts" not in entry or hosts == []:
            errors.append(f"{path}: Missing required field: hosts")
        elif isinstance(hosts, list):
            for index, host in enumerate(hosts):
                if not isinstance(host, str) or not _HOSTNAME.fullmatch(host.strip()):
                    errors.append(
                        f"{path}.hosts[{index}]: Must be a hostname such as "
                        f"api.vendor.com (no scheme, path, or port)"
                    )


def _validate_discovery_section(
    discovery: dict,
    config: dict[str, Any],
    app_name: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validates the discovery: section through its strategy.

    The strategy's own validator checks the fields it requires; this
    resolves the strategy and warns on keys outside the fields it
    declares.

    Args:
        discovery: The discovery section.
        config: The full configuration dictionary the strategy validates.
        app_name: The recipe's name, for the log.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    logger = get_global_logger()

    if "strategy" not in discovery:
        errors.append("discovery: Missing required field: strategy")
        return
    strategy_name = discovery["strategy"]
    if not isinstance(strategy_name, str):
        errors.append("discovery.strategy: Must be a string")
        return
    logger.verbose("VALIDATION", f"'{app_name}' uses strategy: {strategy_name}")

    if strategy_name == "url_download":
        errors.extend(validate_url_download_config(config))
        known = URL_DOWNLOAD_FIELDS
    else:
        try:
            strategy = get_strategy(strategy_name)
        except ConfigError as err:
            errors.append(f"discovery.strategy: {err}")
            return
        errors.extend(strategy.validate_config(config))
        known = strategy.FIELDS

    _check_keys(discovery, known | {"strategy"}, "discovery", errors, warnings)


def _validate_parent_field(
    config: dict[str, Any],
    recipe_path: str,
    warnings: list[str],
) -> None:
    """Warns when the parent field and the file-name convention disagree.

    A recipe that declares ``parent`` is expected to be named
    ``<app>.override.yaml`` so the relationship is visible in every listing;
    the suffix without a parent, or a parent without the suffix, is a
    warning so a hand-written child recipe can opt out. The value itself
    is checked by the config loader, which resolves it before any
    validation runs.

    Args:
        config: The full recipe dictionary.
        recipe_path: Path string of the recipe file, or empty when unknown.
        warnings: List to append warnings to.
    """
    has_parent = "parent" in config
    if not recipe_path:
        return
    has_suffix = recipe_path.endswith(".override.yaml")
    if has_parent and not has_suffix:
        warnings.append(
            "parent is declared but the file is not named <app>.override.yaml"
        )
    elif has_suffix and not has_parent:
        warnings.append("File is named <app>.override.yaml but declares no parent")


def validate_config(
    config: dict[str, Any],
    recipe_path: str = "",
) -> ValidationResult:
    """Validates a merged configuration dict.

    Checks required fields, types, strategy registration, and section-level
    validation. Used by both ``validate_recipe`` (CLI) and
    ``load_effective_config`` (pipeline commands) so that one set of rules
    applies everywhere. When the dict carries the loader's ``_provenance``
    entry, the secrets check also reports entries that a layer other than
    org.yaml tried to declare.

    Args:
        config: The merged configuration dictionary to validate.
        recipe_path: Optional path string for error context.

    Returns:
        Validation status, errors, warnings, app count, and the app id.

    """
    logger = get_global_logger()

    errors: list[str] = []
    warnings: list[str] = []

    # Types of every top-level field, empty sections, and unknown keys.
    top_level = {k: v for k, v in config.items() if k not in _INTERNAL_KEYS}
    _validate_section(top_level, _TOP_LEVEL_FIELDS, "", errors, warnings)

    for field in ("apiVersion", "name", "id", "discovery"):
        if field not in config:
            errors.append(f"Missing required field: {field}")

    api_version = config.get("apiVersion")
    if isinstance(api_version, str):
        if api_version != "napt/v1":
            warnings.append(
                f"apiVersion '{api_version}' may not be supported (expected: napt/v1)"
            )
        logger.verbose("VALIDATION", f"apiVersion: {api_version}")

    app_id = config.get("id")
    if isinstance(app_id, str):
        if not app_id:
            errors.append("Field 'id' cannot be empty")
        elif not is_safe_path_component(app_id):
            # The id names the app's download, build, package, and state
            # folders, so it must be usable as a folder name as-is.
            errors.append(
                "Field 'id' may contain only letters, digits, '.', '-', '_', "
                "and '+', and must start with a letter or digit"
            )

    _validate_parent_field(config, recipe_path, warnings)

    app_name = config.get("name", "unnamed")
    logger.verbose("VALIDATION", f"Validating: {app_name}")

    discovery = config.get("discovery")
    if isinstance(discovery, dict):
        _validate_discovery_section(discovery, config, app_name, errors, warnings)

    _validate_psadt_section(config, errors, warnings)
    _validate_intune_section(config, errors, warnings)
    _validate_table_section(config, "logging", _LOGGING_FIELDS, errors, warnings)
    _validate_table_section(
        config, "directories", _DIRECTORIES_FIELDS, errors, warnings
    )
    _validate_table_section(config, "intunewin", _INTUNEWIN_FIELDS, errors, warnings)
    _validate_deployment_section(config, errors, warnings)
    _validate_secrets_section(config, errors, warnings)

    # Determine final status
    status = "valid" if len(errors) == 0 else "invalid"
    app_count = 1 if status == "valid" else 0

    if status == "valid":
        logger.verbose("VALIDATION", "Recipe is valid!")
    else:
        logger.verbose("VALIDATION", f"Recipe has {len(errors)} error(s)")

    app_id = config.get("id")
    return ValidationResult(
        status=status,
        errors=errors,
        warnings=warnings,
        app_count=app_count,
        recipe_path=recipe_path,
        app_id=app_id if isinstance(app_id, str) and app_id else None,
    )


def validate_recipe(recipe_path: Path) -> ValidationResult:
    """Validates a recipe's effective configuration.

    Merges the recipe with its parent, vendor defaults, and org.yaml the
    way every other command does, then validates the result, so an error
    in any layer is reported here. A file that cannot be read or merged (a
    missing file, a YAML syntax error, a missing parent) is an invalid
    result rather than an exception.

    Args:
        recipe_path: Path to the recipe YAML file to validate.

    Returns:
        Validation status, errors, warnings, app count, app id, and the
            parent path when the recipe declares one.

    Example:
        Validate a recipe and check results:
            ```python
            from pathlib import Path

            result = validate_recipe(Path("recipes/app.yaml"))
            if result.status == "valid":
                print("Recipe is valid!")
            else:
                for error in result.errors:
                    print(f"Error: {error}")
            ```

    """
    logger = get_global_logger()
    recipe_path_str = str(recipe_path)
    logger.verbose("VALIDATION", f"Validating recipe: {recipe_path}")

    try:
        merged, parent_path = merge_effective_config(recipe_path)
    except ConfigError as err:
        return ValidationResult(
            status="invalid",
            errors=[str(err)],
            warnings=[],
            app_count=0,
            recipe_path=recipe_path_str,
        )
    logger.verbose("VALIDATION", "YAML syntax is valid")
    if parent_path is not None:
        logger.verbose("VALIDATION", f"Parent recipe: {parent_path}")

    result = validate_config(merged, recipe_path=recipe_path_str)
    if parent_path is None:
        return result
    return replace(result, parent_path=str(parent_path))


def validate_recipes(path: Path) -> list[ValidationResult]:
    """Validates a recipe file or every recipe under a directory.

    Each file is validated with
    [validate_recipe][napt.validation.validate_recipe]. For a directory,
    two files that resolve to the same id are also reported (a parent
    recipe scanned beside the child that inherits its id is the usual
    cause), since ``napt promote`` refuses such a directory.

    Args:
        path: A recipe YAML file, or a directory scanned recursively.

    Returns:
        One result per recipe file, in path order; a single invalid result
            when the path does not exist or holds no recipes.
    """
    try:
        paths = collect_recipe_paths(path)
    except ConfigError as err:
        return [
            ValidationResult(
                status="invalid",
                errors=[str(err)],
                warnings=[],
                app_count=0,
                recipe_path=str(path),
            )
        ]

    results: list[ValidationResult] = []
    sources: dict[str, Path] = {}
    for recipe_path in paths:
        result = validate_recipe(recipe_path)
        if result.status == "valid" and result.app_id is not None:
            first = sources.get(result.app_id)
            if first is None:
                sources[result.app_id] = recipe_path
            else:
                result = replace(
                    result,
                    status="invalid",
                    app_count=0,
                    errors=[
                        *result.errors,
                        duplicate_recipe_id_message(result.app_id, first, recipe_path),
                    ],
                )
        results.append(result)
    return results
