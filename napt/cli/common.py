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

"""What every napt command shares: flags, logger setup, errors, results.

A command module's `register` adds the shared flags with
[add_output_flags][napt.cli.common.add_output_flags] and
[add_state_dir][napt.cli.common.add_state_dir]; `napt/cli/main.py` calls
[setup_logging][napt.cli.common.setup_logging] once and runs the selected
handler through [run_handler][napt.cli.common.run_handler], so a handler
raises NAPT errors instead of catching them. A handler prints its result
through [print_results][napt.cli.common.print_results], supplying the title,
the rows, and the success line.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from pathlib import Path
import traceback

from napt.exceptions import AuthError, NAPTError
from napt.logging import Logger, get_logger, set_global_logger

EXIT_INTERRUPTED = 130
"""Exit code for a run stopped with Ctrl-C: 128 plus SIGINT's signal number."""


def add_output_flags(parser: argparse.ArgumentParser) -> None:
    """Adds the -v/--verbose and -d/--debug flags to a command's parser.

    Args:
        parser: The command's (or subcommand's) parser.
    """
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )


def add_state_dir(parser: argparse.ArgumentParser, help_text: str) -> None:
    """Adds the --state-dir override to a command's parser.

    The flag is a path that defaults to None, which every command reads as
    "use ``directories.state`` from configuration".

    Args:
        parser: The command's (or subcommand's) parser.
        help_text: What the command does with the directory.
    """
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=help_text,
    )


def setup_logging(args: argparse.Namespace) -> Logger:
    """Configures the global logger from the parsed output flags.

    Args:
        args: Parsed command-line arguments carrying ``verbose`` and
            ``debug``.

    Returns:
        The logger now installed as the global logger.
    """
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)
    return logger


def print_results(
    title: str,
    rows: Iterable[tuple[str, object]],
    success: str,
    *,
    failure: str | None = None,
) -> None:
    """Prints a command's results block.

    The block is a banner, the title, one aligned ``Label: value`` line per
    row, a closing banner, a blank line, and the success line. Labels pad to
    the longest label in the block. A row whose value is None is left out,
    so an optional field needs no branch in the handler. A command that
    finished with partial results and will exit non-zero passes ``failure``
    and the block ends with ``[FAIL]`` instead.

    Args:
        title: Heading for the block (e.g., "BUILD RESULTS").
        rows: Label and value pairs in display order.
        success: What was accomplished, printed after ``[SUCCESS]``.
        failure: What went wrong, printed after ``[FAIL]`` in place of the
            success line.
    """
    shown = [(label, value) for label, value in rows if value is not None]
    width = max((len(label) for label, _ in shown), default=0) + 1
    banner = "=" * 70
    print(banner)
    print(title)
    print(banner)
    for label, value in shown:
        print(f"{label + ':':<{width}} {value}")
    print(banner)
    print()
    if failure is not None:
        print(f"[FAIL] {failure}")
    else:
        print(f"[SUCCESS] {success}")


def run_handler(
    handler: Callable[[argparse.Namespace], int], args: argparse.Namespace
) -> int:
    """Runs a command handler, reporting failures the same way for every command.

    A NAPT error or an OS error becomes one line on stdout (with the
    traceback on stderr under -v or -d) and exit code 1; the label names
    authentication failures. Ctrl-C ends the run with exit code 130 and no
    traceback. Anything else is a bug and propagates.

    Args:
        handler: The command's ``cmd_*`` function.
        args: Parsed command-line arguments to hand to it.

    Returns:
        The process exit code.
    """
    try:
        return handler(args)
    except KeyboardInterrupt:
        print()
        print("Interrupted.")
        return EXIT_INTERRUPTED
    except (NAPTError, OSError) as err:
        label = "Authentication error" if isinstance(err, AuthError) else "Error"
        print(f"{label}: {err}")
        if args.verbose or args.debug:
            traceback.print_exc()
        return 1
