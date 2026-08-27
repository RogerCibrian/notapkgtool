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

"""The `napt package` command.

Packages a PSADT build into a .intunewin file for Intune deployment.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from napt.build.packager import create_intunewin
from napt.config.loader import load_effective_config
from napt.exceptions import ConfigError, NAPTError, NetworkError, PackagingError
from napt.logging import get_logger, set_global_logger


def _resolve_build_dir_from_recipe(
    recipe_path: Path,
    version: str | None = None,
    builds_dir: Path | None = None,
) -> Path:
    """Infer the PSADT build version directory from a recipe.

    Loads the effective config from the recipe, derives the build output
    directory, and returns the version directory to pass to create_intunewin.

    Args:
        recipe_path: Path to the recipe YAML file.
        version: Specific version to target (e.g., "144.0.7559.110").
            If None, picks the most recently modified version directory
            that contains a packagefiles/ subdirectory.
        builds_dir: Directory containing builds. If None, reads from
            config directories.build.

    Returns:
        Path to the version directory (e.g., builds/napt-chrome/144.0.7559.110/).

    Raises:
        ConfigError: If the recipe cannot be loaded, the specified version
            does not exist, no builds exist for the app, or no version
            directory contains a packagefiles/ folder.

    """
    config = load_effective_config(recipe_path)
    app_id = config["id"]
    build_output_dir = (
        builds_dir if builds_dir is not None else Path(config["directories"]["build"])
    )
    app_build_dir = build_output_dir / app_id

    if not app_build_dir.exists():
        raise ConfigError(
            f"No builds found for '{app_id}' in {build_output_dir}. "
            "Run 'napt build' first."
        )

    if version is not None:
        specific_dir = app_build_dir / version
        if not specific_dir.is_dir() or not (specific_dir / "packagefiles").is_dir():
            raise ConfigError(
                f"Build version '{version}' not found for '{app_id}' "
                f"in {app_build_dir}. Run 'napt build' first."
            )
        return specific_dir

    # Find version directories that contain a packagefiles/ subdirectory,
    # sorted by modification time (most recent first).
    version_dirs = sorted(
        (
            d
            for d in app_build_dir.iterdir()
            if d.is_dir() and (d / "packagefiles").is_dir()
        ),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    if not version_dirs:
        raise ConfigError(
            f"No completed builds found for '{app_id}' in {app_build_dir}. "
            "Run 'napt build' first."
        )

    return version_dirs[0]


def cmd_package(args: argparse.Namespace) -> int:
    """Handler for 'napt package' command.

    Creates a .intunewin package from a PSADT build for the given recipe.
    Infers the build directory from the recipe's app ID, removes any
    previously packaged version (single-slot), copies detection scripts
    alongside the .intunewin file so 'napt upload' is self-contained, and
    optionally cleans the source build directory after packaging.

    Args:
        args: Parsed command-line arguments containing recipe path, version,
            output directory, clean flag, and debug flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    Note:
        Without --version, picks the most recently modified build. Run
        'napt build' before 'napt package'. Downloads IntuneWinAppUtil.exe
        if not cached. Optionally removes the build directory if --clean-source.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()
    builds_dir = Path(args.builds_dir).resolve() if args.builds_dir else None

    if not recipe_path.exists():
        print(f"Error: Recipe file not found: {recipe_path}")
        return 1

    try:
        build_dir = _resolve_build_dir_from_recipe(
            recipe_path, version=args.version, builds_dir=builds_dir
        )
    except ConfigError as err:
        print(f"Error: {err}")
        return 1

    config = load_effective_config(recipe_path)

    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else Path(config["directories"]["package"])
    )
    tool_release = config["intunewin"]["release"]

    print(f"Creating .intunewin package from: {build_dir}")
    print(f"Output directory: {output_dir}")
    print()

    try:
        result = create_intunewin(
            build_dir,
            output_dir=output_dir,
            clean_source=args.clean_source,
            tool_release=tool_release,
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
    print(f"App ID:          {result.app_id}")
    print(f"Version:         {result.version}")
    print(f"Package Path:    {result.package_path}")
    if args.clean_source:
        print(f"Build Directory: {result.build_dir} (removed)")
    else:
        print(f"Build Directory: {result.build_dir}")
    print(f"Status:          {result.status}")
    print("=" * 70)
    print()
    print("[SUCCESS] .intunewin package created successfully!")

    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'package' command parser.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_package = subparsers.add_parser(
        "package",
        help="Create .intunewin package from a PSADT build",
        description=(
            "Package a PSADT build for a recipe into a .intunewin file for "
            "Intune deployment. Without --version, packages the most recently "
            "modified build. Only one packaged version is kept on disk per app "
            "(previous version is removed automatically).\n\n"
            "Examples:\n"
            "  napt package recipes/Google/chrome.yaml\n"
            "  napt package recipes/Google/chrome.yaml --version 130.0.6723.116\n"
            "  napt package recipes/Google/chrome.yaml --clean-source\n"
            "  napt package recipes/Google/chrome.yaml --verbose\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_package.add_argument(
        "recipe",
        help="Path to the recipe YAML file",
    )
    parser_package.add_argument(
        "--version",
        default=None,
        metavar="VERSION",
        help="Specific build version to package (default: most recent build)",
    )
    parser_package.add_argument(
        "--builds-dir",
        default=None,
        help=(
            "Directory containing the PSADT build " "(default: from config or ./builds)"
        ),
    )
    parser_package.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Parent directory for package output "
            "(default: from config or ./packages)"
        ),
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
