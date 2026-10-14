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

"""Console output for NAPT.

Every module writes through the one global logger the CLI configures from
the ``-v`` and ``-d`` flags. The levels are:

- step: always printed, for the numbered pipeline stages
- info: always printed, for notable events that are not warnings
- warning: always printed and tagged, for something unexpected but
  recoverable that the user should see
- progress: always printed, overwriting the current line
- verbose: printed with ``-v``, for implementation detail
- debug: printed with ``-d`` (which implies ``-v``), for raw data dumps

Each line starts with a bracketed prefix naming the pipeline stage or the
shared domain the message belongs to; the documented set is in CLAUDE.md
and a test checks every call against it.

Note:
    The default global logger is non-verbose: it prints steps, info,
    warnings, and progress, and hides verbose and debug lines until the
    CLI installs a configured logger.
"""

from __future__ import annotations


class Logger:
    """Prints NAPT's console output at the configured verbosity."""

    def __init__(self, verbose: bool = False, debug: bool = False) -> None:
        """Sets the verbosity.

        Args:
            verbose: If True, print verbose messages.
            debug: If True, print debug messages (implies verbose).
        """
        self._verbose = verbose or debug
        self._debug = debug

    @property
    def debug_enabled(self) -> bool:
        """Whether debug lines print, so a caller can skip building a dump."""
        return self._debug

    def step(self, step: int, total: int, message: str) -> None:
        """Prints a numbered pipeline stage; always visible.

        Args:
            step: Current step number (1-based).
            total: Total number of steps.
            message: Step description.
        """
        print(f"[{step}/{total}] {message}")

    def info(self, prefix: str, message: str) -> None:
        """Prints a notable event that is not a warning; always visible.

        Use for skipping a step for a known reason, replacing an artifact,
        or a key ID an external system returned.

        Args:
            prefix: Message prefix (e.g., "PACKAGE", "BUILD").
            message: Informational message.
        """
        print(f"[{prefix}] {message}")

    def warning(self, prefix: str, message: str) -> None:
        """Prints something unexpected but recoverable; always visible.

        The line carries a ``WARNING:`` tag so it stands apart from the
        info lines around it.

        Args:
            prefix: Message prefix (e.g., "DETECTION", "BUILD").
            message: Warning message.
        """
        print(f"[{prefix}] WARNING: {message}")

    def progress(self, prefix: str, message: str) -> None:
        """Prints download or upload progress, overwriting the current line.

        Always visible regardless of verbosity settings.

        Args:
            prefix: Message prefix (e.g., "HTTP", "UPLOAD").
            message: Progress message (e.g., "42%").
        """
        print(f"[{prefix}] {message}", end="\r")

    def verbose(self, prefix: str, message: str) -> None:
        """Prints implementation detail; visible with ``-v``.

        Args:
            prefix: Message prefix (e.g., "STATE", "BUILD").
            message: Log message.
        """
        if self._verbose:
            print(f"[{prefix}] {message}")

    def debug(self, prefix: str, message: str) -> None:
        """Prints a raw data dump or granular trace; visible with ``-d``.

        Args:
            prefix: Message prefix (e.g., "CONFIG", "HTTP").
            message: Log message.
        """
        if self._debug:
            print(f"[{prefix}] {message}")


# Global logger instance (defaults to non-verbose)
_global_logger: Logger = Logger()


def get_logger(verbose: bool = False, debug: bool = False) -> Logger:
    """Builds a logger with the given verbosity.

    Args:
        verbose: If True, logger will print verbose messages.
        debug: If True, logger will print debug messages (implies verbose).

    Returns:
        A logger configured with the specified verbosity.

    Example:
        Get a verbose logger:
            ```python
            logger = get_logger(verbose=True)
            logger.verbose("BUILD", "Copying installer: setup.msi")
            ```
    """
    return Logger(verbose=verbose, debug=debug)


def get_global_logger() -> Logger:
    """Returns the logger every module writes through.

    Returns:
        The current global logger instance.

    Note:
        Until the CLI installs a configured logger, this is the default
        non-verbose logger: it prints steps, info, warnings, and progress.
    """
    return _global_logger


def set_global_logger(logger: Logger) -> None:
    """Installs the logger every module writes through.

    The CLI calls this once from the parsed ``-v`` and ``-d`` flags before
    running a command; tests install a verbose logger to assert on output.

    Args:
        logger: Logger instance to use as the global logger.

    Example:
        Configure global logger from CLI:
            ```python
            from napt.logging import get_logger, set_global_logger

            logger = get_logger(verbose=args.verbose, debug=args.debug)
            set_global_logger(logger)
            ```
    """
    global _global_logger
    _global_logger = logger
