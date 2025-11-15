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

"""Command-line interface for NAPT.

This module provides the main CLI entry point for the napt tool, offering
commands for recipe validation, package building, and deployment management.

Commands:

    validate: Validate recipe syntax and configuration
    discover: Discover latest version and download installer
    build: Build PSADT package from recipe
    package: Create .intunewin package for Intune

Example:
    Validate recipe syntax:
        ```bash
        $ napt validate recipes/Google/chrome.yaml
        ```

    Discover latest version:
        ```bash
        $ napt discover recipes/Google/chrome.yaml
        ```

    Build PSADT package:
        ```bash
        $ napt build recipes/Google/chrome.yaml
        ```

    Create .intunewin package:
        ```bash
        $ napt package builds/napt-chrome/142.0.7444.60/
        ```

    Enable verbose output:
        ```bash
        $ napt discover recipes/Google/chrome.yaml --verbose
        ```

    Enable debug output:
        ```bash
        $ napt discover recipes/Google/chrome.yaml --debug
        ```

Exit Codes:

- 0: Success
- 1: Error (configuration, download, or validation failure)

Note:
    The CLI uses argparse for command parsing (stdlib, zero dependencies).
    Commands are registered with subparsers for clean organization.
    Each command has its own handler function (cmd_<command>).
    Verbose mode shows full tracebacks on errors for debugging.
    Debug mode implies verbose mode and shows detailed configuration dumps.

"""

from __future__ import annotations

import argparse
from importlib.metadata import version
from pathlib import Path
import sys

from notapkgtool.build import build_package, create_intunewin
from notapkgtool.core import discover_recipe
from notapkgtool.exceptions import (
    ConfigError,
    NAPTError,
    NetworkError,
    PackagingError,
)
from notapkgtool.logging import get_logger, set_global_logger
from notapkgtool.validation import validate_recipe


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
    logger = get_logger(verbose=args.verbose, debug=False)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()

    print(f"Validating recipe: {recipe_path}")
    print()

    # Validate the recipe
    result = validate_recipe(recipe_path, verbose=args.verbose)

    # Display results
    print("=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"Recipe:      {result['recipe_path']}")
    print(f"Status:      {result['status'].upper()}")
    print(f"App Count:   {result['app_count']}")
    print()

    # Show warnings if any
    if result["warnings"]:
        print(f"Warnings ({len(result['warnings'])}):")
        for warning in result["warnings"]:
            print(f"  [WARNING] {warning}")
        print()

    # Show errors if any
    if result["errors"]:
        print(f"Errors ({len(result['errors'])}):")
        for error in result["errors"]:
            print(f"  [X] {error}")
        print()

    print("=" * 70)

    if result["status"] == "valid":
        print()
        print("[SUCCESS] Recipe is valid!")
        return 0
    else:
        print()
        print(
            f"[FAILED] Recipe validation failed with {len(result['errors'])} error(s)."
        )
        return 1


def cmd_discover(args: argparse.Namespace) -> int:
    """Handler for 'napt discover' command.

    Discovers the latest version of an application by querying the source
    and downloading the installer. This command validates the recipe YAML,
    uses the configured discovery strategy to find the latest version,
    downloads the installer (or uses cached version via ETag), extracts
    version information, and updates the state file with caching info.

    Args:
        args: Parsed command-line arguments containing
            recipe path, output directory, state file path, and flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    Note:
        Downloads installer file to output_dir (or uses cached version).
        Updates state file with version and ETag information. Prints progress
        and results to stdout. Prints errors with optional traceback if verbose/debug.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not recipe_path.exists():
        print(f"Error: Recipe file not found: {recipe_path}")
        return 1

    print(f"Discovering version for recipe: {recipe_path}")
    print(f"Output directory: {output_dir}")
    print()

    try:
        result = discover_recipe(
            recipe_path,
            output_dir,
            state_file=args.state_file if not args.stateless else None,
            stateless=args.stateless,
            verbose=args.verbose,
            debug=args.debug,
        )
    except (ConfigError, NetworkError, PackagingError) as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except NAPTError as err:
        # Catch any other NAPT errors we might have missed
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    # Display results
    print("=" * 70)
    print("DISCOVERY RESULTS")
    print("=" * 70)
    print(f"App Name:        {result['app_name']}")
    print(f"App ID:          {result['app_id']}")
    print(f"Strategy:        {result['strategy']}")
    print(f"Version:         {result['version']}")
    print(f"Version Source:  {result['version_source']}")
    print(f"File Path:       {result['file_path']}")
    print(f"SHA-256:         {result['sha256']}")
    print(f"Status:          {result['status']}")
    print("=" * 70)
    print()
    print("[SUCCESS] Version discovered successfully!")

    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Handler for 'napt build' command.

    Builds a PSADT package from a recipe and downloaded installer. This command
    loads the recipe configuration, finds the downloaded installer, extracts
    version from the installer file (filesystem is truth), downloads/caches
    the specified PSADT release, creates build directory structure, copies
    PSADT files pristine from cache, generates Invoke-AppDeployToolkit.ps1
    with recipe values, copies installer to Files/ directory, and applies
    custom branding.

    Args:
        args: Parsed command-line arguments containing
            recipe path, downloads directory, output directory, and flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    Note:
        Creates build directory structure. Downloads PSADT release if not cached.
        Generates Invoke-AppDeployToolkit.ps1. Copies files to build directory.
        Prints progress and results to stdout.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()
    downloads_dir = Path(args.downloads_dir).resolve()
    output_dir = Path(args.output_dir) if args.output_dir else None

    if not recipe_path.exists():
        print(f"Error: Recipe file not found: {recipe_path}")
        return 1

    if not downloads_dir.exists():
        print(f"Error: Downloads directory not found: {downloads_dir}")
        print("Run 'napt discover' first to download the installer.")
        return 1

    print(f"Building PSADT package for recipe: {recipe_path}")
    print(f"Downloads directory: {downloads_dir}")
    if output_dir:
        print(f"Output directory: {output_dir}")
    print()

    try:
        result = build_package(
            recipe_path,
            downloads_dir=downloads_dir,
            output_dir=output_dir,
            verbose=args.verbose,
            debug=args.debug,
        )
    except (ConfigError, NetworkError, PackagingError) as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except NAPTError as err:
        # Catch any other NAPT errors we might have missed
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    # Display results
    print("=" * 70)
    print("BUILD RESULTS")
    print("=" * 70)
    print(f"App Name:        {result['app_name']}")
    print(f"App ID:          {result['app_id']}")
    print(f"Version:         {result['version']}")
    print(f"PSADT Version:   {result['psadt_version']}")
    print(f"Build Directory: {result['build_dir']}")
    print(f"Status:          {result['status']}")
    print("=" * 70)
    print()
    print("[SUCCESS] PSADT package built successfully!")

    return 0


def cmd_package(args: argparse.Namespace) -> int:
    """Handler for 'napt package' command.

    Creates a .intunewin package from a built PSADT directory. This command
    verifies the build directory has valid PSADT structure, downloads/caches
    IntuneWinAppUtil.exe if needed, runs IntuneWinAppUtil.exe to create
    .intunewin package, and optionally cleans the source build directory
    after packaging.

    Args:
        args: Parsed command-line arguments containing
            build directory path, output directory, clean flag, and debug flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    Note:
        Creates .intunewin file in output directory. Downloads IntuneWinAppUtil.exe
        if not cached. Optionally removes build directory if --clean-source.
        Prints progress and results to stdout.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    build_dir = Path(args.build_dir).resolve()
    output_dir = Path(args.output_dir) if args.output_dir else None

    if not build_dir.exists():
        print(f"Error: Build directory not found: {build_dir}")
        return 1

    print(f"Creating .intunewin package from: {build_dir}")
    if output_dir:
        print(f"Output directory: {output_dir}")
    print()

    try:
        result = create_intunewin(
            build_dir,
            output_dir=output_dir,
            clean_source=args.clean_source,
            verbose=args.verbose,
            debug=args.debug,
        )
    except (ConfigError, NetworkError, PackagingError) as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except NAPTError as err:
        # Catch any other NAPT errors we might have missed
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    # Display results
    print("=" * 70)
    print("PACKAGE RESULTS")
    print("=" * 70)
    print(f"App ID:          {result['app_id']}")
    print(f"Version:         {result['version']}")
    print(f"Package Path:    {result['package_path']}")
    if args.clean_source:
        print(f"Build Directory: {result['build_dir']} (removed)")
    else:
        print(f"Build Directory: {result['build_dir']}")
    print(f"Status:          {result['status']}")
    print("=" * 70)
    print()
    print("[SUCCESS] .intunewin package created successfully!")

    return 0


def main() -> None:
    """Main entry point for the napt CLI.

    This function is registered as the 'napt' console script in pyproject.toml.
    """
    parser = argparse.ArgumentParser(
        prog="napt",
        description="NAPT - Not a Pkg Tool for Windows/Intune packaging with PSADT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"napt {version('notapkgtool')}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=True,
    )

    # 'validate' command
    parser_validate = subparsers.add_parser(
        "validate",
        help="Validate recipe syntax and configuration (no downloads)",
        description="Check recipe YAML for syntax errors and configuration issues without making network calls.",
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
    parser_validate.set_defaults(func=cmd_validate)

    # 'discover' command
    parser_discover = subparsers.add_parser(
        "discover",
        help="Discover latest version and download installer",
        description="Find the latest version using the configured discovery strategy and download the installer.",
    )
    parser_discover.add_argument(
        "recipe",
        help="Path to the recipe YAML file",
    )
    parser_discover.add_argument(
        "--output-dir",
        default="./downloads",
        help="Directory to save downloaded files (default: ./downloads)",
    )
    parser_discover.add_argument(
        "--state-file",
        type=Path,
        default=Path("state/versions.json"),
        help="State file for version tracking and ETag caching (default: state/versions.json)",
    )
    parser_discover.add_argument(
        "--stateless",
        action="store_true",
        help="Disable state tracking (no caching, always download full files)",
    )
    parser_discover.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_discover.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_discover.set_defaults(func=cmd_discover)

    # 'build' command
    parser_build = subparsers.add_parser(
        "build",
        help="Build PSADT package from recipe and installer",
        description="Create a PSADT deployment package from a recipe and downloaded installer.",
    )
    parser_build.add_argument(
        "recipe",
        help="Path to the recipe YAML file",
    )
    parser_build.add_argument(
        "--downloads-dir",
        default="./downloads",
        help="Directory containing the downloaded installer (default: ./downloads)",
    )
    parser_build.add_argument(
        "--output-dir",
        default=None,
        help="Base directory for build output (default: from config or ./builds)",
    )
    parser_build.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_build.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_build.set_defaults(func=cmd_build)

    # 'package' command
    parser_package = subparsers.add_parser(
        "package",
        help="Create .intunewin package from PSADT build directory",
        description="Package a built PSADT directory into a .intunewin file for Intune deployment.",
    )
    parser_package.add_argument(
        "build_dir",
        help="Path to the built PSADT package directory",
    )
    parser_package.add_argument(
        "--output-dir",
        default=None,
        help="Directory for .intunewin output (default: packages/{app_id}/)",
    )
    parser_package.add_argument(
        "--clean-source",
        action="store_true",
        help="Remove the build directory after packaging",
    )
    parser_package.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_package.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_package.set_defaults(func=cmd_package)

    # Parse and dispatch
    args = parser.parse_args()

    # Call the appropriate command handler
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
