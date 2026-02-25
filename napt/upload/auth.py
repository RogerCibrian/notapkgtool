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

Provides a credential chain that tries three authentication methods in order.
No configuration is required — the right method is selected automatically
based on the environment.

Authentication order:
    1. EnvironmentCredential -- service principal via environment variables.
        Set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and AZURE_TENANT_ID.
        Recommended for CI/CD pipelines (GitHub Actions, Azure DevOps, etc.).
    2. ManagedIdentityCredential -- Azure managed identity. Works automatically
        on Azure VMs, Azure Container Instances, and Azure-hosted pipeline
        agents with a managed identity assigned. No credentials to manage.
    3. AzureCliCredential -- reuses the session from 'az login'. The
        recommended approach for developers. Run 'az login' once and NAPT
        will reuse that session for all subsequent uploads.

If all three methods fail, an AuthError is raised with guidance on which
environment variables to set or which command to run.

Example:
    Acquiring a token for Graph API:
        ```python
        from napt.upload.auth import get_access_token

        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        ```

"""

from __future__ import annotations

from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    CredentialUnavailableError,
    EnvironmentCredential,
    ManagedIdentityCredential,
)

from napt.exceptions import AuthError

__all__ = ["get_access_token", "get_credential", "GRAPH_SCOPES"]

GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

_TRIED = ["EnvironmentCredential", "ManagedIdentityCredential", "AzureCliCredential"]

_AUTH_FAILURE_HINT = (
    "Authentication failed. Tried: EnvironmentCredential, "
    "ManagedIdentityCredential, AzureCliCredential.\n\n"
    "To fix this, use one of the following:\n"
    "  Developers:  az login\n"
    "  CI/CD:       set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID\n"
    "  Azure VMs:   assign a managed identity to the resource\n"
)


def get_credential() -> ChainedTokenCredential:
    """Build a ChainedTokenCredential that tries auth methods in order.

    Constructs a credential chain with three authentication methods.
    No configuration is needed — the appropriate method is detected
    automatically from the environment.

    Returns:
        A ChainedTokenCredential that tries EnvironmentCredential,
            ManagedIdentityCredential, and AzureCliCredential in that order.

    """
    return ChainedTokenCredential(
        EnvironmentCredential(),
        ManagedIdentityCredential(),
        AzureCliCredential(),
    )


def get_access_token() -> str:
    """Acquire a Microsoft Graph API access token.

    Tries EnvironmentCredential, ManagedIdentityCredential, and
    AzureCliCredential in order until one succeeds.

    Returns:
        Bearer token string for use in Authorization headers.

    Raises:
        AuthError: If all credential types fail or are unavailable,
            with guidance on which environment variables to set or
            which command to run.

    Example:
        Get a token and use it in a request:
            ```python
            from napt.upload.auth import get_access_token

            token = get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            ```

    """
    try:
        return get_credential().get_token(*GRAPH_SCOPES).token
    except CredentialUnavailableError as err:
        raise AuthError(f"{_AUTH_FAILURE_HINT}Details: {err}") from err
