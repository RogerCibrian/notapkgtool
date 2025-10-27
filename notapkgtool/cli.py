"""
Command-line interface for NAPT.

This module provides the main CLI entry point for the napt tool, offering
commands for recipe validation, package building, and deployment management.

Commands
--------
check : command
    Validate a recipe by downloading the installer and extracting version info.
    This command verifies that a recipe is correctly configured and that the
    source URL is accessible.

Future commands:
    build  : Build a PSADT package from a recipe
    upload : Upload a package to Microsoft Intune
    sync   : Full workflow (check -> build -> upload)

Usage Examples
--------------
Validate a recipe:
    $ napt check recipes/Google/chrome.yaml

Validate with custom output directory:
    $ napt check recipes/Google/chrome.yaml --output-dir ./cache

Enable verbose error output:
    $ napt check recipes/Google/chrome.yaml --verbose

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
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from notapkgtool.core import check_recipe

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


def cmd_check(args: argparse.Namespace) -> int:
    """
    Handler for 'napt check' command.

    Downloads the installer specified in a recipe and extracts version
    information. This validates that:
      - The recipe YAML is correctly formatted
      - Configuration merging works properly
      - The source URL is accessible
      - The version can be extracted from the downloaded file

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments containing:
        - recipe : Path to recipe YAML file
        - output_dir : Directory for downloaded files
        - verbose : Whether to show progress updates
        - debug : Whether to show detailed debugging output

    Returns
    -------
    int
        Exit code: 0 for success, 1 for failure.

    Side Effects
    ------------
    - Downloads installer file to output_dir
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

    print(f"Checking recipe: {recipe_path}")
    print(f"Output directory: {output_dir}")
    print()

    try:
        result = check_recipe(
            recipe_path, output_dir, verbose=args.verbose, debug=args.debug
        )
    except Exception as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    # Display results
    print("=" * 70)
    print("CHECK RESULTS")
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
    print("[SUCCESS] Recipe validated successfully!")

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
        version="napt 0.1.0",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=True,
    )

    # 'check' command
    parser_check = subparsers.add_parser(
        "check",
        help="Validate a recipe by downloading and extracting version",
        description="Download the installer specified in a recipe and extract its version.",
    )
    parser_check.add_argument(
        "recipe",
        help="Path to the recipe YAML file",
    )
    parser_check.add_argument(
        "--output-dir",
        default="./downloads",
        help="Directory to save downloaded files (default: ./downloads)",
    )
    parser_check.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_check.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_check.set_defaults(func=cmd_check)

    # Parse and dispatch
    args = parser.parse_args()

    # Call the appropriate command handler
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
