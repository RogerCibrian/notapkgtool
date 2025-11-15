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

"""Logging interface for NAPT.

This module provides a configurable logging interface that library modules
can use for output without depending on the CLI. The logger can be configured
globally or passed as a parameter for better isolation.

The logger supports three output levels:
- Step: Always printed (for progress indicators)
- Verbose: Only printed when verbose mode is enabled
- Debug: Only printed when debug mode is enabled (implies verbose)

Example:
    Configure global logger:
        ```python
        from notapkgtool.logging import get_logger, set_global_logger

        logger = get_logger(verbose=True, debug=False)
        set_global_logger(logger)
        ```

    Use in library code:
        ```python
        from notapkgtool.logging import get_logger

        logger = get_logger()
        logger.step(1, 4, "Loading configuration...")
        logger.verbose("STATE", "Loaded state from file")
        logger.debug("VERSION", "Trying backend: msilib...")
        ```

    Use with dependency injection:

        def my_function(logger=None):
            if logger is None:
                logger = get_logger()
            logger.verbose("MODULE", "Processing...")

Note:
    The default logger is silent (verbose=False, debug=False), so library
    functions won't print anything unless explicitly configured. The CLI
    configures the global logger when commands are executed.
"""

from __future__ import annotations

from typing import Protocol


class Logger(Protocol):
    """Protocol for logger implementations."""

    def step(self, step: int, total: int, message: str) -> None:
        """Print a step indicator for non-verbose mode.

        Args:
            step: Current step number (1-based).
            total: Total number of steps.
            message: Step description.
        """
        ...

    def verbose(self, prefix: str, message: str) -> None:
        """Print a verbose log message.

        Args:
            prefix: Message prefix (e.g., "STATE", "BUILD").
            message: Log message.
        """
        ...

    def debug(self, prefix: str, message: str) -> None:
        """Print a debug log message.

        Args:
            prefix: Message prefix (e.g., "VERSION", "HTTP").
            message: Log message.
        """
        ...


class DefaultLogger:
    """Default logger implementation that prints to stdout.

    This logger respects verbose and debug flags and formats output
    consistently with the CLI output format.
    """

    def __init__(self, verbose: bool = False, debug: bool = False) -> None:
        """Initialize logger with verbosity settings.

        Args:
            verbose: If True, print verbose messages.
            debug: If True, print debug messages (implies verbose).
        """
        self._verbose = verbose or debug
        self._debug = debug

    def step(self, step: int, total: int, message: str) -> None:
        """Print a step indicator for non-verbose mode."""
        print(f"[{step}/{total}] {message}")

    def verbose(self, prefix: str, message: str) -> None:
        """Print a verbose log message (only when verbose mode is active)."""
        if self._verbose:
            print(f"[{prefix}] {message}")

    def debug(self, prefix: str, message: str) -> None:
        """Print a debug log message (only when debug mode is active)."""
        if self._debug:
            print(f"[{prefix}] {message}")


class SilentLogger:
    """Logger that suppresses all output.

    Useful for programmatic usage when output is not desired.
    """

    def step(self, step: int, total: int, message: str) -> None:
        """Suppress step output."""
        pass

    def verbose(self, prefix: str, message: str) -> None:
        """Suppress verbose output."""
        pass

    def debug(self, prefix: str, message: str) -> None:
        """Suppress debug output."""
        pass


# Global logger instance (defaults to silent)
_global_logger: Logger = SilentLogger()


def get_logger(verbose: bool = False, debug: bool = False) -> Logger:
    """Get a logger instance with specified verbosity.

    Args:
        verbose: If True, logger will print verbose messages.
        debug: If True, logger will print debug messages (implies verbose).

    Returns:
        A logger instance configured with the specified verbosity.

    Example:
        Get a verbose logger:
            ```python
            logger = get_logger(verbose=True)
            logger.verbose("MODULE", "Processing...")
            ```

        Get a debug logger:
            ```python
            logger = get_logger(debug=True)
            logger.debug("MODULE", "Debug info...")
            ```
    """
    return DefaultLogger(verbose=verbose, debug=debug)


def get_global_logger() -> Logger:
    """Get the global logger instance.

    Returns:
        The current global logger instance.

    Note:
        The default global logger is silent. Use set_global_logger() to
        configure it, or pass a logger instance directly to functions.
    """
    return _global_logger


def set_global_logger(logger: Logger) -> None:
    """Set the global logger instance.

    Args:
        logger: Logger instance to use as the global logger.

    Example:
        Configure global logger from CLI:
            ```python
            from notapkgtool.logging import get_logger, set_global_logger

            logger = get_logger(verbose=args.verbose, debug=args.debug)
            set_global_logger(logger)
            ```

    Note:
        This affects all library functions that use get_logger() without
        passing a logger instance. For better isolation, pass logger
        instances directly to functions instead of using the global logger.
    """
    global _global_logger
    _global_logger = logger
