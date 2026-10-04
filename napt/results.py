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

"""Result types returned by napt commands.

Each dataclass here is what a ``napt`` command's underlying operation
returns: ``napt discover`` produces a DiscoverResult, ``napt build`` a
BuildResult, ``napt package`` a PackageResult, ``napt upload`` an
UploadResult, and ``napt validate`` a ValidationResult. The one
exception is DownloadResult, which comes from the shared download step
the discovery stage builds on. Command handlers consume these results
to render console output and choose exit codes; tests assert against
them.

A result exists only when the operation succeeded; a failure is an
exception. All dataclasses are frozen (immutable) to prevent accidental
mutation of return values.

Note:
    Only results that napt commands surface belong in this module. Domain types
    (like MSIMetadata) and internal types (like StrategyResult) should
    remain co-located with their related logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DownloadResult:
    """Result of a file download operation.

    Attributes:
        file_path: Path to the downloaded file.
        sha256: SHA-256 hex digest of the downloaded file.
        headers: HTTP response headers from the download.
    """

    file_path: Path
    sha256: str
    headers: dict


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
    """

    app_name: str
    app_id: str
    strategy: str
    version: str
    version_source: str
    file_path: Path
    sha256: str


@dataclass(frozen=True)
class BuildResult:
    """Result from building a PSADT package.

    Attributes:
        app_id: Unique application identifier.
        app_name: Application display name.
        version: Application version.
        build_dir: Path to the build directory (packagefiles subdirectory).
        psadt_version: PSADT version used for the build.
    """

    app_id: str
    app_name: str
    version: str
    build_dir: Path
    psadt_version: str


@dataclass(frozen=True)
class PackageResult:
    """Result from creating a .intunewin package.

    Attributes:
        build_dir: Path to the build directory.
        package_path: Path to the created .intunewin file.
        app_id: Unique application identifier.
        version: Application version.
    """

    build_dir: Path
    package_path: Path
    app_id: str
    version: str


@dataclass(frozen=True)
class UploadResult:
    """Result from uploading a .intunewin package to Microsoft Intune.

    Attributes:
        app_id: Unique application identifier (from recipe).
        app_name: Application display name.
        version: Application version uploaded.
        intune_app_id: Graph API object ID of the install app entry.
            None when build_types is "update_only".
        intune_update_app_id: Graph API object ID of the update app entry.
            None when build_types is "app_only".
        package_path: Path to the uploaded .intunewin file.
    """

    app_id: str
    app_name: str
    version: str
    package_path: Path
    intune_app_id: str | None = None
    intune_update_app_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    """Result from validating a recipe.

    Attributes:
        errors: List of error messages (empty if valid).
        warnings: List of warning messages.
        recipe_path: String path to the validated recipe file.
        parent_path: String path to the parent recipe merged beneath it, or
            None when the recipe declares no parent.
        app_id: The recipe's id, or None when it has no usable one.
    """

    errors: list[str]
    warnings: list[str]
    recipe_path: str
    parent_path: str | None = None
    app_id: str | None = None

    @property
    def is_valid(self) -> bool:
        """Whether the recipe passed: no errors were found."""
        return not self.errors
