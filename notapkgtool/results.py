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

"""Public API return types for NAPT.

This module defines dataclasses for return values from public API functions.
These types represent the results of operations like discovery, building,
packaging, and validation.

All dataclasses are frozen (immutable) to prevent accidental mutation of
return values.

Example:
    Using result types:
        ```python
        from pathlib import Path
        from notapkgtool.core import discover_recipe
        from notapkgtool.results import DiscoverResult

        result: DiscoverResult = discover_recipe(
            Path("recipes/Google/chrome.yaml"),
            Path("./downloads")
        )
        print(result.version)  # Attribute access, not dict access
        ```

Note:
    Only public API return types belong in this module. Domain types
    (like DiscoveredVersion) and internal types (like LoadContext) should
    remain co-located with their related logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoverResult:
    """Result from discovering a version and downloading an installer.

    Attributes:
        app_name: Application display name.
        app_id: Unique application identifier.
        strategy: Discovery strategy used (e.g., "web_scrape", "api_github").
        version: Extracted version string.
        version_source: How version was determined (e.g., "regex_in_url", "msi").
        file_path: Path to the downloaded installer file.
        sha256: SHA-256 hash of the downloaded file.
        status: Always "success" for successful discovery.
    """

    app_name: str
    app_id: str
    strategy: str
    version: str
    version_source: str
    file_path: Path
    sha256: str
    status: str


@dataclass(frozen=True)
class BuildResult:
    """Result from building a PSADT package.

    Attributes:
        app_id: Unique application identifier.
        app_name: Application display name.
        version: Application version.
        build_dir: Path to the build directory.
        psadt_version: PSADT version used for the build.
        status: Build status (typically "success").
    """

    app_id: str
    app_name: str
    version: str
    build_dir: Path
    psadt_version: str
    status: str


@dataclass(frozen=True)
class PackageResult:
    """Result from creating a .intunewin package.

    Attributes:
        build_dir: Path to the build directory.
        package_path: Path to the created .intunewin file.
        app_id: Unique application identifier.
        version: Application version.
        status: Packaging status (typically "success").
    """

    build_dir: Path
    package_path: Path
    app_id: str
    version: str
    status: str


@dataclass(frozen=True)
class ValidationResult:
    """Result from validating a recipe.

    Attributes:
        status: Validation status ("valid" or "invalid").
        errors: List of error messages (empty if valid).
        warnings: List of warning messages.
        app_count: Number of apps in the recipe.
        recipe_path: String path to the validated recipe file.
    """

    status: str
    errors: list[str]
    warnings: list[str]
    app_count: int
    recipe_path: str
