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
version information from binary files (MSI, EXE). It supports multiple
comparison strategies and handles various versioning schemes including
semantic versioning, numeric versions, and prerelease tags.

Modules:
    keys
        Core version comparison logic with semver-like parsing and robust fallbacks.
    msi
        MSI ProductVersion extraction and metadata extraction using msilib, _msi,
        PowerShell, or msitools.

Version Comparison Strategies:

The versioning system supports multiple comparison modes:

1. **Semantic Versioning (semver)**:
   - Parses X.Y.Z tuples with optional prerelease and build metadata
   - Handles prerelease tags: alpha, beta, rc, dev, etc.
   - Correctly orders: 1.0.0-alpha < 1.0.0-beta < 1.0.0-rc < 1.0.0

2. **Numeric (MSI/EXE)**:
   - Strict numeric-only parsing
   - MSI: 3-part versions (major.minor.patch)
   - EXE: 4-part versions (major.minor.patch.build)

3. **Lexicographic**:
   - Fallback string comparison for non-version-like strings
   - Useful for build IDs, timestamps, etc.

Example:
    Basic version comparison:
        ```python
        from napt.versioning import compare_any, is_newer_any

        # Compare versions (returns 1 for newer, 0 for equal, -1 for older)
        result = compare_any("1.2.0", "1.1.9")  # Returns: 1

        # Check if version is newer
        is_newer = is_newer_any("1.2.0", "1.1.9")  # Returns: True
        ```

    Prerelease handling:
        ```python
        # rc is newer than beta
        compare_any("1.0.0-rc.1", "1.0.0-beta.5")  # Returns: 1

        # Release is newer than prerelease
        compare_any("1.0.0", "1.0.0-rc.1")  # Returns: 1
        ```

    MSI version extraction:
        ```python
        from pathlib import Path
        from napt.versioning.msi import version_from_msi_product_version

        discovered = version_from_msi_product_version(Path("installer.msi"))
        print(discovered.version)  # e.g., "1.2.3"
        ```

    MSI metadata extraction:
        ```python
        from pathlib import Path
        from napt.versioning.msi import extract_msi_metadata

        metadata = extract_msi_metadata(Path("installer.msi"))
        print(f"{metadata.product_name} {metadata.product_version}")
        # e.g., "Google Chrome 131.0.6778.86"
        ```

    MSI architecture extraction:
        ```python
        from pathlib import Path
        from napt.versioning.msi import extract_msi_architecture

        arch = extract_msi_architecture(Path("installer.msi"))
        print(f"Architecture: {arch}")  # e.g., "x64"
        ```

Note:
    - Version comparison is format-agnostic: no network or file I/O
    - MSI extraction works cross-platform with appropriate backends
    - Prerelease ordering follows common conventions but allows custom tags

"""

from .keys import (
    DiscoveredVersion,
    SourceHint,
    compare_any,
    is_newer_any,
    version_key_any,
)
from .msi import (
    MSIMetadata,
    architecture_from_template,
    extract_msi_architecture,
    extract_msi_metadata,
)
