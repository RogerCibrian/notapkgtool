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
- Required top-level fields present (apiVersion, app)
- apiVersion is supported
- App has required fields (name, id, source)
- Discovery strategy exists and is registered
- Strategy-specific configuration is valid
- Win32 configuration fields are valid (types, values, unknown field warnings)

Example:
    Validate a recipe and handle results:
        ```python
        from pathlib import Path
        from notapkgtool.validation import validate_recipe

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

from notapkgtool.discovery import get_strategy
from notapkgtool.exceptions import ConfigError
from notapkgtool.logging import get_global_logger
from notapkgtool.results import ValidationResult

__all__ = ["validate_recipe"]


# Schema definitions for win32 configuration validation
# Each entry: field_name -> (expected_type, allowed_values or None, description)
_WIN32_FIELDS: dict[str, tuple[type, list[str] | None, str]] = {
    "build_types": (str, ["both", "app_only", "update_only"], "build type"),
    "installed_check": (dict, None, "installed check configuration"),
}

_INSTALLED_CHECK_FIELDS: dict[str, tuple[type, list[str] | None, str]] = {
    "display_name": (str, None, "display name for registry lookup"),
    "architecture": (str, ["x86", "x64", "arm64", "any"], "architecture"),
    "override_msi_display_name": (bool, None, "MSI display name override flag"),
    "fail_on_error": (bool, None, "fail on error flag"),
    "log_format": (str, ["cmtrace"], "log format"),
    "log_level": (str, ["INFO", "WARNING", "ERROR", "DEBUG"], "log level"),
    "log_rotation_mb": (int, None, "log rotation size in MB"),
    "detection": (dict, None, "detection configuration"),
}

_DETECTION_FIELDS: dict[str, tuple[type, list[str] | None, str]] = {
    "exact_match": (bool, None, "exact version match flag"),
}


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


def _validate_win32_config(
    app: dict,
    app_prefix: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate the win32 configuration section.

    Validates:
    - win32.build_types
    - win32.installed_check.*
    - win32.installed_check.detection.*

    Args:
        app: The app configuration dictionary.
        app_prefix: Prefix for error messages (e.g., "app").
        errors: List to append errors to.
        warnings: List to append warnings to.

    """
    win32 = app.get("win32")
    if win32 is None:
        return

    win32_path = f"{app_prefix}.win32"

    # Validate win32 is a dict
    if not isinstance(win32, dict):
        errors.append(f"{win32_path}: Must be a dictionary")
        return

    # Validate win32 section
    _validate_section(win32, _WIN32_FIELDS, win32_path, errors, warnings)

    # Validate installed_check subsection
    installed_check = win32.get("installed_check")
    if installed_check is not None:
        ic_path = f"{win32_path}.installed_check"

        if not isinstance(installed_check, dict):
            errors.append(f"{ic_path}: Must be a dictionary")
        else:
            _validate_section(
                installed_check, _INSTALLED_CHECK_FIELDS, ic_path, errors, warnings
            )

            # Validate detection subsection
            detection = installed_check.get("detection")
            if detection is not None:
                det_path = f"{ic_path}.detection"

                if not isinstance(detection, dict):
                    errors.append(f"{det_path}: Must be a dictionary")
                else:
                    _validate_section(
                        detection, _DETECTION_FIELDS, det_path, errors, warnings
                    )


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
    app_count = 0

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

    # Check app field
    app = recipe.get("app")
    if not app:
        errors.append("Field 'app' is required")
        return ValidationResult(
            status="invalid",
            errors=errors,
            warnings=warnings,
            app_count=0,
            recipe_path=str(recipe_path),
        )

    if not isinstance(app, dict):
        errors.append("Field 'app' must be a dictionary")
        return ValidationResult(
            status="invalid",
            errors=errors,
            warnings=warnings,
            app_count=0,
            recipe_path=str(recipe_path),
        )

    app_prefix = "app"

    logger.verbose("VALIDATION", f"Found app: {app.get('name', 'unnamed')}")

    # Check required fields
    for field in ["name", "id", "source"]:
        if field not in app:
            errors.append(f"{app_prefix}: Missing required field: {field}")

    # Validate name
    if "name" in app and not isinstance(app["name"], str):
        errors.append(f"{app_prefix}: Field 'name' must be a string")

    # Validate id
    if "id" in app:
        if not isinstance(app["id"], str):
            errors.append(f"{app_prefix}: Field 'id' must be a string")
        elif not app["id"]:
            errors.append(f"{app_prefix}: Field 'id' cannot be empty")

    # Validate source
    if "source" not in app:
        # Already reported missing field, but continue to check other things
        pass
    else:
        source = app["source"]
        if not isinstance(source, dict):
            errors.append(f"{app_prefix}.source: Must be a dictionary")
        else:
            # Check strategy field
            if "strategy" not in source:
                errors.append(f"{app_prefix}.source: Missing required field: strategy")
            else:
                strategy_name = source["strategy"]
                if not isinstance(strategy_name, str):
                    errors.append(f"{app_prefix}.source.strategy: Must be a string")
                else:
                    logger.verbose(
                        "VALIDATION",
                        f"App '{app.get('name', 'unnamed')}' uses strategy: {strategy_name}",
                    )

                    # Check if strategy exists
                    try:
                        strategy = get_strategy(strategy_name)
                    except ConfigError as err:
                        errors.append(f"{app_prefix}.source.strategy: {err}")
                    else:
                        # Validate strategy-specific configuration
                        if hasattr(strategy, "validate_config"):
                            try:
                                config_errors = strategy.validate_config(app)
                                for error in config_errors:
                                    errors.append(f"{app_prefix}: {error}")
                            except Exception as err:
                                errors.append(
                                    f"{app_prefix}: Strategy validation failed: {err}"
                                )

    # Validate win32 configuration
    _validate_win32_config(app, app_prefix, errors, warnings)

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
