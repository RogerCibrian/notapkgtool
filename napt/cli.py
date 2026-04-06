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

"""Command-line interface for NAPT.

This module provides the main CLI entry point for the napt tool, offering
commands for recipe validation, package building, and deployment management.

Commands:

    init: Initialize a new NAPT project
    validate: Validate recipe syntax and configuration
    discover: Discover latest version and download installer
    build: Build PSADT package from recipe
    package: Create .intunewin package for Intune (recipe-based)
    upload: Upload .intunewin package to Microsoft Intune

Example:
    Validate recipe syntax:
        ```bash
        $ napt validate recipes/Google/chrome.yaml
        ```

    Discover latest version:
        ```bash
        $ napt discover recipes/Google/chrome.yaml
        ```

    Build PSADT package:
        ```bash
        $ napt build recipes/Google/chrome.yaml
        ```

    Create .intunewin package:
        ```bash
        $ napt package recipes/Google/chrome.yaml
        ```

    Upload to Intune:
        ```bash
        $ napt upload recipes/Google/chrome.yaml
        ```

    Enable verbose output:
        ```bash
        $ napt discover recipes/Google/chrome.yaml --verbose
        ```

    Enable debug output:
        ```bash
        $ napt discover recipes/Google/chrome.yaml --debug
        ```

Exit Codes:

- 0: Success
- 1: Error (configuration, download, or validation failure)

Note:
    The CLI uses argparse for command parsing (stdlib, zero dependencies).
    Commands are registered with subparsers for clean organization.
    Each command has its own handler function (`cmd_<command>`).
    Verbose mode shows full tracebacks on errors for debugging.
    Debug mode implies verbose mode and shows detailed configuration dumps.

"""

from __future__ import annotations

import argparse
from importlib.metadata import version
from pathlib import Path
import sys
from typing import Any

from napt.build import build_package, create_intunewin
from napt.config import load_effective_config
from napt.config.defaults import ORG_YAML_TEMPLATE
from napt.discovery.manager import discover_recipe
from napt.exceptions import (
    AuthError,
    ConfigError,
    NAPTError,
    NetworkError,
    PackagingError,
)
from napt.logging import get_logger, set_global_logger
from napt.upload import upload_package
from napt.validation import validate_recipe


def _print_provenance(
    config: dict[str, Any], provenance: dict[str, Any], prefix: str = ""
) -> None:
    """Prints provenance information showing which layer set each config value.

    Args:
        config: The merged configuration dictionary.
        provenance: The provenance dictionary mirroring config structure.
        prefix: Key path prefix for nested sections (used in recursion).
    """
    for key in sorted(provenance.keys()):
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        prov_value = provenance[key]

        if isinstance(prov_value, dict):
            # Recurse into nested sections
            cfg_value = config.get(key, {})
            if isinstance(cfg_value, dict):
                _print_provenance(cfg_value, prov_value, full_key)
        else:
            # Leaf value — print provenance
            cfg_value = config.get(key)
            value_repr = repr(cfg_value)
            if len(value_repr) > 60:
                value_repr = value_repr[:57] + "..."
            print(f"  {full_key}: {value_repr} ({prov_value})")


def cmd_validate(args: argparse.Namespace) -> int:
    """Handler for 'napt validate' command.

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
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()

    print(f"Validating recipe: {recipe_path}")
    print()

    # Validate the recipe
    result = validate_recipe(recipe_path)

    # Display results
    print("=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"Recipe:      {result.recipe_path}")
    print(f"Status:      {result.status.upper()}")
    print(f"App Count:   {result.app_count}")
    print()

    # Show warnings if any
    if result.warnings:
        print(f"Warnings ({len(result.warnings)}):")
        for warning in result.warnings:
            print(f"  [WARNING] {warning}")
        print()

    # Show errors if any
    if result.errors:
        print(f"Errors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  [X] {error}")
        print()

    print("=" * 70)

    # Show provenance in debug mode (useful for both valid and invalid recipes)
    if args.debug:
        try:
            config = load_effective_config(recipe_path)
            provenance = config.get("_provenance")
            if provenance:
                print()
                print("CONFIGURATION PROVENANCE")
                print("-" * 70)
                _print_provenance(config, provenance)
                print("-" * 70)
        except Exception:
            pass  # Best-effort; config may fail to load for invalid recipes

    if result.status == "valid":
        print()
        print("[SUCCESS] Recipe is valid!")
        return 0
    else:
        print()
        print(f"[FAILED] Recipe validation failed with {len(result.errors)} error(s).")
        return 1


def cmd_discover(args: argparse.Namespace) -> int:
    """Handler for 'napt discover' command.

    Discovers the latest version of an application by querying the source
    and downloading the installer. This command validates the recipe YAML,
    uses the configured discovery strategy to find the latest version,
    downloads the installer (or uses cached version via ETag), extracts
    version information, and updates the state file with caching info.

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
            state_file=args.state_file if not args.stateless else None,
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


def cmd_build(args: argparse.Namespace) -> int:
    """Handler for 'napt build' command.

    Builds a PSADT package from a recipe and downloaded installer. This command
    loads the recipe configuration, finds the downloaded installer, extracts
    version from the installer file (filesystem is truth), downloads/caches
    the specified PSADT release, creates build directory structure, copies
    PSADT files pristine from cache, generates Invoke-AppDeployToolkit.ps1
    with recipe values, copies installer to Files/ directory, and applies
    custom branding.

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
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()
    downloads_dir = Path(args.downloads_dir).resolve() if args.downloads_dir else None
    output_dir = Path(args.output_dir) if args.output_dir else None

    if not recipe_path.exists():
        print(f"Error: Recipe file not found: {recipe_path}")
        return 1

    print(f"Building PSADT package for recipe: {recipe_path}")
    if downloads_dir:
        print(f"Downloads directory: {downloads_dir}")
    if output_dir:
        print(f"Output directory: {output_dir}")
    print()

    try:
        result = build_package(
            recipe_path,
            downloads_dir=downloads_dir,
            output_dir=output_dir,
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


def cmd_upload(args: argparse.Namespace) -> int:
    """Handler for 'napt upload' command.

    Uploads the .intunewin package for a recipe to Microsoft Intune via the
    Graph API. Infers the package path from the recipe's app ID. Authentication
    is automatic: tries EnvironmentCredential (AZURE_CLIENT_ID +
    AZURE_CLIENT_SECRET + AZURE_TENANT_ID), ManagedIdentityCredential, and
    DeviceCodeCredential (browser login) in that order.

    Args:
        args: Parsed command-line arguments containing recipe path and
            debug flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    Note:
        Run 'napt package' before this command to create the .intunewin file.
        Developers: set AZURE_CLIENT_ID and AZURE_TENANT_ID, then complete
        the device code flow when prompted.
        Set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID for CI/CD.

    """
    # Configure global logger
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipe_path = Path(args.recipe).resolve()

    if not recipe_path.exists():
        print(f"Error: Recipe file not found: {recipe_path}")
        return 1

    print(f"Uploading package for recipe: {recipe_path}")
    print()

    try:
        result = upload_package(recipe_path)
    except ConfigError as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except AuthError as err:
        print(f"Authentication error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except (NetworkError, PackagingError) as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except NAPTError as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    # Display results
    print("=" * 70)
    print("UPLOAD RESULTS")
    print("=" * 70)
    print(f"App ID:          {result.app_id}")
    print(f"App Name:        {result.app_name}")
    print(f"Version:         {result.version}")
    if result.intune_app_id:
        print(f"Intune Win32 App ID:    {result.intune_app_id}")
    if result.intune_update_app_id:
        print(f"Intune Win32 Update ID: {result.intune_update_app_id}")
    print(f"Package:         {result.package_path}")
    print(f"Status:          {result.status}")
    print("=" * 70)
    print()
    print("[SUCCESS] Package uploaded to Intune successfully!")

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Handler for 'napt init' command.

    Initializes a new NAPT project by creating the directory structure and
    default configuration files. This command creates the recipes/ directory,
    defaults/ directory with org.yaml template, and defaults/vendors/ directory.

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


def main() -> None:
    """Main entry point for the napt CLI.

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
        version=f"napt {version('napt')}",
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
        description=(
            "Check recipe YAML for syntax errors and configuration issues "
            "without making network calls.\n\n"
            "Examples:\n"
            "  napt validate recipes/Google/chrome.yaml\n"
            "  napt validate recipes/Google/chrome.yaml --verbose\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
    parser_validate.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_validate.set_defaults(func=cmd_validate)

    # 'discover' command
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
        "--state-file",
        type=Path,
        default=Path("state/versions.json"),
        help=(
            "State file for version tracking and ETag caching "
            "(default: state/versions.json)"
        ),
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
        help="Path to the recipe YAML file",
    )
    parser_build.add_argument(
        "--downloads-dir",
        default=None,
        help=(
            "Directory containing the downloaded installer "
            "(default: from config or ./downloads)"
        ),
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

    # 'init' command
    parser_init = subparsers.add_parser(
        "init",
        help="Initialize a new NAPT project",
        description=(
            "Create a new NAPT project structure with default configuration.\n\n"
            "Creates:\n"
            "  - recipes/              Directory for recipe YAML files\n"
            "  - defaults/org.yaml     Organization defaults template\n"
            "  - defaults/vendors/     Directory for vendor-specific defaults\n\n"
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

    # 'upload' command
    parser_upload = subparsers.add_parser(
        "upload",
        help="Upload .intunewin package to Microsoft Intune",
        description=(
            "Upload the most recent .intunewin package for a recipe to "
            "Microsoft Intune via the Graph API.\n\n"
            "Authentication is automatic — tried in this order:\n"
            "  1. AZURE_CLIENT_ID + AZURE_CLIENT_SECRET + AZURE_TENANT_ID env vars\n"
            "  2. Managed identity (Azure VMs, GitHub Actions OIDC)\n"
            "  3. Device code flow (browser login — set AZURE_CLIENT_ID + AZURE_TENANT_ID)\n\n"
            "Examples:\n"
            "  napt upload recipes/Google/chrome.yaml\n"
            "  napt upload recipes/Google/chrome.yaml --tenant-id <id>\n"
            "  napt upload recipes/Google/chrome.yaml --verbose\n\n"
            "See docs for auth setup and full configuration guide."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_upload.add_argument(
        "recipe",
        help="Path to the recipe YAML file",
    )
    parser_upload.add_argument(
        "--tenant-id",
        default=None,
        help="Azure AD tenant ID (overrides defaults/org.yaml)",
    )
    parser_upload.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_upload.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_upload.set_defaults(func=cmd_upload)

    # Parse and dispatch
    args = parser.parse_args()

    # Call the appropriate command handler
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
