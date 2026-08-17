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

"""Microsoft Graph authentication for NAPT.

Every command that talks to Intune (`napt upload`, `napt promote apply`,
`napt promote plan --reconcile/--check-drift`) calls
[get_access_token][napt.upload.auth.get_access_token] once. The token comes
from the first source that works:

Non-interactive (CI/CD):
    1. EnvironmentCredential -- service principal via AZURE_CLIENT_ID,
        AZURE_TENANT_ID and either AZURE_CLIENT_SECRET or
        AZURE_CLIENT_CERTIFICATE_PATH.
    2. WorkloadIdentityCredential -- federated (OIDC) identity, e.g. GitHub
        Actions with `azure/login`. Recommended over client secrets when the
        CI platform supports it: no secret to store or rotate.

Interactive (a person at a terminal):
    3. A session established earlier with `napt auth login`. Tokens are
        cached by MSAL in an OS-encrypted store (DPAPI on Windows, Keychain on
        macOS, libsecret on Linux) and refreshed silently; the browser or
        Windows/macOS broker is only opened by `napt auth login` itself,
        never by `napt upload`.

`napt auth login` uses the authorization code flow with PKCE against a
loopback redirect, or -- on Windows and macOS when the MSAL broker runtime is
installed -- the platform broker (Web Account Manager / Company Portal),
which gives single sign-on with the signed-in OS account and honors
device-based Conditional Access.

Requires a NAPT app registration in Microsoft Entra ID with the
`DeviceManagementApps.ReadWrite.All` and `Group.Read.All` Microsoft Graph
permissions (application permissions for CI/CD, delegated for interactive
use). See the authentication documentation for setup instructions.

Example:
    Acquiring a token for Graph API:
        ```python
        from napt.upload.auth import get_access_token

        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        ```

"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import (
    ChainedTokenCredential,
    EnvironmentCredential,
    WorkloadIdentityCredential,
)
import msal
import msal_extensions

from napt.exceptions import AuthError, ConfigError

__all__ = [
    "AuthConfig",
    "AuthStatus",
    "GRAPH_SCOPES",
    "REQUIRED_PERMISSIONS",
    "get_access_token",
    "get_credential",
    "get_status",
    "load_auth_config",
    "login",
    "logout",
    "resolve_auth_config",
]

GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

# azure-identity logs a WARNING every time the non-interactive chain comes up
# empty, which is the normal path for a signed-in developer. NAPT reports the
# outcome itself, so keep the library quiet below ERROR.
logging.getLogger("azure.identity").setLevel(logging.ERROR)

# Graph permissions NAPT needs, whether granted as application permissions
# (service principal, workload identity) or delegated permissions (interactive).
REQUIRED_PERMISSIONS = ("DeviceManagementApps.ReadWrite.All", "Group.Read.All")

_AUTHORITY_BASE = "https://login.microsoftonline.com"
_AUTH_CONFIG_FILENAME = "auth.json"
_TOKEN_CACHE_FILENAME = "token_cache.bin"

# Seconds `napt auth login` waits for the browser round-trip before giving up.
_LOGIN_TIMEOUT = 300

_HINT_NOT_LOGGED_IN = (
    "Not authenticated.\n\n"
    "  Interactive:  run 'napt auth login'\n"
    "  CI/CD:        set AZURE_CLIENT_ID, AZURE_TENANT_ID and either\n"
    "                AZURE_CLIENT_SECRET / AZURE_CLIENT_CERTIFICATE_PATH,\n"
    "                or use OIDC federation (WorkloadIdentityCredential)\n"
)

_HINT_SESSION_EXPIRED = (
    "Your sign-in session has expired or was revoked. "
    "Run 'napt auth login' to sign in again.\n"
)

_HINT_NO_CLIENT_CONFIG = (
    "No app registration configured for interactive sign-in.\n\n"
    "Run: napt auth login --client-id <id> --tenant-id <id>\n"
    "(The IDs are remembered for later logins.)\n"
)

_HINT_LOGIN_FAILED = (
    "Interactive sign-in failed.\n\n"
    "Common causes:\n"
    "  - Missing redirect URI: the app registration needs a 'Mobile and\n"
    "    desktop applications' platform with redirect URI http://localhost\n"
    "    (and ms-appx-web://Microsoft.AAD.BrokerPlugin/<client-id> for the\n"
    "    Windows broker).\n"
    "  - Delegated permissions not consented: add the delegated\n"
    "    DeviceManagementApps.ReadWrite.All and Group.Read.All permissions\n"
    "    and grant admin consent.\n"
    "  - Wrong client ID or tenant ID: check 'napt auth status'.\n"
    "  - Browser showed 'localhost refused to connect': the sign-in took\n"
    "    longer than the listener waited, or a proxy is not bypassing\n"
    "    localhost. Retry, or retry with --no-broker / without a proxy.\n"
)


@dataclass(frozen=True)
class AuthConfig:
    """App registration used for interactive sign-in.

    Attributes:
        client_id: Application (client) ID of the NAPT app registration.
        tenant_id: Directory (tenant) ID the sign-in is scoped to.
    """

    client_id: str
    tenant_id: str


@dataclass
class AuthStatus:
    """What `napt auth status` reports about the current credential.

    Attributes:
        method: Human-readable credential source, e.g. ``"service principal"``
            or ``"interactive (broker)"``.
        account: Signed-in user (UPN) for delegated tokens, or the client ID
            for application tokens. ``None`` when the token could not be
            decoded.
        tenant_id: Tenant the token was issued for, when decodable.
        client_id: App registration the token was issued to, when decodable.
        expires_at: Access token expiry, when decodable.
        permissions: Graph permissions carried by the token -- delegated
            scopes (``scp``) or application roles (``roles``).
        missing: Required Graph permissions (``REQUIRED_PERMISSIONS``) absent
            from ``permissions``.
    """

    method: str
    account: str | None = None
    tenant_id: str | None = None
    client_id: str | None = None
    expires_at: datetime | None = None
    permissions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Config and cache locations
# ---------------------------------------------------------------------------


def _user_data_dir() -> Path:
    """Returns NAPT's per-user data directory.

    Windows: ``%LOCALAPPDATA%/napt``. macOS: ``~/Library/Application
    Support/napt``. Elsewhere: ``$XDG_CONFIG_HOME/napt`` or ``~/.config/napt``.
    ``NAPT_USER_DIR`` overrides all of these.
    """
    override = os.environ.get("NAPT_USER_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "napt"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "napt"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "napt"
    return Path.home() / ".config" / "napt"


def _auth_config_path() -> Path:
    return _user_data_dir() / _AUTH_CONFIG_FILENAME


def _token_cache_path() -> Path:
    return _user_data_dir() / _TOKEN_CACHE_FILENAME


def load_auth_config() -> AuthConfig | None:
    """Reads the app registration saved by a previous `napt auth login`.

    Returns:
        The saved config, or ``None`` when no login has been run yet.

    Raises:
        ConfigError: If the file exists but is unreadable or malformed.
    """
    path = _auth_config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AuthConfig(client_id=data["client_id"], tenant_id=data["tenant_id"])
    except (OSError, ValueError, KeyError, TypeError) as err:
        raise ConfigError(
            f"Cannot read saved auth config {path}: {err}. "
            "Delete the file and run 'napt auth login' again."
        ) from err


def _save_auth_config(config: AuthConfig) -> Path:
    path = _auth_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"client_id": config.client_id, "tenant_id": config.tenant_id},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def resolve_auth_config(
    client_id: str | None = None, tenant_id: str | None = None
) -> AuthConfig | None:
    """Determines the app registration to use for interactive sign-in.

    Per field, an explicit argument wins over the config saved by the last
    `napt auth login`. ``AZURE_*`` environment variables are deliberately not
    consulted: they describe a non-interactive credential, not which app a
    person signs in to.

    Args:
        client_id: Explicit client ID (from ``--client-id``).
        tenant_id: Explicit tenant ID (from ``--tenant-id``).

    Returns:
        The resolved config, or ``None`` if either field is still unknown.

    Raises:
        ConfigError: If a saved config file exists but is malformed.
    """
    saved = load_auth_config()
    resolved_client = client_id or (saved.client_id if saved else None)
    resolved_tenant = tenant_id or (saved.tenant_id if saved else None)
    if resolved_client and resolved_tenant:
        return AuthConfig(client_id=resolved_client, tenant_id=resolved_tenant)
    return None


# ---------------------------------------------------------------------------
# Token inspection
# ---------------------------------------------------------------------------


def _decode_claims(token: str) -> dict[str, Any]:
    """Extracts the payload claims of a JWT without validating it.

    Diagnostic only -- NAPT never trusts these values for authorization, and
    Graph access tokens are not guaranteed to stay decodable. Returns an
    empty dict when the token is not a readable JWT.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, UnicodeDecodeError):
        return {}


def _status_from_token(token: str, method: str) -> AuthStatus:
    claims = _decode_claims(token)
    scopes = str(claims.get("scp", "")).split()
    roles = list(claims.get("roles") or [])
    permissions = sorted(set(scopes) | set(roles))
    account = (
        claims.get("preferred_username")
        or claims.get("upn")
        or claims.get("unique_name")
        or claims.get("appid")
        or claims.get("azp")
    )
    exp = claims.get("exp")
    return AuthStatus(
        method=method,
        account=account,
        tenant_id=claims.get("tid"),
        client_id=claims.get("appid") or claims.get("azp"),
        expires_at=(
            datetime.fromtimestamp(exp, tz=UTC)
            if isinstance(exp, (int, float))
            else None
        ),
        permissions=permissions,
        missing=[p for p in REQUIRED_PERMISSIONS if p not in permissions],
    )


# ---------------------------------------------------------------------------
# Non-interactive chain (azure-identity)
# ---------------------------------------------------------------------------


def get_credential() -> ChainedTokenCredential:
    """Builds the non-interactive credential chain.

    Service principal (environment variables), then workload identity
    federation (only when its ``AZURE_FEDERATED_TOKEN_FILE`` etc. variables
    are present). Both use the `.default` scope, suitable for application
    permissions.

    Returns:
        A ChainedTokenCredential for non-interactive authentication.
    """
    credentials: list[Any] = [EnvironmentCredential()]
    if all(
        os.environ.get(var)
        for var in (
            "AZURE_TENANT_ID",
            "AZURE_CLIENT_ID",
            "AZURE_FEDERATED_TOKEN_FILE",
        )
    ):
        credentials.append(WorkloadIdentityCredential())
    return ChainedTokenCredential(*credentials)


def _describe_noninteractive_method() -> str:
    if os.environ.get("AZURE_CLIENT_SECRET") or os.environ.get(
        "AZURE_CLIENT_CERTIFICATE_PATH"
    ):
        return "service principal"
    return "workload identity (OIDC)"


# ---------------------------------------------------------------------------
# Interactive session (MSAL)
# ---------------------------------------------------------------------------


def _broker_available() -> bool:
    """Whether the MSAL broker runtime is importable on this platform."""
    if sys.platform not in ("win32", "darwin"):
        return False
    try:
        import pymsalruntime  # noqa: F401  # pyright: ignore[reportMissingImports]
    except ImportError:
        return False
    return True


def _build_token_cache() -> msal_extensions.PersistedTokenCache:
    """Opens NAPT's OS-encrypted token cache, creating the directory if needed."""
    path = _token_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        persistence = msal_extensions.build_encrypted_persistence(str(path))
    except Exception as err:  # msal_extensions raises platform-specific types
        raise AuthError(
            f"Cannot open an encrypted token cache at {path}: {err}\n"
            "Interactive sign-in needs the OS credential store (DPAPI, "
            "Keychain, or libsecret). Use a service principal instead."
        ) from err
    return msal_extensions.PersistedTokenCache(persistence)


def _build_public_client(
    config: AuthConfig, *, use_broker: bool
) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        config.client_id,
        authority=f"{_AUTHORITY_BASE}/{config.tenant_id}",
        token_cache=_build_token_cache(),
        enable_broker_on_windows=use_broker,
        enable_broker_on_mac=use_broker,
    )


def _msal_error(result: dict[str, Any]) -> str:
    code = result.get("error", "unknown_error")
    description = str(result.get("error_description", "")).splitlines()
    return f"{code}: {description[0]}" if description else str(code)


def _acquire_silent(config: AuthConfig, *, use_broker: bool) -> str | None:
    """Returns a cached/refreshed token for the saved session, or ``None``.

    ``None`` means no account is cached. An account whose session can no
    longer be refreshed raises AuthError instead, since that needs a new
    login rather than a different credential.
    """
    app = _build_public_client(config, use_broker=use_broker)
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent_with_error(GRAPH_SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        detail = _msal_error(result) if result else "no token"
        raise AuthError(f"{_HINT_SESSION_EXPIRED}Details: {detail}")
    return result["access_token"]


def _interactive_config() -> AuthConfig | None:
    """The interactive app registration, or ``None`` when unconfigured."""
    try:
        return resolve_auth_config()
    except ConfigError:
        return None


def login(
    *,
    client_id: str | None = None,
    tenant_id: str | None = None,
    use_broker: bool = True,
) -> AuthStatus:
    """Signs a user in interactively and persists the session.

    Opens the platform broker (Windows/macOS, when the MSAL broker runtime is
    installed and ``use_broker`` is true) or the system browser, then stores
    the resulting account in NAPT's encrypted token cache so later commands
    authenticate silently. Also saves the client/tenant IDs so future logins
    don't need them repeated.

    Args:
        client_id: App registration client ID; overrides the saved config.
        tenant_id: Tenant ID; overrides the saved config.
        use_broker: Prefer the OS broker over a browser when available.

    Returns:
        Status of the newly acquired token, including any missing
        permissions.

    Raises:
        AuthError: If no app registration is configured or the sign-in fails.
        ConfigError: If the saved auth config is malformed.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    config = resolve_auth_config(client_id, tenant_id)
    if config is None:
        raise AuthError(_HINT_NO_CLIENT_CONFIG)

    broker = use_broker and _broker_available()
    app = _build_public_client(config, use_broker=broker)
    logger.verbose(
        "AUTH",
        f"Signing in to tenant {config.tenant_id} as app {config.client_id} "
        f"({'broker' if broker else 'browser'})",
    )

    def _announce(ui: str = "browser", **_: Any) -> None:
        if ui == "broker":
            print("A sign-in window will open. Choose your work account.")
        else:
            print("Opening your browser to sign in...")

    try:
        result = app.acquire_token_interactive(
            GRAPH_SCOPES,
            prompt="select_account",
            timeout=_LOGIN_TIMEOUT,
            parent_window_handle=(
                msal.PublicClientApplication.CONSOLE_WINDOW_HANDLE if broker else None
            ),
            on_before_launching_ui=_announce,
        )
    except Exception as err:  # MSAL surfaces transport/broker failures as raw errors
        raise AuthError(f"{_HINT_LOGIN_FAILED}Details: {err}") from err

    if "access_token" not in result:
        raise AuthError(f"{_HINT_LOGIN_FAILED}Details: {_msal_error(result)}")

    saved_to = _save_auth_config(config)
    logger.verbose("AUTH", f"Saved app registration to {saved_to}")

    method = "interactive (broker)" if broker else "interactive (browser)"
    status = _status_from_token(result["access_token"], method)
    if not status.account:
        claims = result.get("id_token_claims")
        if isinstance(claims, dict):
            status.account = claims.get("preferred_username")
    return status


def logout() -> bool:
    """Removes the cached interactive session.

    Signs every cached account out of NAPT's token cache (and the OS broker,
    when it was used). The saved client/tenant IDs are kept so the next
    `napt auth login` needs no arguments.

    Returns:
        True if a session was removed, False if none was cached.

    Raises:
        ConfigError: If the saved auth config is malformed.
    """
    config = resolve_auth_config()
    if config is None or not _token_cache_path().exists():
        return False
    app = _build_public_client(config, use_broker=_broker_available())
    accounts = app.get_accounts()
    for account in accounts:
        app.remove_account(account)
    return bool(accounts)


def get_status() -> AuthStatus | None:
    """Reports which credential NAPT would use right now, or ``None``.

    Resolves a token exactly as [get_access_token][napt.upload.auth.get_access_token]
    does -- so the answer reflects what `napt upload` will do -- and
    decodes it for display.

    Returns:
        The current credential's status, or ``None`` when nothing is
        configured or signed in.

    Raises:
        AuthError: If a credential is configured but fails (for example, a
            saved session that can no longer be refreshed).
    """
    try:
        token = get_credential().get_token(*GRAPH_SCOPES).token
        return _status_from_token(token, _describe_noninteractive_method())
    except ClientAuthenticationError:
        pass

    config = _interactive_config()
    if config is None:
        return None
    broker = _broker_available()
    token = _acquire_silent(config, use_broker=broker)
    if token is None:
        return None
    return _status_from_token(
        token, "interactive (broker)" if broker else "interactive (browser)"
    )


def get_access_token() -> str:
    """Acquires a Microsoft Graph access token.

    Tries the non-interactive chain from
    [get_credential][napt.upload.auth.get_credential] first, then the session
    saved by `napt auth login`. Never opens a browser: an interactive user
    who has not logged in is told to run `napt auth login`.

    Returns:
        Bearer token string for use in Authorization headers.

    Raises:
        AuthError: If no credential is available or the saved session can no
            longer be refreshed, with guidance on what to do.

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
    except ClientAuthenticationError:
        pass

    config = _interactive_config()
    if config is not None:
        token = _acquire_silent(config, use_broker=_broker_available())
        if token is not None:
            return token

    raise AuthError(_HINT_NOT_LOGGED_IN)
