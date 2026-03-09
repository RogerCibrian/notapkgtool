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

"""Default configuration values for NAPT.

This module provides the baseline configuration that ships with NAPT. These
defaults are always applied first, then overridden by organization defaults
(org.yaml), vendor defaults, and finally recipe-specific settings.

The configuration hierarchy is:
    1. Code defaults (this module) - always present
    2. Organization defaults (defaults/org.yaml) - optional overrides
    3. Vendor defaults (defaults/vendors/{Vendor}.yaml) - optional overrides
    4. Recipe configuration - required, app-specific settings

This design ensures that NAPT works out of the box without requiring any
configuration files, while still allowing full customization when needed.

Note:
    Authentication for 'napt upload' requires no config file. Developers set
    AZURE_CLIENT_ID and AZURE_TENANT_ID and complete the device code flow;
    CI/CD pipelines set all three env vars including AZURE_CLIENT_SECRET.
"""

from __future__ import annotations

from typing import Any

# Default configuration values that ship with NAPT.
# These provide sensible defaults for all settings, ensuring NAPT works
# without requiring a defaults/org.yaml file.
DEFAULT_CONFIG: dict[str, Any] = {
    "defaults": {
        # PSADT (PowerShell App Deployment Toolkit) settings
        "psadt": {
            "release": "latest",
            "cache_dir": "cache/psadt",
            # Brand pack is not set by default - users must configure their own
            "brand_pack": {
                "path": "",
                "mappings": [],
            },
            # Default app variables injected into PSADT scripts
            "app_vars": {
                "AppLang": "EN",
                "AppRevision": "01",
                "AppSuccessExitCodes": [0],
                "AppRebootExitCodes": [1641, 3010],
                "AppProcessesToClose": [],
                "AppScriptVersion": "1.0.0",
                "AppScriptAuthor": "napt",
                "RequireAdmin": True,
            },
        },
        # Discovery output settings
        "discover": {
            "output_dir": "downloads",
        },
        # Build output settings
        "build": {
            "output_dir": "builds",
        },
        # Package output settings
        "package": {
            "output_dir": "packages",
        },
        # Windows/Intune settings
        "win32": {
            "build_types": "both",
            "installed_check": {
                "log_format": "cmtrace",
                "log_level": "INFO",
                "log_rotation_mb": 3,
                "detection": {
                    "exact_match": False,
                },
            },
        },
    },
}


# Template for org.yaml created by `napt init`.
# This is a commented template showing available options, not required values.
ORG_YAML_TEMPLATE = """\
# NAPT Organization Defaults
# ==========================
# This file contains organization-wide defaults that apply to all recipes.
# All fields are optional - NAPT has sensible built-in defaults.
# Uncomment and modify only the settings you want to customize.
#
# Configuration hierarchy:
#   1. NAPT built-in defaults (always present)
#   2. This file (org.yaml) - your organization overrides
#   3. Vendor defaults (defaults/vendors/<Vendor>.yaml)
#   4. Recipe configuration (recipes/<Vendor>/<app>.yaml)

apiVersion: napt/v1

defaults:
  # PSADT settings
  # psadt:
  #   # PSADT release: "latest" or specific version (e.g., "4.1.7")
  #   release: "latest"
  #
  #   # Custom branding (logo/banner)
  #   brand_pack:
  #     path: brand-packs/my-company
  #     mappings:
  #       - source: "AppIcon.*"
  #         target: "Assets/AppIcon"
  #       - source: "Banner.Classic.*"
  #         target: "Assets/Banner.Classic"
  #
  #   # Default app variables
  #   app_vars:
  #     AppScriptAuthor: "IT Team"

  # Discovery output settings
  # discover:
  #   output_dir: "downloads"

  # Build output settings
  # build:
  #   output_dir: "builds"

  # Package output settings
  # package:
  #   output_dir: "packages"

  # Windows/Intune detection settings
  # win32:
  #   build_types: "both"  # both, app_only, update_only
  #   installed_check:
  #     log_format: "cmtrace"  # cmtrace or legacy
  #     log_level: "INFO"      # DEBUG, INFO, WARNING, ERROR
  #     log_rotation_mb: 3
  #     detection:
  #       exact_match: false  # true = version must match exactly
"""
