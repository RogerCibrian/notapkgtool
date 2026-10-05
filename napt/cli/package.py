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

Packages a PSADT build into a .intunewin file for Intune deployment. The
build to package is the one for the release deployment state records
(pending, else published), the same release `napt build` built, so the
command never has to guess among the builds on disk.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from napt.cli.common import add_output_flags, add_state_dir, print_results
from napt.exceptions import ConfigError


def _completed_builds(app_build_dir: Path) -> list[Path]:
    """Lists the version folders under an app's builds that hold a build."""
    return sorted(
        d
        for d in app_build_dir.iterdir()
        if d.is_dir() and (d / "packagefiles").is_dir()
    )


def _resolve_build(
    config: dict[str, Any],
    version: str | None = None,
    builds_dir: Path | None = None,
    state_dir: Path | None = None,
) -> tuple[Path, str | None]:
    """Chooses the build to package and the installer hash it must carry.

    The release comes from deployment state (pending, else published), so
    the choice is the same on every machine that has the state file. With
    no recorded release, the only completed build is used; several builds
    then need ``--version``, since picking one by modification time would
    package whichever was touched last.

    Args:
        config: The recipe's effective configuration.
        version: Specific version to package. When it is the recorded
            release's version, the build is still verified against that
            release's hash.
        builds_dir: Directory containing builds. If None, reads from
            config directories.build.
        state_dir: State root. If None, reads from config directories.state.

    Returns:
        The build version directory, and the hash of the recorded release
            the build must match (None when no release is recorded or the
            chosen version is another one).

    Raises:
        ConfigError: If no builds exist for the app, the recorded or
            requested version has no completed build, or several builds
            exist and none is recorded.
        StateError: If the deployment state file is corrupted.

    """
    from napt.state.deployment import working_release

    app_id = config["id"]
    build_output_dir = (
        builds_dir if builds_dir is not None else Path(config["directories"]["build"])
    )
    app_build_dir = build_output_dir / app_id
    if state_dir is None:
        state_dir = Path(config["directories"]["state"])

    if not app_build_dir.exists():
        raise ConfigError(
            f"No builds found for '{app_id}' in {build_output_dir}. "
            "Run 'napt build' first."
        )

    release = working_release(state_dir, app_id)

    if version is None and release is not None:
        version = release["version"]
        specific_dir = app_build_dir / version
        if not (specific_dir / "packagefiles").is_dir():
            raise ConfigError(
                f"Deployment state records release {version} for '{app_id}', "
                f"but there is no build of it in {app_build_dir}. Run "
                "'napt build' first."
            )
        return specific_dir, release["sha256"]

    if version is not None:
        specific_dir = app_build_dir / version
        if not (specific_dir / "packagefiles").is_dir():
            raise ConfigError(
                f"Build version '{version}' not found for '{app_id}' "
                f"in {app_build_dir}. Run 'napt build' first."
            )
        expected = (
            release["sha256"]
            if release is not None and release["version"] == version
            else None
        )
        return specific_dir, expected

    builds = _completed_builds(app_build_dir)
    if not builds:
        raise ConfigError(
            f"No completed builds found for '{app_id}' in {app_build_dir}. "
            "Run 'napt build' first."
        )
    if len(builds) > 1:
        names = ", ".join(d.name for d in builds)
        raise ConfigError(
            f"'{app_id}' has no recorded release and several builds "
            f"({names}). Run 'napt discover' to record the release, or pass "
            "--version to choose one."
        )
    return builds[0], None


def cmd_package(args: argparse.Namespace) -> int:
    """Handler for 'napt package' command.

    Creates a .intunewin package from a PSADT build for the given recipe.
    Packages the build of the release deployment state records, verifies
    it against the recorded installer hash, replaces that version's package
    folder, and copies the detection scripts alongside the .intunewin file
    so 'napt upload' is self-contained.

    Args:
        args: Parsed command-line arguments containing recipe path, version,
            directories, and debug flags.

    Returns:
        Exit code (0 for success).

    Note:
        Run 'napt build' before 'napt package'. Downloads IntuneWinAppUtil.exe
        if not cached. Failures raise NAPT errors for
        [run_handler][napt.cli.common.run_handler] to report.

    """
    from napt.build.packager import create_intunewin
    from napt.config.loader import load_effective_config

    recipe_path = args.recipe.resolve()
    builds_dir = args.builds_dir.resolve() if args.builds_dir else None
    state_dir = args.state_dir.resolve() if args.state_dir else None

    config = load_effective_config(recipe_path)
    build_dir, expected_sha256 = _resolve_build(
        config,
        version=args.version,
        builds_dir=builds_dir,
        state_dir=state_dir,
    )

    output_dir = (
        args.output_dir if args.output_dir else Path(config["directories"]["package"])
    )
    tool_release = config["intunewin"]["release"]

    print(f"Creating .intunewin package from: {build_dir}")
    print(f"Output directory: {output_dir}")
    print()

    result = create_intunewin(
        build_dir,
        cache_dir=Path(config["directories"]["cache"]),
        output_dir=output_dir,
        tool_release=tool_release,
        expected_sha256=expected_sha256,
    )

    print_results(
        "PACKAGE RESULTS",
        [
            ("App ID", result.app_id),
            ("Version", result.version),
            ("Package Path", result.package_path),
            ("Build Directory", result.build_dir),
        ],
        ".intunewin package created successfully!",
    )
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
            "Intune deployment. Packages the build of the release recorded in "
            "deployment state (pending, else published); with no recorded "
            "release, the only build, or the one named by --version. The "
            "version's package folder is replaced; other versions are left "
            "alone.\n\n"
            "Examples:\n"
            "  napt package recipes/Google/chrome.yaml\n"
            "  napt package recipes/Google/chrome.yaml --version 130.0.6723.116\n"
            "  napt package recipes/Google/chrome.yaml --verbose\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_package.add_argument(
        "recipe",
        type=Path,
        help="Path to the recipe YAML file",
    )
    parser_package.add_argument(
        "--version",
        default=None,
        metavar="VERSION",
        help="Build version to package (default: the recorded release)",
    )
    parser_package.add_argument(
        "--builds-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing the PSADT build " "(default: from config or ./builds)"
        ),
    )
    parser_package.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Parent directory for package output "
            "(default: from config or ./packages)"
        ),
    )
    add_state_dir(
        parser_package,
        "State root whose deployment/ folder records the release "
        "(default: from config or ./state)",
    )
    add_output_flags(parser_package)
    parser_package.set_defaults(func=cmd_package)
