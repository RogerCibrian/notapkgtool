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

Provides a credential chain that tries authentication methods in order.
No configuration is required — the right method is selected automatically
based on the environment.

Authentication order:
    1. EnvironmentCredential -- service principal via environment variables.
        Set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and AZURE_TENANT_ID.
        Recommended for CI/CD pipelines (GitHub Actions, Azure DevOps, etc.).
    2. ManagedIdentityCredential -- Azure managed identity. Works automatically
        on Azure VMs, Azure Container Instances, and Azure-hosted pipeline
        agents with a managed identity assigned. No credentials to manage.
    3. AzureCliCredential -- reuses the session from 'az login'. Requires
        Azure CLI to be installed and authenticated.
    4. DeviceCodeCredential -- interactive device code flow. Only attempted
        when stdout is a TTY (interactive terminal). Prints a URL and code;
        the user completes authentication in any browser. Skipped in CI/CD
        and when output is redirected, to avoid hanging on an unattended prompt.

If all available methods fail, an AuthError is raised with guidance on which
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

import sys

from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    CredentialUnavailableError,
    DeviceCodeCredential,
    EnvironmentCredential,
    ManagedIdentityCredential,
)

from napt.exceptions import AuthError

__all__ = ["get_access_token", "get_credential", "GRAPH_SCOPES"]

GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

_AUTH_FAILURE_HINT_NONINTERACTIVE = (
    "Authentication failed. Tried: EnvironmentCredential, "
    "ManagedIdentityCredential, AzureCliCredential.\n\n"
    "To fix this, use one of the following:\n"
    "  Developers:  az login  (then re-run)\n"
    "  CI/CD:       set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID\n"
    "  Azure VMs:   assign a managed identity to the resource\n"
)

_AUTH_FAILURE_HINT_INTERACTIVE = (
    "Authentication failed. Tried: EnvironmentCredential, "
    "ManagedIdentityCredential, AzureCliCredential, DeviceCodeCredential.\n\n"
    "To fix this, use one of the following:\n"
    "  Option 1:  re-run and complete the device code prompt in your browser\n"
    "  Option 2:  az login  (then re-run)\n"
    "  Option 3:  set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID\n"
)


def get_credential() -> ChainedTokenCredential:
    """Build a ChainedTokenCredential that tries auth methods in order.

    Constructs a credential chain. In interactive terminal sessions
    (stdout is a TTY), DeviceCodeCredential is appended as a final
    fallback so developers can authenticate without installing Azure CLI.
    In non-interactive environments (CI/CD, redirected output),
    DeviceCodeCredential is omitted to avoid hanging on an unattended prompt.

    Returns:
        A ChainedTokenCredential configured for the current environment.

    """
    credentials = [
        EnvironmentCredential(),
        ManagedIdentityCredential(),
        AzureCliCredential(),
    ]
    if sys.stdout.isatty():
        credentials.append(DeviceCodeCredential())
    return ChainedTokenCredential(*credentials)


def get_access_token() -> str:
    """Acquire a Microsoft Graph API access token.

    Tries credential methods in order until one succeeds. In interactive
    sessions, DeviceCodeCredential is included as a final fallback.

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
    interactive = sys.stdout.isatty()
    hint = (
        _AUTH_FAILURE_HINT_INTERACTIVE
        if interactive
        else _AUTH_FAILURE_HINT_NONINTERACTIVE
    )
    try:
        return get_credential().get_token(*GRAPH_SCOPES).token
    except CredentialUnavailableError as err:
        raise AuthError(f"{hint}Details: {err}") from err
