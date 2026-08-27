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

"""The `napt upload` command.

Uploads the packaged .intunewin file for a recipe to Microsoft Intune via
the Graph API.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from napt.exceptions import (
    AuthError,
    ConfigError,
    NAPTError,
    NetworkError,
    PackagingError,
)
from napt.logging import get_logger, set_global_logger
from napt.upload.manager import upload_package


def cmd_upload(args: argparse.Namespace) -> int:
    """Handler for 'napt upload' command.

    Uploads the .intunewin package for a recipe to Microsoft Intune via the
    Graph API. Infers the package path from the recipe's app ID. Authentication
    uses service principal / OIDC environment variables when set, otherwise
    the session saved by 'napt auth login'.

    Args:
        args: Parsed command-line arguments containing recipe path and
            debug flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    Note:
        Run 'napt package' before this command to create the .intunewin file.
        Re-running an upload adopts existing NAPT-stamped apps instead of
        creating duplicates; --force re-sends metadata and content to them.
        Developers: run 'napt auth login' once. CI/CD: set AZURE_CLIENT_ID,
        AZURE_TENANT_ID and AZURE_CLIENT_SECRET, or use OIDC federation.

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
        result = upload_package(recipe_path, force=args.force)
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


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'upload' command parser.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_upload = subparsers.add_parser(
        "upload",
        help="Upload .intunewin package to Microsoft Intune",
        description=(
            "Upload the most recent .intunewin package for a recipe to "
            "Microsoft Intune via the Graph API.\n\n"
            "Authentication:\n"
            "  CI/CD:       AZURE_CLIENT_ID + AZURE_TENANT_ID + AZURE_CLIENT_SECRET,\n"
            "               or OIDC federation (azure/login)\n"
            "  Interactive: run 'napt auth login' once\n\n"
            "Examples:\n"
            "  napt upload recipes/Google/chrome.yaml\n"
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
        "--force",
        action="store_true",
        help=(
            "Re-upload metadata and content to existing NAPT-managed apps "
            "for this release instead of adopting them as-is "
            "(never creates duplicates)"
        ),
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
