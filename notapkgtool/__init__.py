"""
NAPT - Not a Pkg Tool

A Python-based CLI tool for automating Windows application packaging and
deployment to Microsoft Intune using PSAppDeployToolkit (PSADT).

NAPT provides:
  - Declarative YAML-based recipe configuration
  - Automatic version discovery from multiple sources
  - Robust download with conditional requests and integrity verification
  - Intelligent update policies (version-based, hash-based, or combined)
  - PSADT package generation (planned)
  - Direct upload to Microsoft Intune (planned)
  - Deployment wave/ring management (planned)

Quick Start
-----------
Validate a recipe and download the installer:

    $ python -m notapkgtool.cli check recipes/Google/chrome.yaml

For full CLI documentation:

    $ python -m notapkgtool.cli --help

Package Structure
-----------------
cli : module
    Command-line interface with argparse.
core : module
    High-level orchestration functions.
config : package
    YAML configuration loading and merging.
discovery : package
    Strategy pattern for discovering application versions.
versioning : package
    Version comparison and extraction from MSI/EXE files.
io : package
    Download and upload operations.
policy : package
    Update policies and deployment wave management.

Public API
----------
The primary interface is the CLI, but key functions are exported for
programmatic use:

    from notapkgtool.core import check_recipe
    from notapkgtool.config import load_effective_config
    from notapkgtool.versioning import compare_any, is_newer_any
    from notapkgtool.io import download_file

For more details, see the individual module docstrings.

Project Information
-------------------
Author: Roger Cibrian
License: GPL-3.0-only
Repository: https://github.com/RogerCibrian/notapkgtool
"""

__version__ = "0.1.0"
__author__ = "Roger Cibrian"
__license__ = "GPL-3.0-only"
__description__ = "Not a Pkg Tool - Windows/Intune packaging with PSADT"

# Re-export commonly used functions for convenience
from notapkgtool.config import load_effective_config
from notapkgtool.core import check_recipe
from notapkgtool.io import download_file
from notapkgtool.versioning import DiscoveredVersion, compare_any, is_newer_any

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "__description__",
    "check_recipe",
    "load_effective_config",
    "download_file",
    "compare_any",
    "is_newer_any",
    "DiscoveredVersion",
]
