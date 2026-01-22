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


def validate_recipe(recipe_path: Path) -> ValidationResult:
    """Validate a recipe file without downloading anything.

    This function checks:

    1. YAML file can be parsed
    2. Required top-level fields are present
    3. apiVersion is supported
    4. App has required fields
    5. Discovery strategies exist
    6. Strategy-specific configuration is valid

    Does NOT:

    - Make network calls
    - Download files
    - Verify URLs are accessible
    - Check if versions can be extracted

    Args:
        recipe_path: Path to the recipe YAML file to validate.

    Returns:
        ValidationResult dataclass with the following fields:

            - status (str): Validation status, either "valid" (no errors) or "invalid"
                (has errors). Warnings do not affect status.
            - errors (list[str]): List of error messages found during validation. Empty
                list if recipe is valid. Each error describes a specific validation
                failure (e.g., missing required field, invalid strategy configuration).
            - warnings (list[str]): List of warning messages found during validation.
                Warnings indicate potential issues but do not prevent validation from
                passing (e.g., unsupported apiVersion, deprecated configuration).
            - app_count (int): Always 1 for valid recipes (single app format). Zero if recipe
                structure is invalid.
            - recipe_path (str): String path to the validated recipe file, useful for
                error reporting and logging.

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
