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

"""The `napt discover` command.

Finds the latest version of an application with the configured discovery
strategy and downloads the installer.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from napt.discovery.manager import discover_recipe
from napt.exceptions import ConfigError, NAPTError, NetworkError, PackagingError
from napt.logging import get_logger, set_global_logger


def cmd_discover(args: argparse.Namespace) -> int:
    """Handler for 'napt discover' command.

    Discovers the latest version of an application by querying the source
    and downloading the installer. This command validates the recipe YAML,
    uses the configured discovery strategy to find the latest version,
    downloads the installer (or uses cached version via ETag), extracts
    version information, updates the discovery cache, and records the
    release as a pending publication candidate in deployment state when it
    differs from the published version.

    Args:
        args: Parsed command-line arguments containing
            recipe path, output directory, cache file path, deployment
            state directory, and flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    Note:
        Downloads installer file to output_dir (or uses cached version).
        Updates the discovery cache with version and ETag information and
        the app's deployment state file with the pending release. Prints
        progress and results to stdout. Prints errors with optional
        traceback if verbose/debug.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else None

    if not recipe_path.exists():
        print(f"Error: Recipe file not found: {recipe_path}")
        return 1

    print(f"Discovering version for recipe: {recipe_path}")
    if output_dir:
        print(f"Output directory: {output_dir}")
    print()

    try:
        result = discover_recipe(
            recipe_path,
            output_dir,
            cache_file=args.cache_file,
            state_dir=args.state_dir,
            stateless=args.stateless,
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
    print(f"App Name:        {result.app_name}")
    print(f"App ID:          {result.app_id}")
    print(f"Strategy:        {result.strategy}")
    print(f"Version:         {result.version}")
    print(f"Version Source:  {result.version_source}")
    print(f"File Path:       {result.file_path}")
    print(f"SHA-256:         {result.sha256}")
    print(f"Status:          {result.status}")
    print("=" * 70)
    print()
    print("[SUCCESS] Version discovered successfully!")

    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'discover' command parser.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_discover = subparsers.add_parser(
        "discover",
        help="Discover latest version and download installer",
        description=(
            "Find the latest version using the configured discovery strategy "
            "and download the installer.\n\n"
            "Examples:\n"
            "  napt discover recipes/Google/chrome.yaml\n"
            "  napt discover recipes/Google/chrome.yaml --verbose\n"
            "  napt discover recipes/Google/chrome.yaml --stateless\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_discover.add_argument(
        "recipe",
        help="Path to the recipe YAML file",
    )
    parser_discover.add_argument(
        "--output-dir",
        default=None,
        help="Directory to save downloaded files (default: from config or ./downloads)",
    )
    parser_discover.add_argument(
        "--cache-file",
        type=Path,
        default=None,
        help=(
            "Discovery cache file for version tracking and ETag caching "
            "(default: cache/discovery.json from directories.cache)"
        ),
    )
    parser_discover.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=(
            "Directory for per-app deployment state files "
            "(default: state/deployment from directories.state)"
        ),
    )
    parser_discover.add_argument(
        "--stateless",
        action="store_true",
        help=(
            "Disable the discovery cache and deployment state writes "
            "(always download full files, record nothing)"
        ),
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
