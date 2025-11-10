"""
Command-line interface for NAPT.

This module provides the main CLI entry point for the napt tool, offering
commands for recipe validation, package building, and deployment management.

Commands:

    validate: Validate recipe syntax and configuration without making network calls.
        This command checks that a recipe is correctly formatted and that all
        required fields are present.

    discover: Discover the latest version by downloading the installer and extracting
        version information. This command verifies that a recipe is correctly
        configured, that the source is accessible, and tracks state for caching.

    build: Build a PSADT package from a recipe and downloaded installer. Creates
        complete deployment package with generated scripts and branding.

    package: Create a .intunewin package from a built PSADT directory using
        Microsoft's IntuneWinAppUtil.exe tool.

    Future commands:
        upload: Upload a package to Microsoft Intune
        sync: Full workflow (discover -> build -> upload -> deploy)

Usage Examples:

    Validate recipe syntax:

        $ napt validate recipes/Google/chrome.yaml

    Discover latest version:

        $ napt discover recipes/Google/chrome.yaml

    Build PSADT package:

        $ napt build recipes/Google/chrome.yaml

    Create .intunewin package:

        $ napt package builds/napt-chrome/142.0.7444.60/

    Enable verbose output:

        $ napt discover recipes/Google/chrome.yaml --verbose

    Enable debug output:

        $ napt discover recipes/Google/chrome.yaml --debug

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
from notapkgtool.validation import validate_recipe

# Global verbose and debug flags set from CLI args
_verbose = False
_debug = False


def set_verbose(enabled: bool) -> None:
    """Set the global verbose flag."""
    global _verbose
    _verbose = enabled


def is_verbose() -> bool:
    """Check if verbose mode is enabled."""
    return _verbose


def set_debug(enabled: bool) -> None:
    """Set the global debug flag. Debug mode implies verbose mode."""
    global _debug, _verbose
    _debug = enabled
    if enabled:
        _verbose = True  # Debug implies verbose


def is_debug() -> bool:
    """Check if debug mode is enabled."""
    return _debug


def print_step(step: int, total: int, message: str) -> None:
    """Print a step indicator for non-verbose mode."""
    print(f"[{step}/{total}] {message}")


def print_verbose(prefix: str, message: str) -> None:
    """Print a verbose log message (only when verbose mode is active)."""
    if _verbose:
        print(f"[{prefix}] {message}")


def print_debug(prefix: str, message: str) -> None:
    """Print a debug log message (only when debug mode is active)."""
    if _debug:
        print(f"[{prefix}] {message}")


def cmd_validate(args: argparse.Namespace) -> int:
    """
    Handler for 'napt validate' command.

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
    # Set global verbose flag
    set_verbose(args.verbose)

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
    """
    Handler for 'napt discover' command.

    Discovers the latest version of an application by querying the source
    and downloading the installer. This command:
      - Validates the recipe YAML is correctly formatted
      - Uses the configured discovery strategy to find the latest version
      - Downloads the installer (or uses cached version via ETag)
      - Extracts version information from the downloaded file
      - Updates the state file with version and caching info

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
    # Set global verbose and debug flags
    set_verbose(args.verbose)
    set_debug(args.debug)

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
    except Exception as err:
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
    """
    Handler for 'napt build' command.

    Builds a PSADT package from a recipe and downloaded installer. This command:
      - Loads the recipe configuration
      - Finds the downloaded installer in downloads directory
      - Extracts version from the installer file (filesystem is truth)
      - Downloads/caches the specified PSADT release
      - Creates build directory structure
      - Copies PSADT files pristine from cache
      - Generates Invoke-AppDeployToolkit.ps1 with recipe values
      - Copies installer to Files/ directory
      - Applies custom branding

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
    # Set global verbose and debug flags
    set_verbose(args.verbose)
    set_debug(args.debug)

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
    except Exception as err:
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
    """
    Handler for 'napt package' command.

    Creates a .intunewin package from a built PSADT directory. This command:
      - Verifies the build directory has valid PSADT structure
      - Downloads/caches IntuneWinAppUtil.exe if needed
      - Runs IntuneWinAppUtil.exe to create .intunewin package
      - Optionally cleans the source build directory after packaging

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
    # Set global verbose and debug flags
    set_verbose(args.verbose)
    set_debug(args.debug)

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
    except Exception as err:
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
    """
    Main entry point for the napt CLI.

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
