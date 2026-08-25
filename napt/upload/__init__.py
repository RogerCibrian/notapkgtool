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

"""Intune upload operations for NAPT.

This module provides the complete upload pipeline for deploying Win32 LOB apps
to Microsoft Intune via the Graph API. Authentication comes from
[napt.auth][] and the Graph calls from [napt.graph][].

Modules:
    manager - Upload orchestration (load config, auth, upload flow).
    intunewin - .intunewin ZIP parser (reads Detection.xml encryption metadata).

Example:
    Upload a packaged app to Intune:
        ```python
        from pathlib import Path
        from napt.upload import upload_package

        result = upload_package(Path("recipes/Google/chrome.yaml"))
        print(f"Intune app ID: {result.intune_app_id}")
        print(f"Version: {result.version}")
        ```

"""

from .manager import upload_package

__all__ = ["upload_package"]
