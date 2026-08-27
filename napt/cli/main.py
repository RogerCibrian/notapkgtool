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

"""CLI entry point: parser assembly and dispatch.

Builds the top-level ``napt`` argument parser, calls each command
module's ``register`` hook to add its subparser, and dispatches to the
selected command's handler. Registered as the ``napt`` console script in
pyproject.toml.
"""

from __future__ import annotations

import argparse
from importlib.metadata import version
import sys

from napt.cli import (
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
