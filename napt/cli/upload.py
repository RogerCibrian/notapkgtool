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

Uploads the .intunewin package of the release recorded in deployment
state for a recipe to Microsoft Intune via the Graph API.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from napt.cli.common import add_output_flags, add_state_dir


def cmd_upload(args: argparse.Namespace) -> int:
    """Handler for 'napt upload' command.

    Uploads the .intunewin package of the release deployment state records
    (pending, else published) for a recipe to Microsoft Intune via the
    Graph API; with no recorded release, the only package. Authentication
    uses service principal / OIDC environment variables when set, otherwise
    the session saved by 'napt auth login'.

    Args:
        args: Parsed command-line arguments containing recipe path,
            directory overrides, and debug flags.

    Returns:
        Exit code (0 for success).

    Note:
        Run 'napt package' before this command to create the .intunewin file.
        Re-running an upload adopts existing NAPT-stamped apps instead of
        creating duplicates; --force re-sends metadata and content to them.
        Developers: run 'napt auth login' once. CI/CD: set AZURE_CLIENT_ID,
        AZURE_TENANT_ID and AZURE_CLIENT_SECRET, or use OIDC federation.
        Failures raise NAPT errors for
        [run_handler][napt.cli.common.run_handler] to report.

    """
    from napt.upload.manager import upload_package

    recipe_path = args.recipe.resolve()

    print(f"Uploading package for recipe: {recipe_path}")
    print()

    result = upload_package(
        recipe_path,
        force=args.force,
        state_dir=args.state_dir,
        packages_dir=args.packages_dir,
    )

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
            "Upload the .intunewin package of the release recorded in "
            "deployment state (pending, else published) for a recipe to "
            "Microsoft Intune via the Graph API; with no recorded release, "
            "the only package.\n\n"
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
        type=Path,
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
        "--packages-dir",
        type=Path,
        default=None,
        help="Directory containing the packages (default: from config or ./packages)",
    )
    add_state_dir(
        parser_upload,
        "State root whose deployment/ folder records the release "
        "(default: from config or ./state)",
    )
    add_output_flags(parser_upload)
    parser_upload.set_defaults(func=cmd_upload)
