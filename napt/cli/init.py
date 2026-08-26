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

from napt.config.defaults import ORG_YAML_TEMPLATE
from napt.logging import get_logger, set_global_logger


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
        Exit code (0 for success, 1 for failure).

    Note:
        By default, existing files are skipped (not overwritten).
        Use --force to backup existing files and create fresh ones.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    target_dir = Path(args.directory).resolve()

    print(f"Initializing NAPT project in: {target_dir}")
    print()

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
        if args.force:
            # Backup existing file
            backup_path = org_yaml_path.with_suffix(".yaml.backup")
            org_yaml_path.rename(backup_path)
            backed_up.append(f"defaults/org.yaml -> {backup_path.name}")
            logger.verbose(
                "INIT", f"Backed up: defaults/org.yaml -> {backup_path.name}"
            )

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
        default=".",
        help="Directory to initialize (default: current directory)",
    )
    parser_init.add_argument(
        "--force",
        action="store_true",
        help="Backup and overwrite existing configuration files",
    )
    parser_init.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed initialization steps",
    )
    parser_init.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_init.set_defaults(func=cmd_init)
