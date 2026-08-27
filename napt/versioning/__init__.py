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

Compares version strings and extracts version information from MSI and
MSIX files. Supports multiple comparison strategies and handles various
versioning schemes including semantic versioning, numeric versions, and
prerelease tags.

Versions are compared using semver-like parsing: X.Y.Z tuples with optional
prerelease and build metadata. Handles prerelease tags (alpha, beta, rc, dev)
and correctly orders 1.0.0-alpha < 1.0.0-beta < 1.0.0-rc < 1.0.0. Falls back
to lexicographic comparison for non-version-like strings (build IDs,
timestamps).

Modules:
    compare - Version comparison with semver-like parsing (compare, is_newer).
    msi - MSI metadata extraction using PowerShell COM (Windows) or
        msitools (Linux/macOS).
    msix - MSIX metadata extraction using zipfile and XML parsing
        (cross-platform).
"""
