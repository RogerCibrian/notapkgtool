"""
Command-line interface for NAPT.

This module provides the main CLI entry point for the napt tool, offering
commands for recipe validation, package building, and deployment management.

Commands
--------
validate : command
    Validate recipe syntax and configuration without making network calls.
    This command checks that a recipe is correctly formatted and that all
    required fields are present.

discover : command
    Discover the latest version by downloading the installer and extracting
    version information. This command verifies that a recipe is correctly
    configured, that the source is accessible, and tracks state for caching.

Future commands:
    build  : Build a PSADT package from a recipe
    upload : Upload a package to Microsoft Intune
    sync   : Full workflow (discover -> build -> upload)

Usage Examples
--------------
Validate recipe syntax:
    $ napt validate recipes/Google/chrome.yaml

Discover latest version:
    $ napt discover recipes/Google/chrome.yaml

Discover with custom output directory:
    $ napt discover recipes/Google/chrome.yaml --output-dir ./cache

Enable verbose output:
    $ napt discover recipes/Google/chrome.yaml --verbose

Enable debug output:
    $ napt discover recipes/Google/chrome.yaml --debug

Exit Codes
----------
0 : Success
1 : Error (configuration, download, or validation failure)

Notes
-----
- The CLI uses argparse for command parsing (stdlib, zero dependencies).
- Commands are registered with subparsers for clean organization.
- Each command has its own handler function (cmd_<command>).
- Verbose mode shows full tracebacks on errors for debugging.
- Debug mode implies verbose mode and shows detailed configuration dumps.
"""

from __future__ import annotations

import argparse
from importlib.metadata import version
from pathlib import Path
import sys

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

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments containing:
        - recipe : Path to recipe YAML file
        - verbose : Whether to show validation progress

    Returns
    -------
    int
        Exit code: 0 for valid recipe, 1 for invalid.

    Side Effects
    ------------
    - Prints validation results to stdout
    - Prints errors/warnings to stdout
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
            print(f"  ⚠ {warning}")
        print()

    # Show errors if any
    if result["errors"]:
        print(f"Errors ({len(result['errors'])}):")
        for error in result["errors"]:
            print(f"  ✗ {error}")
        print()

    print("=" * 70)

    if result["status"] == "valid":
        print()
        print("[SUCCESS] Recipe is valid!")
        return 0
    else:
        print()
        print(f"[FAILED] Recipe validation failed with {len(result['errors'])} error(s).")
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

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments containing:
        - recipe : Path to recipe YAML file
        - output_dir : Directory for downloaded files
        - state_file : Path to state file for caching
        - stateless : Whether to disable state tracking
        - verbose : Whether to show progress updates
        - debug : Whether to show detailed debugging output

    Returns
    -------
    int
        Exit code: 0 for success, 1 for failure.

    Side Effects
    ------------
    - Downloads installer file to output_dir (or uses cached version)
    - Updates state file with version and ETag information
    - Prints progress and results to stdout
    - Prints errors to stdout (with optional traceback if verbose/debug)
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

    # Parse and dispatch
    args = parser.parse_args()

    # Call the appropriate command handler
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
