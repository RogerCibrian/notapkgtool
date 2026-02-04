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

"""File upload functionality for NAPT.

This module provides file upload capabilities for deploying packages to
Intune and other storage providers. Currently focused on Microsoft Intune
Win32 app deployment with support for .intunewin package uploads.

The module handles authentication, chunked uploads, encryption requirements,
and retry logic specific to Intune's Graph API endpoints.

Example:
    Basic Intune upload:
        ```python
        from pathlib import Path
        from napt.io.upload import upload_to_intune

        result = upload_to_intune(
            intunewin_path=Path("./MyApp.intunewin"),
            app_id="12345678-1234-1234-1234-123456789abc",
            access_token="eyJ0eXAiOi...",
        )
        print(f"Upload complete: {result}")
        ```
"""
