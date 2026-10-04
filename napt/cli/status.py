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

"""The `napt status` command.

Aggregates per-app deployment state into one view: published version,
pending release, and ring positions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from napt.cli.common import add_output_flags, add_state_dir


def cmd_status(args: argparse.Namespace) -> int:
    """Handler for 'napt status' command.

    Aggregates all per-app deployment state files into one view: the
    published version, pending release, and which version holds each ring.
    Without --state-dir, the directory comes from the recipes'
    ``directories.state`` setting, the same one the pipeline wrote to.

    Args:
        args: Parsed command-line arguments containing the recipes path,
            state directory, output format, and flags.

    Returns:
        Exit code (0 for success).

    Note:
        Failures raise NAPT errors for
        [run_handler][napt.cli.common.run_handler] to report.

    """
    from napt.config.loader import resolve_state_dir
    from napt.state.deployment import summarize_deployment_states

    state_dir = (
        args.state_dir
        if args.state_dir is not None
        else resolve_state_dir(args.recipes)
    )
    deployment_dir = state_dir / "deployment"

    rows = summarize_deployment_states(deployment_dir)

    if args.format == "json":
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if not rows:
        print(f"No deployment state found in {deployment_dir}")
        return 0

    headers = ("App", "Published", "Pending", "Rings")
    table = [
        (
            row["app_id"],
            row["published"] or "-",
            (row["pending"] or "-")
            + (" [DOWNGRADE]" if row["pending_is_downgrade"] else ""),
            ", ".join(f"{name}={ver}" for name, ver in row["rings"].items()) or "-",
        )
        for row in rows
    ]
    widths = [
        max(len(headers[col]), *(len(line[col]) for line in table))
        for col in range(len(headers))
    ]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * w for w in widths))
    for line in table:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(line)))

    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'status' command parser.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_status = subparsers.add_parser(
        "status",
        help="Show deployment state across all apps",
        description=(
            "Aggregate per-app deployment state into one view: published "
            "version, pending release, and ring positions.\n\n"
            "Examples:\n"
            "  napt status\n"
            "  napt status --format json\n\n"
            "See docs for more examples and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_status.add_argument(
        "recipes",
        nargs="?",
        type=Path,
        default=Path("recipes"),
        help=(
            "Recipe file or directory whose configuration names the state "
            "directory (default: recipes/)"
        ),
    )
    add_state_dir(
        parser_status,
        "State directory holding deployment/ "
        "(default: directories.state from config)",
    )
    parser_status.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    add_output_flags(parser_status)
    parser_status.set_defaults(func=cmd_status)
