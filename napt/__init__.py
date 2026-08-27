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

"""Python-based CLI tool for Windows application packaging and Intune deployment.

Uses PSAppDeployToolkit (PSADT) to automate packaging and deployment to
Microsoft Intune.

NAPT provides:

- YAML-based recipe configuration
- Automatic version discovery from multiple sources
- Robust download with conditional requests and integrity verification
- Automatic update policies (version-based, hash-based, or combined)
- PSADT package generation with Template_v4
- .intunewin package creation for Intune deployment
- Direct upload to Microsoft Intune (planned)
- Deployment wave/ring management (planned)

Quick Start:
Validate recipe syntax:

    $ napt validate recipes/Google/chrome.yaml

Discover latest version and download installer:

    $ napt discover recipes/Google/chrome.yaml

For full CLI documentation:

    $ napt --help

For more details, see the individual module docstrings.
"""
