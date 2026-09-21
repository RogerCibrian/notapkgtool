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

"""Version extraction and ordering utilities for NAPT.

Extracts version information and other metadata from MSI and MSIX files,
and orders version strings the way managed devices do.

Modules:
    ordering - Version ordering that mirrors the device-side comparison.
    msi - MSI metadata extraction using PowerShell COM (Windows) or
        msitools (Linux/macOS).
    msix - MSIX metadata extraction using zipfile and XML parsing
        (cross-platform).
"""
