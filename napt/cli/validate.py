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

"""The `napt validate` command.

Checks a recipe's effective configuration (org.yaml, vendor defaults,
parent, recipe) for syntax errors and configuration issues without
downloading files or making network calls. Given a directory, checks every
recipe under it and reports two files that resolve to the same id.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from napt.config.loader import load_effective_config
from napt.exceptions import NAPTError
from napt.logging import get_logger, set_global_logger
from napt.results import ValidationResult
from napt.validation import validate_recipe, validate_recipes


def _print_provenance(
    config: dict[str, Any], provenance: dict[str, Any], prefix: str = ""
) -> None:
    """Prints provenance information showing which layer set each config value.

    Args:
        config: The merged configuration dictionary.
        provenance: The provenance dictionary mirroring config structure.
        prefix: Key path prefix for nested sections (used in recursion).
    """
    for key in sorted(provenance.keys()):
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        prov_value = provenance[key]

        if isinstance(prov_value, dict):
            # Recurse into nested sections
            cfg_value = config.get(key, {})
            if isinstance(cfg_value, dict):
                _print_provenance(cfg_value, prov_value, full_key)
        else:
            # Leaf value: print provenance
            cfg_value = config.get(key)
            value_repr = repr(cfg_value)
            if len(value_repr) > 60:
                value_repr = value_repr[:57] + "..."
            print(f"  {full_key}: {value_repr} ({prov_value})")


def _print_provenance_block(recipe_path: Path) -> None:
    """Prints the provenance of a recipe's effective configuration.

    Args:
        recipe_path: The recipe whose configuration to describe.
    """
    try:
        config = load_effective_config(recipe_path)
        provenance = config.get("_provenance")
        if provenance:
            print()
            print("CONFIGURATION PROVENANCE")
            print("-" * 70)
            _print_provenance(config, provenance)
            print("-" * 70)
    except NAPTError as err:
        # An invalid recipe cannot be merged; say so rather than hide it.
        print()
        print(f"Provenance unavailable: {err}")


def _print_single(result: ValidationResult) -> None:
    """Prints the full report for one recipe.

    Args:
        result: The recipe's validation result.
    """
    print("=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"Recipe:      {result.recipe_path}")
    if result.parent_path:
        print(f"Parent:      {result.parent_path}")
    print(f"Status:      {result.status.upper()}")
    print(f"App Count:   {result.app_count}")
    print()

    # Show warnings if any
    if result.warnings:
        print(f"Warnings ({len(result.warnings)}):")
        for warning in result.warnings:
            print(f"  [WARNING] {warning}")
        print()

    # Show errors if any
    if result.errors:
        print(f"Errors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  [X] {error}")
        print()

    print("=" * 70)


def _display_path(result: ValidationResult, root: Path) -> str:
    """Names a recipe relative to the directory being validated.

    Args:
        result: The recipe's validation result.
        root: The directory given on the command line.

    Returns:
        The relative path when the recipe is under the root, else the path
            as recorded.
    """
    try:
        return str(Path(result.recipe_path).relative_to(root))
    except ValueError:
        return result.recipe_path


def _print_directory(results: list[ValidationResult], root: Path) -> None:
    """Prints one line per recipe with its errors and warnings beneath.

    Args:
        results: One result per recipe file.
        root: The directory given on the command line.
    """
    for result in results:
        tag = "[OK]  " if result.status == "valid" else "[FAIL]"
        print(f"{tag} {_display_path(result, root)}")
        for error in result.errors:
            print(f"       [X] {error}")
        for warning in result.warnings:
            print(f"       [WARNING] {warning}")


def cmd_validate(args: argparse.Namespace) -> int:
    """Handler for 'napt validate' command.

    Validates recipe syntax and configuration without downloading files or
    making network calls. This is useful for quick feedback during recipe
    development and for CI/CD pre-checks.

    Args:
        args: Parsed command-line arguments containing
            the recipe or directory path and verbose flag.

    Returns:
        Exit code (0 when every recipe is valid, 1 otherwise).

    Note:
        Prints validation results, errors, and warnings to stdout.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()

    if recipe_path.is_dir():
        print(f"Validating recipes under: {recipe_path}")
        print()
        results = validate_recipes(recipe_path)
        _print_directory(results, recipe_path)
        if args.debug:
            for result in results:
                if result.status == "valid":
                    print()
                    print(f"Recipe: {_display_path(result, recipe_path)}")
                    _print_provenance_block(Path(result.recipe_path))
        failed = sum(1 for result in results if result.status != "valid")
        print()
        print("=" * 70)
        if failed:
            print(f"[FAILED] {failed} of {len(results)} recipe(s) failed validation.")
            return 1
        print(f"[SUCCESS] All {len(results)} recipe(s) are valid.")
        return 0

    print(f"Validating recipe: {recipe_path}")
    print()

    result = validate_recipe(recipe_path)
    _print_single(result)

    # Show provenance in debug mode (useful for both valid and invalid recipes)
    if args.debug:
        _print_provenance_block(recipe_path)

    if result.status == "valid":
        print()
        print("[SUCCESS] Recipe is valid!")
        return 0
    print()
    print(f"[FAILED] Recipe validation failed with {len(result.errors)} error(s).")
    return 1


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'validate' command parser.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_validate = subparsers.add_parser(
        "validate",
        help="Validate recipe syntax and configuration (no downloads)",
        description=(
            "Check a recipe's effective configuration (org.yaml, vendor "
            "defaults, parent, recipe) for syntax errors and configuration "
            "issues without making network calls. Given a directory, check "
            "every recipe under it.\n\n"
            "Examples:\n"
            "  napt validate recipes/Google/chrome.yaml\n"
            "  napt validate recipes/\n"
            "  napt validate recipes/Google/chrome.yaml --verbose\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_validate.add_argument(
        "recipe",
        help="Path to a recipe YAML file, or a directory of recipes",
    )
    parser_validate.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show validation progress and details",
    )
    parser_validate.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_validate.set_defaults(func=cmd_validate)
