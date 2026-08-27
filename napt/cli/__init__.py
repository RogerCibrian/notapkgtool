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
`register(subparsers)` hook that adds its parser. `napt/cli/main.py`
assembles the top-level parser, calls each command's `register`, and
dispatches to the selected handler.

Exit Codes:

- 0: Success
- 1: Error (configuration, download, or validation failure)

Note:
    The CLI uses argparse for command parsing (stdlib, zero dependencies).
    Verbose mode shows full tracebacks on errors for debugging.
    Debug mode implies verbose mode and shows detailed configuration dumps.
"""
