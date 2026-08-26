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
from pathlib import Path

from napt.exceptions import ConfigError, StateError
from napt.logging import get_logger, set_global_logger
from napt.state import summarize_deployment_states


def cmd_status(args: argparse.Namespace) -> int:
    """Handler for 'napt status' command.

    Aggregates all per-app deployment state files into one view: the
    published version, pending release, and which version holds each ring.

    Args:
        args: Parsed command-line arguments containing the state
            directory, output format, and flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    """
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    deployment_dir = Path(args.state_dir) / "deployment"

    try:
        rows = summarize_deployment_states(deployment_dir)
    except (ConfigError, StateError) as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    if args.format == "json":
        import json

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
            row["pending"] or "-",
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
        "--state-dir",
        type=Path,
        default=Path("state"),
        help="State directory holding deployment/ (default: state)",
    )
    parser_status.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser_status.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_status.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_status.set_defaults(func=cmd_status)
