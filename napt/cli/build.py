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

"""The `napt build` command.

Creates a PSADT deployment package from a recipe and a downloaded
installer.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from napt.cli.common import add_output_flags, add_state_dir


def cmd_build(args: argparse.Namespace) -> int:
    """Handler for 'napt build' command.

    Builds a PSADT package from a recipe and downloaded installer. This command
    loads the recipe configuration, reads the release to build from
    deployment state, finds the installer by its recorded hash, checks an MSI
    or MSIX version against its folder, downloads/caches the specified PSADT
    release, creates build directory structure, copies
    PSADT files pristine from cache, generates Invoke-AppDeployToolkit.ps1
    with recipe values, copies installer to Files/ directory, and applies
    custom branding.

    Args:
        args: Parsed command-line arguments containing
            recipe path, downloads directory, output directory, and flags.

    Returns:
        Exit code (0 for success).

    Note:
        Creates build directory structure. Downloads PSADT release if not cached.
        Generates Invoke-AppDeployToolkit.ps1. Copies files to build directory.
        Prints progress and results to stdout. Failures raise NAPT errors
        for [run_handler][napt.cli.common.run_handler] to report.

    """
    from napt.build.manager import build_package

    recipe_path = args.recipe.resolve()
    downloads_dir = args.downloads_dir.resolve() if args.downloads_dir else None
    output_dir = args.output_dir

    print(f"Building PSADT package for recipe: {recipe_path}")
    if downloads_dir:
        print(f"Downloads directory: {downloads_dir}")
    if output_dir:
        print(f"Output directory: {output_dir}")
    print()

    result = build_package(
        recipe_path,
        downloads_dir=downloads_dir,
        output_dir=output_dir,
        state_dir=args.state_dir,
    )

    # Display results
    print("=" * 70)
    print("BUILD RESULTS")
    print("=" * 70)
    print(f"App Name:        {result.app_name}")
    print(f"App ID:          {result.app_id}")
    print(f"Version:         {result.version}")
    print(f"PSADT Version:   {result.psadt_version}")
    print(f"Build Directory: {result.build_dir}")
    print(f"Status:          {result.status}")
    print("=" * 70)
    print()
    print("[SUCCESS] PSADT package built successfully!")

    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'build' command parser.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_build = subparsers.add_parser(
        "build",
        help="Build PSADT package from recipe and installer",
        description=(
            "Create a PSADT deployment package from a recipe and "
            "downloaded installer.\n\n"
            "Examples:\n"
            "  napt build recipes/Google/chrome.yaml\n"
            "  napt build recipes/Google/chrome.yaml --verbose\n"
            "  napt build recipes/Google/chrome.yaml --output-dir ./builds\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_build.add_argument(
        "recipe",
        type=Path,
        help="Path to the recipe YAML file",
    )
    parser_build.add_argument(
        "--downloads-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing the downloaded installer "
            "(default: from config or ./downloads)"
        ),
    )
    parser_build.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Base directory for build output (default: from config or ./builds)",
    )
    add_state_dir(
        parser_build,
        "State root; the release to build is read from <dir>/deployment/ "
        "(default: directories.state, ./state)",
    )
    add_output_flags(parser_build)
    parser_build.set_defaults(func=cmd_build)
