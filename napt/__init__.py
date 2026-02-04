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

"""NAPT - Not a Pkg Tool

A Python-based CLI tool for automating Windows application packaging and
deployment to Microsoft Intune using PSAppDeployToolkit (PSADT).

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

__version__ = "0.3.0"
__author__ = "Roger Cibrian"
__license__ = "Apache-2.0"
__description__ = "Not a Pkg Tool - Windows/Intune packaging with PSADT"

# Re-export commonly used functions for convenience
from napt.config import load_effective_config
from napt.core import discover_recipe
from napt.exceptions import (
    ConfigError,
    NAPTError,
    NetworkError,
    PackagingError,
)
from napt.io import download_file
from napt.results import (
    BuildResult,
    DiscoverResult,
    PackageResult,
    ValidationResult,
)
from napt.validation import validate_recipe
from napt.versioning import DiscoveredVersion, compare_any, is_newer_any

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "BuildResult",
    "DiscoverResult",
    "PackageResult",
    "ValidationResult",
    "__description__",
    "discover_recipe",
    "validate_recipe",
    "load_effective_config",
    "download_file",
    "compare_any",
    "is_newer_any",
    "DiscoveredVersion",
    "NAPTError",
    "ConfigError",
    "NetworkError",
    "PackagingError",
]
