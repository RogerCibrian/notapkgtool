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

This package provides the main CLI entry point for the napt tool, offering
commands for recipe validation, package building, and deployment management.

Commands:

    init: Initialize a new NAPT project
    validate: Validate recipe syntax and configuration
    discover: Discover latest version and download installer
    build: Build PSADT package from recipe
    package: Create .intunewin package for Intune (recipe-based)
    upload: Upload .intunewin package to Microsoft Intune
    auth: Sign in to Microsoft Graph and inspect credentials
    promote: Plan and apply deployment ring promotion
    status: Show deployment state across all apps

Each command lives in its own module named after it -- `napt/cli/validate.py`
owns `napt validate` -- holding the command's `cmd_*` handlers and a
`register(subparsers)` hook that adds its parser. This module assembles the
top-level parser, calls each command's `register`, and dispatches to the
selected handler.

Example:
    Validate recipe syntax:
        ```bash
        $ napt validate recipes/Google/chrome.yaml
        ```

    Discover latest version:
        ```bash
        $ napt discover recipes/Google/chrome.yaml
        ```

    Enable verbose output:
        ```bash
        $ napt discover recipes/Google/chrome.yaml --verbose
        ```

Exit Codes:

- 0: Success
- 1: Error (configuration, download, or validation failure)

Note:
    The CLI uses argparse for command parsing (stdlib, zero dependencies).
    Verbose mode shows full tracebacks on errors for debugging.
    Debug mode implies verbose mode and shows detailed configuration dumps.

"""

from __future__ import annotations

import argparse
from importlib.metadata import version
import sys

from . import (
    auth,
    build,
    discover,
    init,
    package,
    promote,
    status,
    upload,
    validate,
)

__all__ = ["main"]


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

    validate.register(subparsers)
    discover.register(subparsers)
    build.register(subparsers)
    package.register(subparsers)
    init.register(subparsers)
    upload.register(subparsers)
    auth.register(subparsers)
    promote.register(subparsers)
    status.register(subparsers)

    # Parse and dispatch
    args = parser.parse_args()

    # Call the appropriate command handler
    exit_code = args.func(args)
    sys.exit(exit_code)
