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
to Microsoft Intune via the Graph API.

Authentication is automatic — no configuration file required:

- Developers: set AZURE_CLIENT_ID and AZURE_TENANT_ID, then complete the device code flow in a browser (DeviceCodeCredential)
- CI/CD: set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID (EnvironmentCredential)
- Azure-hosted runners: assign a managed identity to the resource (ManagedIdentityCredential)

Modules:
    manager - Upload orchestration (load config, auth, upload flow).
    graph - Graph API and Azure Blob Storage HTTP calls.
    auth - Azure credential chain via azure-identity.
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
