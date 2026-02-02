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

"""Input/Output operations for NAPT.

This module provides robust file download and upload capabilities with
features like conditional requests, retry logic, atomic writes, and
integrity verification.

Modules:
    download - HTTP(S) file download with retries, conditional requests, and checksums.
    upload - File upload adapters for Intune and storage providers (planned).

Example:
    Basic usage:
        ```python
        from pathlib import Path
        from notapkgtool.io import download_file

        file_path, sha256, headers = download_file(
            url="https://example.com/installer.msi",
            destination_folder=Path("./downloads"),
        )
        print(f"Downloaded to {file_path} with hash {sha256}")
        ```

"""

from .download import NotModifiedError, download_file, make_session

__all__ = ["download_file", "NotModifiedError", "make_session"]
