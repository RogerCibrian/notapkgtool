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

"""Version comparison and extraction utilities for NAPT.

This package provides tools for comparing version strings and extracting
version information from MSI and MSIX files. It supports multiple
comparison strategies and handles various versioning schemes including
semantic versioning, numeric versions, and prerelease tags.

Modules:
    compare
        Core version comparison logic with semver-like parsing and robust fallbacks.
    msi
        MSI metadata extraction using PowerShell COM (Windows) or msitools (Linux/macOS).
    msix
        MSIX metadata extraction using zipfile and XML parsing (cross-platform).

Version Comparison Strategy:

Versions are compared using semver-like parsing: X.Y.Z tuples with optional
prerelease and build metadata. Handles prerelease tags (alpha, beta, rc, dev)
and correctly orders 1.0.0-alpha < 1.0.0-beta < 1.0.0-rc < 1.0.0. Falls back
to lexicographic comparison for non-version-like strings (build IDs, timestamps).

Example:
    Basic version comparison:
        ```python
        from napt.versioning import compare, is_newer

        # Compare versions (returns 1 for newer, 0 for equal, -1 for older)
        result = compare("1.2.0", "1.1.9")  # Returns: 1

        # Check if version is newer
        is_newer_version = is_newer("1.2.0", "1.1.9")  # Returns: True
        ```

    Prerelease handling:
        ```python
        # rc is newer than beta
        compare("1.0.0-rc.1", "1.0.0-beta.5")  # Returns: 1

        # Release is newer than prerelease
        compare("1.0.0", "1.0.0-rc.1")  # Returns: 1
        ```

    MSI metadata extraction:
        ```python
        from pathlib import Path
        from napt.versioning import extract_msi_metadata

        metadata = extract_msi_metadata(Path("installer.msi"))
        print(f"{metadata.product_name} {metadata.product_version} ({metadata.architecture})")
        # e.g., "Google Chrome 131.0.6778.86 (x64)"
        ```

    MSIX metadata extraction:
        ```python
        from pathlib import Path
        from napt.versioning import extract_msix_metadata

        metadata = extract_msix_metadata(Path("Slack.msix"))
        print(f"{metadata.display_name} {metadata.version} ({metadata.architecture})")
        # e.g., "Slack 4.49.81.0 (x64)"
        ```

Note:
    - Version comparison is format-agnostic: no network or file I/O
    - MSI extraction works cross-platform with appropriate backends
    - MSIX extraction works cross-platform with no external dependencies
    - Prerelease ordering follows common conventions but allows custom tags

"""

from .compare import (
    compare,
    is_newer,
    version_key,
)
from .msi import (
    MSIMetadata,
    extract_msi_metadata,
)
from .msix import (
    MSIXMetadata,
    extract_msix_metadata,
)
