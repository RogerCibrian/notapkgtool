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

"""Download operations for NAPT.

Provides robust HTTP(S) file download with conditional requests, retry logic,
atomic writes, and integrity verification.

Example:
    Basic usage:
        ```python
        from pathlib import Path
        from napt.download import download_file

        result = download_file(
            url="https://example.com/installer.msi",
            destination_folder=Path("./downloads/my-app"),
        )
        print(f"Downloaded to {result.file_path} with hash {result.sha256}")
        ```

"""

from napt.exceptions import NotModifiedError

from .download import download_file

__all__ = ["download_file", "NotModifiedError"]
