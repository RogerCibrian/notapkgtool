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

"""Azure credential acquisition for NAPT Intune upload.

Requires a NAPT app registration in Microsoft Entra ID with the
`DeviceManagementApps.ReadWrite.All` Microsoft Graph API permission.
See the authentication documentation for setup instructions.

Authentication is selected automatically based on environment variables:

Authentication order:
    1. EnvironmentCredential -- service principal via environment variables.
        Set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and AZURE_TENANT_ID.
        Recommended for CI/CD pipelines (GitHub Actions, Azure DevOps, etc.).
    2. ManagedIdentityCredential -- Azure managed identity. Works automatically
        on Azure VMs, Azure Container Instances, and Azure-hosted pipeline
        agents with a managed identity assigned. No credentials to manage.
    3. DeviceCodeCredential -- interactive device code flow (TTY only).
        Requires AZURE_CLIENT_ID and AZURE_TENANT_ID to be set (no secret
        needed). Prints a URL and code; the user completes authentication in
        any browser. Skipped in CI/CD and when output is redirected.

If all available methods fail, an AuthError is raised with guidance on which
environment variables to set.

Example:
    Acquiring a token for Graph API:
        ```python
        from napt.upload.auth import get_access_token

        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        ```

"""

from __future__ import annotations

import os
import sys

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import (
    ChainedTokenCredential,
    CredentialUnavailableError,
    DeviceCodeCredential,
    EnvironmentCredential,
    ManagedIdentityCredential,
)

from napt.exceptions import AuthError

__all__ = ["get_access_token", "get_credential", "GRAPH_SCOPES"]

GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

_DEVICE_CODE_SCOPES = ["https://graph.microsoft.com/DeviceManagementApps.ReadWrite.All"]

_AUTH_FAILURE_HINT_NONINTERACTIVE = (
    "Authentication failed. Tried: EnvironmentCredential, "
    "ManagedIdentityCredential.\n\n"
    "To fix this, use one of the following:\n"
    "  CI/CD:      set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID\n"
    "  Azure VMs:  assign a managed identity to the resource\n"
)

_AUTH_FAILURE_HINT_INTERACTIVE_NO_CLIENT = (
    "Authentication failed. No app registration configured for interactive "
    "auth.\n\n"
    "Set AZURE_CLIENT_ID and AZURE_TENANT_ID to enable device code "
    "authentication,\n"
    "or set all three (including AZURE_CLIENT_SECRET) for service principal "
    "auth.\n\n"
    "See the authentication documentation for app registration setup "
    "instructions.\n"
)

_AUTH_FAILURE_HINT_DEVICE_CODE = (
    "Authentication failed during device code flow.\n\n"
    "To fix this:\n"
    "  Option 1:  re-run and complete the device code prompt in your browser\n"
    "  Option 2:  set AZURE_CLIENT_SECRET to use service principal auth\n"
)


def get_credential() -> ChainedTokenCredential:
    """Build the Phase 1 credential chain for non-interactive authentication.

    Returns a credential that tries service principal auth (via environment
    variables) first, then managed identity for Azure-hosted workloads.
    Both use the `.default` scope, suitable for application permissions.

    For interactive device code auth, use `get_access_token()` directly,
    which handles Phase 2 automatically when Phase 1 fails.

    Returns:
        A ChainedTokenCredential for non-interactive authentication.

    """
    return ChainedTokenCredential(
        EnvironmentCredential(),
        ManagedIdentityCredential(),
    )


def get_access_token() -> str:
    """Acquire a Microsoft Graph API access token.

    Tries credential methods in order until one succeeds:

    Phase 1 (always tried):
        EnvironmentCredential (service principal via AZURE_CLIENT_ID,
        AZURE_CLIENT_SECRET, AZURE_TENANT_ID) then ManagedIdentityCredential.
        Both use the `.default` scope (application permissions).

    Phase 2 (only if Phase 1 fails and stdout is a TTY):
        DeviceCodeCredential using AZURE_CLIENT_ID and AZURE_TENANT_ID.
        Uses the explicit DeviceManagementApps.ReadWrite.All scope, which
        triggers a consent prompt on first run.

    Returns:
        Bearer token string for use in Authorization headers.

    Raises:
        AuthError: If all credential types fail or are unavailable,
            with guidance on which environment variables to set.

    Example:
        Get a token and use it in a request:
            ```python
            from napt.upload.auth import get_access_token

            token = get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            ```

    """
    # Phase 1: service principal or managed identity
    try:
        return get_credential().get_token(*GRAPH_SCOPES).token
    except ClientAuthenticationError:
        pass

    # Phase 2: interactive device code (TTY only)
    if sys.stdout.isatty():
        client_id = os.environ.get("AZURE_CLIENT_ID", "")
        tenant_id = os.environ.get("AZURE_TENANT_ID", "")
        if client_id and tenant_id:
            try:
                return (
                    DeviceCodeCredential(
                        client_id=client_id,
                        tenant_id=tenant_id,
                    )
                    .get_token(*_DEVICE_CODE_SCOPES)
                    .token
                )
            except CredentialUnavailableError as err:
                raise AuthError(
                    f"{_AUTH_FAILURE_HINT_DEVICE_CODE}Details: {err}"
                ) from err
        raise AuthError(_AUTH_FAILURE_HINT_INTERACTIVE_NO_CLIENT)

    raise AuthError(_AUTH_FAILURE_HINT_NONINTERACTIVE)
