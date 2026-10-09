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

"""The `napt upstream` command: recipes imported from other git repositories.

`napt upstream add` imports upstream recipes from a repository as pinned
copies and writes the overrides that run them; `napt upstream remove` takes
one out again. The
engines live in [napt.upstream.add][] and [napt.upstream.remove][]; this
module parses arguments and prints results.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from napt.cli.common import add_output_flags, print_results


def cmd_upstream_add(args: argparse.Namespace) -> int:
    """Handler for 'napt upstream add'.

    Imports the selected recipes from a repository: writes each one
    byte-identical as a pinned copy under upstream/, writes an override in
    recipes/ that names it as parent, and records each recipe's commit and
    hashes in upstream.yaml. Nothing is written if any recipe fails validation.

    Args:
        args: Parsed command-line arguments carrying the clone URL, paths,
            ref, destination, id, exclude globs, and the dry-run flag.

    Returns:
        Exit code (0 for success).

    Note:
        Failures raise NAPT errors for
        [run_handler][napt.cli.common.run_handler] to report.
    """
    from napt.upstream.add import add_recipes

    result = add_recipes(
        Path.cwd(),
        args.url,
        args.path,
        ref=args.ref,
        dest=args.dest,
        app_id=args.id,
        excludes=args.exclude,
        dry_run=args.dry_run,
    )

    print()
    for recipe in result.recipes:
        marker = "[PLAN]" if result.dry_run else "[OK]"
        print(f"{marker} {recipe.path} -> {recipe.override} (id {recipe.app_id})")
    for path in result.skipped:
        print(f"[SKIP] {path} (already imported; napt upstream update refreshes it)")
    print()
    rows = [
        ("Repository", result.url),
        ("Ref", result.ref),
        ("Commit", result.commit),
        ("Recipes", str(len(result.recipes))),
        ("Skipped", str(len(result.skipped)) if result.skipped else None),
    ]
    count = len(result.recipes)
    if result.dry_run:
        print_results("UPSTREAM ADD (DRY RUN)", rows, "Nothing written.")
    elif count == 0:
        print_results("UPSTREAM ADD RESULTS", rows, "Nothing new to import.")
    else:
        print_results(
            "UPSTREAM ADD RESULTS",
            rows,
            f"Imported {count} recipe(s); run 'napt validate recipes/' to confirm.",
        )
    return 0


def cmd_upstream_remove(args: argparse.Namespace) -> int:
    """Handler for 'napt upstream remove'.

    Deletes a pinned copy and its lockfile entry, and the repository's
    entry once nothing of it remains. The override stays unless
    --delete-override is given.

    Args:
        args: Parsed command-line arguments carrying the path and the
            delete-override flag.

    Returns:
        Exit code (0 for success).

    Note:
        Failures raise NAPT errors for
        [run_handler][napt.cli.common.run_handler] to report.
    """
    from napt.upstream.remove import remove_recipe

    result = remove_recipe(Path.cwd(), args.path, delete_override=args.delete_override)

    override_state = None
    if result.override is not None:
        override_state = "deleted" if result.override_deleted else "kept"
    print_results(
        "UPSTREAM REMOVE RESULTS",
        [
            ("Removed", result.path),
            ("Override", result.override),
            ("Override State", override_state),
            ("Repository Entry", "removed" if result.repo_removed else "kept"),
        ],
        "Removed the pinned copy.",
    )
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'upstream' command parser and its subcommands.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_upstream = subparsers.add_parser(
        "upstream",
        help="Import recipes from other git repositories",
        description=(
            "Import upstream recipes from any git repository as pinned copies. "
            "An imported "
            "recipe is a byte-identical pinned copy under upstream/, run through an "
            "override in recipes/ that names it as parent, and recorded in "
            "upstream.yaml with its commit and hashes.\n\n"
            "Examples:\n"
            "  napt upstream add https://github.com/org/recipes.git "
            "--path recipes/Google/chrome.yaml\n"
            "  napt upstream add https://github.com/org/recipes.git "
            "--path recipes --exclude 'Beta/*'\n"
            "  napt upstream remove recipes/Google/chrome.override.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    upstream_sub = parser_upstream.add_subparsers(
        dest="upstream_command",
        help="Upstream subcommands",
        required=True,
    )

    parser_add = upstream_sub.add_parser(
        "add",
        help="Import recipes from a repository",
        description=(
            "Fetch the recipes under each --path at the branch or tag, write "
            "them as pinned copies under upstream/, write one <app>.override.yaml "
            "per recipe "
            "under recipes/ (mirroring the path after the repository's own "
            "recipes/ segment), and record them in upstream.yaml. Keys an "
            "upstream recipe may not set (deployment, directories, intune "
            "policy) are ignored at load and named once here. Nothing is "
            "written if any recipe fails validation.\n\n"
            "Examples:\n"
            "  napt upstream add https://github.com/org/recipes.git "
            "--path recipes/Google/chrome.yaml\n"
            "  napt upstream add git@github.com:org/recipes.git --path recipes "
            "--ref v2 --dry-run\n"
            "  napt upstream add https://gitlab.com/g/sub/recipes.git "
            "--path apps/x.yaml --dest recipes/Vendor --id vendor-x"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_add.add_argument("url", help="Clone URL in any form git accepts")
    parser_add.add_argument(
        "--path",
        action="append",
        required=True,
        metavar="PATH",
        help=(
            "File or directory inside the repository to import; repeatable. "
            "A directory imports every .yaml and .yml beneath it"
        ),
    )
    parser_add.add_argument(
        "--ref",
        default=None,
        help="Branch or tag to import from (default: the repository's default branch)",
    )
    parser_add.add_argument(
        "--dest",
        default=None,
        metavar="DIR",
        help=(
            "Directory for the overrides, relative to the project root; required "
            "when the upstream path has no recipes/ segment to mirror"
        ),
    )
    parser_add.add_argument(
        "--id",
        default=None,
        help="Override id instead of the upstream recipe's (single-file imports)",
    )
    parser_add.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help=(
            "Skip files matching the glob, relative to the imported directory; "
            "repeatable"
        ),
    )
    parser_add.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written and write nothing",
    )
    add_output_flags(parser_add)
    parser_add.set_defaults(func=cmd_upstream_add)

    parser_remove = upstream_sub.add_parser(
        "remove",
        help="Remove an imported recipe",
        description=(
            "Delete a pinned copy and its upstream.yaml entry, and the "
            "repository's entry once nothing of it remains. The override is "
            "kept, with its parent now dangling, unless --delete-override is "
            "given.\n\n"
            "Examples:\n"
            "  napt upstream remove recipes/Google/chrome.override.yaml\n"
            "  napt upstream remove upstream/github.com/org/recipes/recipes/"
            "Google/chrome.yaml --delete-override"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_remove.add_argument(
        "path",
        type=Path,
        help="The override, or the pinned copy under upstream/",
    )
    parser_remove.add_argument(
        "--delete-override",
        action="store_true",
        help="Delete the override as well",
    )
    add_output_flags(parser_remove)
    parser_remove.set_defaults(func=cmd_upstream_remove)
