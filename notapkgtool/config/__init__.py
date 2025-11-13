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

"""Configuration loading and management for NAPT.

This module provides tools for loading, merging, and validating YAML-based
configuration files with a layered approach:

  - Organization-wide defaults (defaults/org.yaml)
  - Vendor-specific defaults (defaults/vendors/<Vendor>.yaml)
  - Recipe-specific configuration (recipes/<Vendor>/<app>.yaml)

The loader performs deep merging where dicts are merged recursively and
lists/scalars are replaced (last wins). Relative paths are resolved against
the recipe file location for relocatability.

Public API:

- load_effective_config: Load and merge configuration for a recipe

Example:
    Basic usage:

        from pathlib import Path
        from notapkgtool.config import load_effective_config

        config = load_effective_config(Path("recipes/Google/chrome.yaml"))
        first_app = config.get("apps", [])[0]
        print(first_app["name"])  # "Google Chrome"

"""

from .loader import load_effective_config

__all__ = ["load_effective_config"]
