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

Checks recipe YAML for syntax errors and configuration issues without
downloading files or making network calls.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from napt.config.loader import load_effective_config
from napt.logging import get_logger, set_global_logger
from napt.validation import validate_recipe


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
            # Leaf value — print provenance
            cfg_value = config.get(key)
            value_repr = repr(cfg_value)
            if len(value_repr) > 60:
                value_repr = value_repr[:57] + "..."
            print(f"  {full_key}: {value_repr} ({prov_value})")


def cmd_validate(args: argparse.Namespace) -> int:
    """Handler for 'napt validate' command.

    Validates recipe syntax and configuration without downloading files or
    making network calls. This is useful for quick feedback during recipe
    development and for CI/CD pre-checks.

    Args:
        args: Parsed command-line arguments containing
            recipe path and verbose flag.

    Returns:
        Exit code (0 for valid recipe, 1 for invalid).

    Note:
        Prints validation results, errors, and warnings to stdout.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()

    print(f"Validating recipe: {recipe_path}")
    print()

    # Validate the recipe
    result = validate_recipe(recipe_path)

    # Display results
    print("=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"Recipe:      {result.recipe_path}")
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

    # Show provenance in debug mode (useful for both valid and invalid recipes)
    if args.debug:
        try:
            config = load_effective_config(recipe_path)
            provenance = config.get("_provenance")
            if provenance:
                print()
                print("CONFIGURATION PROVENANCE")
                print("-" * 70)
                _print_provenance(config, provenance)
                print("-" * 70)
        except Exception:
            pass  # Best-effort; config may fail to load for invalid recipes

    if result.status == "valid":
        print()
        print("[SUCCESS] Recipe is valid!")
        return 0
    else:
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
            "Check recipe YAML for syntax errors and configuration issues "
            "without making network calls.\n\n"
            "Examples:\n"
            "  napt validate recipes/Google/chrome.yaml\n"
            "  napt validate recipes/Google/chrome.yaml --verbose\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_validate.add_argument(
        "recipe",
        help="Path to the recipe YAML file",
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
