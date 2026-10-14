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

"""The `napt init` command.

Creates a new NAPT project structure with default configuration.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from napt.cli.common import add_output_flags
from napt.exceptions import ConfigError
from napt.logging import get_global_logger


def cmd_init(args: argparse.Namespace) -> int:
    """Handler for 'napt init' command.

    Initializes a new NAPT project by creating the directory structure and
    default configuration files. This command creates the recipes/ directory,
    defaults/ directory with org.yaml template, defaults/vendors/ directory,
    and state/deployment/ directory for per-app deployment state.

    Args:
        args: Parsed command-line arguments containing
            directory path, force flag, and debug flags.

    Returns:
        Exit code (0 for success).

    Note:
        By default, existing files are skipped (not overwritten).
        Use --force to backup existing files and create fresh ones.
        Failures raise NAPT errors for
        [run_handler][napt.cli.common.run_handler] to report.

    """
    target_dir = args.directory.resolve()

    print(f"Initializing NAPT project in: {target_dir}")
    print()

    created, skipped, backed_up = _create_layout(target_dir, args.force)

    # Display results
    print()
    print("=" * 70)
    print("INITIALIZATION RESULTS")
    print("=" * 70)
    print(f"Project Root:    {target_dir}")
    print()

    if created:
        print(f"Created ({len(created)}):")
        for item in created:
            print(f"  [OK] {item}")
        print()

    if backed_up:
        print(f"Backed Up ({len(backed_up)}):")
        for item in backed_up:
            print(f"  [OK] {item}")
        print()

    if skipped:
        print(f"Skipped ({len(skipped)}):")
        for item in skipped:
            print(f"  [SKIP] {item}")
        print()

    print("=" * 70)
    print()

    if skipped and not args.force:
        print("Note: Existing files were preserved. Use --force to overwrite.")
        print()

    print("[SUCCESS] Project initialized!")
    return 0


def _create_layout(
    target_dir: Path, force: bool
) -> tuple[list[str], list[str], list[str]]:
    """Creates the project folders and the org.yaml template.

    Args:
        target_dir: The project root.
        force: Whether to back up an existing org.yaml and write a fresh one.

    Returns:
        A tuple (created, skipped, backed_up), where
            created lists the relative paths this run made,
            skipped lists the ones that already existed and were left alone,
            backed_up lists the ones moved aside before being recreated.

    Raises:
        ConfigError: If a folder or file cannot be created there.
    """
    try:
        return _create_layout_files(target_dir, force)
    except OSError as err:
        raise ConfigError(
            f"Cannot initialize a project in {target_dir}: {err}"
        ) from err


def _create_layout_files(
    target_dir: Path, force: bool
) -> tuple[list[str], list[str], list[str]]:
    """Does the file system work of [_create_layout][napt.cli.init._create_layout].

    Args:
        target_dir: The project root.
        force: Whether to back up an existing org.yaml and write a fresh one.

    Returns:
        The same tuple as
            [_create_layout][napt.cli.init._create_layout].

    Raises:
        OSError: If a folder or file cannot be created.
    """
    from napt.config.defaults import ORG_YAML_TEMPLATE

    logger = get_global_logger()

    # Track what we create/skip
    created: list[str] = []
    skipped: list[str] = []
    backed_up: list[str] = []

    # Step 1: Create directory structure
    logger.step(1, 2, "Creating directory structure...")

    # Create recipes/ directory
    recipes_dir = target_dir / "recipes"
    if not recipes_dir.exists():
        recipes_dir.mkdir(parents=True)
        created.append("recipes/")
        logger.verbose("INIT", "Created: recipes/")
    else:
        skipped.append("recipes/")
        logger.verbose("INIT", "Skipped: recipes/ (already exists)")

    # Create defaults/vendors/ directory
    vendors_dir = target_dir / "defaults" / "vendors"
    if not vendors_dir.exists():
        vendors_dir.mkdir(parents=True)
        created.append("defaults/vendors/")
        logger.verbose("INIT", "Created: defaults/vendors/")
    else:
        skipped.append("defaults/vendors/")
        logger.verbose("INIT", "Skipped: defaults/vendors/ (already exists)")

    # Create state/deployment/ directory
    deployment_dir = target_dir / "state" / "deployment"
    if not deployment_dir.exists():
        deployment_dir.mkdir(parents=True)
        created.append("state/deployment/")
        logger.verbose("INIT", "Created: state/deployment/")
    else:
        skipped.append("state/deployment/")
        logger.verbose("INIT", "Skipped: state/deployment/ (already exists)")

    # Step 2: Create configuration files
    logger.step(2, 2, "Creating configuration files...")

    # Create defaults/org.yaml
    org_yaml_path = target_dir / "defaults" / "org.yaml"
    if org_yaml_path.exists():
        if force:
            # Backup existing file; a backup from an earlier --force run is
            # replaced, since rename would refuse an existing target.
            backup_path = org_yaml_path.with_suffix(".yaml.backup")
            org_yaml_path.replace(backup_path)
            backed_up.append(f"defaults/org.yaml -> {backup_path.name}")
            logger.info("INIT", f"Backed up: defaults/org.yaml -> {backup_path.name}")

            # Write new file
            org_yaml_path.write_text(ORG_YAML_TEMPLATE, encoding="utf-8")
            created.append("defaults/org.yaml")
            logger.verbose("INIT", "Created: defaults/org.yaml")
        else:
            skipped.append("defaults/org.yaml")
            logger.verbose("INIT", "Skipped: defaults/org.yaml (already exists)")
    else:
        # Ensure parent directory exists
        org_yaml_path.parent.mkdir(parents=True, exist_ok=True)
        org_yaml_path.write_text(ORG_YAML_TEMPLATE, encoding="utf-8")
        created.append("defaults/org.yaml")
        logger.verbose("INIT", "Created: defaults/org.yaml")

    return created, skipped, backed_up


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'init' command parser.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_init = subparsers.add_parser(
        "init",
        help="Initialize a new NAPT project",
        description=(
            "Create a new NAPT project structure with default configuration.\n\n"
            "Creates:\n"
            "  - recipes/              Directory for recipe YAML files\n"
            "  - defaults/org.yaml     Organization defaults template\n"
            "  - defaults/vendors/     Directory for vendor-specific defaults\n"
            "  - state/deployment/     Per-app deployment state files\n\n"
            "Examples:\n"
            "  napt init\n"
            "  napt init ./my-project\n"
            "  napt init --force\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_init.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Directory to initialize (default: current directory)",
    )
    parser_init.add_argument(
        "--force",
        action="store_true",
        help="Backup and overwrite existing configuration files",
    )
    add_output_flags(parser_init)
    parser_init.set_defaults(func=cmd_init)
