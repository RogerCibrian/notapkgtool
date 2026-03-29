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

Validation Checks:

- YAML syntax is valid
- Required top-level fields present (apiVersion, name, id, discovery)
- apiVersion is supported
- discovery.strategy exists and is registered
- Strategy-specific configuration is valid
- intune.detection fields are valid (types, values, unknown field warnings)
- psadt.app_vars only contains user-settable keys
- logging section fields are valid

Example:
    Validate a recipe and handle results:
        ```python
        from pathlib import Path
        from napt.validation import validate_recipe

        result = validate_recipe(Path("recipes/Google/chrome.yaml"))
        if result.status == "valid":
            print(f"Recipe is valid with {result.app_count} app(s)")
        else:
            for error in result.errors:
                print(f"Error: {error}")
        ```

"""

from __future__ import annotations

from pathlib import Path

import yaml

from napt.discovery import get_strategy
from napt.exceptions import ConfigError
from napt.logging import get_global_logger
from napt.results import ValidationResult

__all__ = ["validate_recipe"]


# Schema for the intune.detection subsection
_INTUNE_DETECTION_FIELDS: dict[str, tuple[type, list[str] | None, str]] = {
    "display_name": (str, None, "display name for registry lookup"),
    "architecture": (str, ["x86", "x64", "arm64", "any"], "architecture"),
    "exact_match": (bool, None, "exact version match flag"),
    "override_msi_display_name": (bool, None, "MSI display name override flag"),
}

# Schema for the intune: section
_INTUNE_FIELDS: dict[str, tuple[type, list[str] | None, str]] = {
    "build_types": (str, ["both", "app_only", "update_only"], "build type"),
    "update_name_prefix": (str, None, "prefix for update entry display name"),
    "minimum_supported_windows_release": (str, None, "minimum Windows release"),
    "install_command": (str, None, "Intune install command line"),
    "uninstall_command": (str, None, "Intune uninstall command line"),
    "description": (str, None, "app description for Intune portal"),
    "publisher": (str, None, "publisher name override"),
    "category": (str, None, "Intune app category"),
    "privacy_url": (str, None, "privacy information URL"),
    "info_url": (str, None, "information URL"),
    "logo_path": (str, None, "path to app icon file"),
    "developer": (str, None, "app developer or maintainer"),
    "owner": (str, None, "business owner of the app"),
    "notes": (str, None, "free-text notes shown in Intune portal"),
    "detection": (dict, None, "detection configuration"),
}

# Schema for the logging: section
_LOGGING_FIELDS: dict[str, tuple[type, list[str] | None, str]] = {
    "log_format": (str, ["cmtrace"], "log format"),
    "log_level": (str, ["INFO", "WARNING", "ERROR", "DEBUG"], "log level"),
    "log_rotation_mb": (int, None, "log rotation size in MB"),
}

# Allowed keys for psadt.app_vars.
# NAPT-managed keys (AppArch, DeployAppScriptVersion, DeployAppScriptFriendlyName,
# DeployAppScriptParameters) are excluded — setting them in recipes is an error.
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


def _find_similar_field(unknown: str, known_fields: set[str]) -> str | None:
    """Find a similar field name for typo suggestions.

    Uses simple heuristics: lowercase comparison, common typo patterns.

    Args:
        unknown: The unknown field name.
        known_fields: Set of known valid field names.

    Returns:
        Similar field name if found, None otherwise.

    """
    unknown_lower = unknown.lower().replace("_", "").replace("-", "")

    for known in known_fields:
        known_lower = known.lower().replace("_", "").replace("-", "")
        # Exact match after normalization (e.g., "displayname" -> "display_name")
        if unknown_lower == known_lower:
            return known
        # Check if one is substring of other (e.g., "display" in "display_name")
        if len(unknown_lower) > 3 and (
            unknown_lower in known_lower or known_lower in unknown_lower
        ):
            return known

    return None


def _validate_field_type(
    value: object,
    expected_type: type,
    field_path: str,
    errors: list[str],
) -> bool:
    """Validate that a field has the expected type.

    Args:
        value: The value to check.
        expected_type: Expected Python type.
        field_path: Full path to field for error messages.
        errors: List to append errors to.

    Returns:
        True if type is valid, False otherwise.

    """
    if not isinstance(value, expected_type):
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
    """Validate that a field value is in the allowed set.

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


def _validate_section(
    section: dict,
    schema: dict[str, tuple[type, list[str] | None, str]],
    section_path: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate a configuration section against its schema.

    Checks types, allowed values, and warns on unknown fields.

    Args:
        section: The configuration section to validate.
        schema: Schema definition for this section.
        section_path: Full path to section for error messages.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    known_fields = set(schema.keys())
    actual_fields = set(section.keys())

    # Check for unknown fields
    unknown_fields = actual_fields - known_fields
    for unknown in unknown_fields:
        similar = _find_similar_field(unknown, known_fields)
        if similar:
            warnings.append(
                f"{section_path}: Unknown field '{unknown}'. Did you mean '{similar}'?"
            )
        else:
            warnings.append(f"{section_path}: Unknown field '{unknown}'")

    # Validate known fields
    for field_name, (expected_type, allowed_values, _desc) in schema.items():
        if field_name not in section:
            continue

        value = section[field_name]
        field_path = f"{section_path}.{field_name}"

        # Type check
        if not _validate_field_type(value, expected_type, field_path, errors):
            continue

        # Value check (only for non-dict types with allowed values)
        if allowed_values is not None and expected_type is not dict:
            _validate_field_value(value, allowed_values, field_path, errors)


def _validate_psadt_app_vars(
    app_vars: object,
    app_vars_path: str,
    errors: list[str],
) -> None:
    """Validate that all keys in a psadt.app_vars dict are in the allowed set.

    NAPT-managed keys (AppArch, DeployAppScriptVersion, etc.) are excluded
    from the allowed set because NAPT sets them automatically.

    Args:
        app_vars: The app_vars value from the recipe (may not be a dict).
        app_vars_path: Full path to the field for error messages.
        errors: List to append errors to.

    """
    if not isinstance(app_vars, dict):
        errors.append(f"{app_vars_path}: Must be a dictionary")
        return

    allowed_sorted = ", ".join(sorted(_PSADT_APP_VAR_KEYS))
    for key in app_vars:
        if key not in _PSADT_APP_VAR_KEYS:
            errors.append(
                f"{app_vars_path}: Unknown key '{key}'. NAPT sets AppArch and "
                f"DeployAppScriptVersion automatically. "
                f"Allowed keys: {allowed_sorted}"
            )


def _validate_psadt_section(
    recipe: dict,
    errors: list[str],
) -> None:
    """Validate the top-level psadt: section.

    Checks that app_vars only contains known, user-settable keys.

    Args:
        recipe: The full recipe dictionary.
        errors: List to append errors to.

    """
    psadt = recipe.get("psadt")
    if psadt is None:
        return

    if not isinstance(psadt, dict):
        errors.append("psadt: Must be a dictionary")
        return

    app_vars = psadt.get("app_vars")
    if app_vars is not None:
        _validate_psadt_app_vars(app_vars, "psadt.app_vars", errors)


def _validate_intune_section(
    recipe: dict,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate the top-level intune: section.

    Validates field types, allowed values, and warns on unknown fields. Also
    validates the intune.detection subsection if present.

    Args:
        recipe: The full recipe dictionary.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    intune = recipe.get("intune")
    if intune is None:
        return

    if not isinstance(intune, dict):
        errors.append("intune: Must be a dictionary")
        return

    _validate_section(intune, _INTUNE_FIELDS, "intune", errors, warnings)

    # Validate detection subsection
    detection = intune.get("detection")
    if detection is not None:
        if not isinstance(detection, dict):
            errors.append("intune.detection: Must be a dictionary")
        else:
            _validate_section(
                detection,
                _INTUNE_DETECTION_FIELDS,
                "intune.detection",
                errors,
                warnings,
            )


def _validate_logging_section(
    recipe: dict,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate the top-level logging: section.

    Validates log_format, log_level, and log_rotation_mb fields.

    Args:
        recipe: The full recipe dictionary.
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    logging_config = recipe.get("logging")
    if logging_config is None:
        return

    if not isinstance(logging_config, dict):
        errors.append("logging: Must be a dictionary")
        return

    _validate_section(logging_config, _LOGGING_FIELDS, "logging", errors, warnings)


def validate_recipe(recipe_path: Path) -> ValidationResult:
    """Validate a recipe file without downloading anything.

    Validates recipe syntax, required fields, and configuration without
    making network calls.

    Args:
        recipe_path: Path to the recipe YAML file to validate.

    Returns:
        Validation status, errors, warnings, and app count.

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

    errors = []
    warnings = []

    logger.verbose("VALIDATION", f"Validating recipe: {recipe_path}")

    # Check file exists
    if not recipe_path.exists():
        errors.append(f"Recipe file not found: {recipe_path}")
        return ValidationResult(
            status="invalid",
            errors=errors,
            warnings=warnings,
            app_count=0,
            recipe_path=str(recipe_path),
        )

    # Parse YAML
    try:
        with open(recipe_path, encoding="utf-8") as f:
            recipe = yaml.safe_load(f)
    except yaml.YAMLError as err:
        errors.append(f"Invalid YAML syntax: {err}")
        return ValidationResult(
            status="invalid",
            errors=errors,
            warnings=warnings,
            app_count=0,
            recipe_path=str(recipe_path),
        )
    except Exception as err:
        errors.append(f"Failed to read recipe file: {err}")
        return ValidationResult(
            status="invalid",
            errors=errors,
            warnings=warnings,
            app_count=0,
            recipe_path=str(recipe_path),
        )

    logger.verbose("VALIDATION", "YAML syntax is valid")

    # Validate recipe is a dict
    if not isinstance(recipe, dict):
        errors.append("Recipe must be a YAML dictionary/mapping")
        return ValidationResult(
            status="invalid",
            errors=errors,
            warnings=warnings,
            app_count=0,
            recipe_path=str(recipe_path),
        )

    # Check apiVersion
    if "apiVersion" not in recipe:
        errors.append("Missing required field: apiVersion")
    else:
        api_version = recipe["apiVersion"]
        if not isinstance(api_version, str):
            errors.append("apiVersion must be a string")
        elif api_version != "napt/v1":
            warnings.append(
                f"apiVersion '{api_version}' may not be supported (expected: napt/v1)"
            )
        if not errors:
            logger.verbose("VALIDATION", f"apiVersion: {api_version}")

    # Check required top-level fields: name and id
    for field in ["name", "id"]:
        if field not in recipe:
            errors.append(f"Missing required field: {field}")

    if "name" in recipe and not isinstance(recipe["name"], str):
        errors.append("Field 'name' must be a string")

    if "id" in recipe:
        if not isinstance(recipe["id"], str):
            errors.append("Field 'id' must be a string")
        elif not recipe["id"]:
            errors.append("Field 'id' cannot be empty")

    app_name = recipe.get("name", "unnamed")
    logger.verbose("VALIDATION", f"Validating: {app_name}")

    # Validate discovery section
    discovery = recipe.get("discovery")
    if not discovery:
        errors.append("Missing required field: discovery")
    elif not isinstance(discovery, dict):
        errors.append("Field 'discovery' must be a dictionary")
    else:
        if "strategy" not in discovery:
            errors.append("discovery: Missing required field: strategy")
        else:
            strategy_name = discovery["strategy"]
            if not isinstance(strategy_name, str):
                errors.append("discovery.strategy: Must be a string")
            else:
                logger.verbose(
                    "VALIDATION",
                    f"'{app_name}' uses strategy: {strategy_name}",
                )

                # Check if strategy exists
                try:
                    strategy = get_strategy(strategy_name)
                except ConfigError as err:
                    errors.append(f"discovery.strategy: {err}")
                else:
                    # Validate strategy-specific configuration
                    if hasattr(strategy, "validate_config"):
                        try:
                            config_errors = strategy.validate_config(recipe)
                            errors.extend(config_errors)
                        except Exception as err:
                            errors.append(f"Strategy validation failed: {err}")

    # Validate optional sections
    _validate_psadt_section(recipe, errors)
    _validate_intune_section(recipe, errors, warnings)
    _validate_logging_section(recipe, errors, warnings)

    # Determine final status
    status = "valid" if len(errors) == 0 else "invalid"
    app_count = 1 if status == "valid" else 0

    if status == "valid":
        logger.verbose("VALIDATION", "Recipe is valid!")
    else:
        logger.verbose("VALIDATION", f"Recipe has {len(errors)} error(s)")

    return ValidationResult(
        status=status,
        errors=errors,
        warnings=warnings,
        app_count=app_count,
        recipe_path=str(recipe_path),
    )
