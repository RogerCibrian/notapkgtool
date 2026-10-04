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

from napt.cli.common import add_output_flags, add_state_dir


def cmd_discover(args: argparse.Namespace) -> int:
    """Handler for 'napt discover' command.

    Discovers the latest version of an application by querying the source
    and downloading the installer. This command validates the recipe YAML,
    uses the configured discovery strategy to find the latest version,
    downloads the installer (or reuses the one an earlier run downloaded),
    extracts version information, and records the release as a pending
    publication candidate in deployment state when it differs from the
    published version.

    Args:
        args: Parsed command-line arguments containing
            recipe path, output directory, deployment state directory,
            and flags.

    Returns:
        Exit code (0 for success).

    Note:
        Downloads installer file to output_dir (or reuses an earlier
        download). Updates the app's deployment state file with the
        pending release. Prints progress and results to stdout. Failures
        raise NAPT errors for [run_handler][napt.cli.common.run_handler]
        to report.

    """
    from napt.discovery.manager import discover_recipe

    recipe_path = args.recipe.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else None

    print(f"Discovering version for recipe: {recipe_path}")
    if output_dir:
        print(f"Output directory: {output_dir}")
    print()

    result = discover_recipe(
        recipe_path,
        output_dir,
        state_dir=args.state_dir,
        stateless=args.stateless,
    )

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
        type=Path,
        help="Path to the recipe YAML file",
    )
    parser_discover.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save downloaded files (default: from config or ./downloads)",
    )
    add_state_dir(
        parser_discover,
        "State root; deployment state is written to <dir>/deployment/ "
        "(default: directories.state, ./state)",
    )
    parser_discover.add_argument(
        "--stateless",
        action="store_true",
        help="Do not read or write deployment state (no pending release is recorded)",
    )
    add_output_flags(parser_discover)
    parser_discover.set_defaults(func=cmd_discover)
