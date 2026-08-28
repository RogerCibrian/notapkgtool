"""Tests for napt.auth.credentials."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

from azure.core.exceptions import ClientAuthenticationError
import pytest

from napt.auth import credentials
from napt.auth.credentials import (
    AuthConfig,
    AuthStore,
    get_access_token,
    get_status,
    login,
    logout,
    resolve_auth_config,
)
from napt.exceptions import AuthError, ConfigError


def _jwt(claims: dict) -> str:
    """Builds an unsigned JWT-shaped string carrying the given claims."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"eyJhbGciOiJub25lIn0.{payload.decode()}.sig"


def _active_config() -> AuthConfig | None:
    """Returns the active tenant's saved config, or None."""
    store = credentials.load_auth_store()
    if store.active is None:
        return None
    return store.tenants.get(store.active)


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    """Points NAPT's user data dir at a temp dir and clears AZURE_* env vars."""
    monkeypatch.setenv("NAPT_USER_DIR", str(tmp_path))
    for var in (
        "AZURE_CLIENT_ID",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_CLIENT_CERTIFICATE_PATH",
        "AZURE_FEDERATED_TOKEN_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def chain_fails():
    """Makes the non-interactive azure-identity chain report no credential."""
    cred = MagicMock()
    cred.get_token.side_effect = ClientAuthenticationError("no cred")
    with (
        patch("napt.auth.credentials.get_credential", return_value=cred),
        # Keep the developer's real `az login` session out of the tests.
        patch("napt.auth.credentials._azure_cli_token", return_value=None),
    ):
        yield cred


def _remember(*configs: AuthConfig, active: str | None = None) -> None:
    """Seeds the auth store with the given tenants; the last one is active."""
    store = AuthStore(
        active=active or configs[-1].tenant_id,
        tenants={c.tenant_id: c for c in configs},
    )
    credentials._save_auth_store(store)


def _fake_app(
    accounts: list | None = None,
    silent: dict | None = None,
    interactive: dict | None = None,
) -> MagicMock:
    app = MagicMock()
    app.get_accounts.return_value = accounts or []
    app.acquire_token_silent_with_error.return_value = silent
    app.acquire_token_interactive.return_value = interactive
    return app


# ---------------------------------------------------------------------------
# get_access_token
# ---------------------------------------------------------------------------


def test_get_access_token_returns_token_when_chain_succeeds() -> None:
    """Tests that the non-interactive chain's token is returned as-is."""
    mock_token = MagicMock()
    mock_token.token = "test-bearer-token"
    cred = MagicMock()
    cred.get_token.return_value = mock_token

    with patch("napt.auth.credentials.get_credential", return_value=cred):
        assert get_access_token() == "test-bearer-token"


def test_get_access_token_tells_user_to_login_when_nothing_configured(
    user_dir, chain_fails
) -> None:
    """Tests that an unconfigured interactive user is pointed at 'napt auth login'."""
    with pytest.raises(AuthError, match="napt auth login"):
        get_access_token()


def test_get_access_token_uses_cached_session(user_dir, chain_fails) -> None:
    """Tests that a cached interactive session is used silently."""
    _remember(AuthConfig("cid", "tid", "u@x"))
    app = _fake_app(accounts=[{"username": "u@x"}], silent={"access_token": "cached"})

    with patch("napt.auth.credentials._build_public_client", return_value=app):
        assert get_access_token() == "cached"

    app.get_accounts.assert_called_once_with(username="u@x")
    app.acquire_token_interactive.assert_not_called()


def test_get_access_token_never_opens_browser_without_session(
    user_dir, chain_fails
) -> None:
    """Tests that a configured app with no cached account fails instead of prompting."""
    _remember(AuthConfig("cid", "tid", "u@x"))
    app = _fake_app(accounts=[])

    with patch("napt.auth.credentials._build_public_client", return_value=app):
        with pytest.raises(AuthError, match="napt auth login"):
            get_access_token()

    app.acquire_token_interactive.assert_not_called()


def test_get_access_token_reports_expired_session(user_dir, chain_fails) -> None:
    """Tests that a session that can no longer refresh asks for a new login."""
    _remember(AuthConfig("cid", "tid", "u@x"))
    app = _fake_app(
        accounts=[{"username": "u@x"}],
        silent={"error": "invalid_grant", "error_description": "AADSTS70008 expired"},
    )

    with patch("napt.auth.credentials._build_public_client", return_value=app):
        with pytest.raises(AuthError, match="invalid_grant") as excinfo:
            get_access_token()
    assert "napt auth login" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def test_resolve_auth_config_uses_active_tenant_by_default(user_dir) -> None:
    """Tests that the active tenant's client ID and username are used."""
    assert resolve_auth_config() is None

    _remember(AuthConfig("cid-a", "tid-a", "a@x"), AuthConfig("cid-b", "tid-b", "b@x"))
    assert resolve_auth_config() == AuthConfig("cid-b", "tid-b", "b@x")


def test_resolve_auth_config_switches_tenant_by_id(user_dir) -> None:
    """Tests that --tenant-id alone selects a remembered tenant's settings."""
    _remember(AuthConfig("cid-a", "tid-a", "a@x"), AuthConfig("cid-b", "tid-b", "b@x"))
    assert resolve_auth_config(tenant_id="tid-a") == AuthConfig("cid-a", "tid-a", "a@x")


def test_resolve_auth_config_unknown_tenant_needs_client_id(user_dir) -> None:
    """Tests that a never-seen tenant needs an explicit client ID."""
    _remember(AuthConfig("cid-a", "tid-a", "a@x"))
    assert resolve_auth_config(tenant_id="tid-new") is None
    assert resolve_auth_config(tenant_id="tid-new", client_id="cid-new") == AuthConfig(
        "cid-new", "tid-new", None
    )


def test_resolve_auth_config_drops_username_when_client_changes(user_dir) -> None:
    """Tests that a different app registration does not inherit the session."""
    _remember(AuthConfig("cid-a", "tid-a", "a@x"))
    assert resolve_auth_config(client_id="cid-other") == AuthConfig(
        "cid-other", "tid-a", None
    )


def test_resolve_auth_config_ignores_azure_env_vars(user_dir, monkeypatch) -> None:
    """Tests that AZURE_* variables never configure interactive sign-in."""
    monkeypatch.setenv("AZURE_CLIENT_ID", "env-client")
    monkeypatch.setenv("AZURE_TENANT_ID", "env-tenant")
    assert resolve_auth_config() is None

    _remember(AuthConfig("saved-client", "saved-tenant", "s@x"))
    assert resolve_auth_config() == AuthConfig("saved-client", "saved-tenant", "s@x")


def test_resolve_auth_config_returns_none_when_incomplete(user_dir) -> None:
    """Tests that a client ID without a tenant ID is not enough."""
    assert resolve_auth_config(client_id="cid") is None


def test_load_auth_store_rejects_malformed_file(user_dir) -> None:
    """Tests that a corrupt auth.json raises ConfigError with a remedy."""
    (user_dir / "auth.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="napt auth login"):
        credentials.load_auth_store()


# ---------------------------------------------------------------------------
# login / logout / status
# ---------------------------------------------------------------------------


def test_login_saves_config_and_reports_permissions(user_dir) -> None:
    """Tests that a successful login persists IDs and decodes the token."""
    token = _jwt(
        {
            "preferred_username": "admin@contoso.com",
            "tid": "tid",
            "appid": "cid",
            "scp": "DeviceManagementApps.ReadWrite.All Group.Read.All",
            "exp": 1_900_000_000,
        }
    )
    app = _fake_app(interactive={"access_token": token})

    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch("napt.auth.credentials._broker_available", return_value=False),
    ):
        status = login(client_id="cid", tenant_id="tid")

    assert status.method == "interactive (browser)"
    assert status.account == "admin@contoso.com"
    assert status.missing == []
    assert _active_config() == AuthConfig("cid", "tid", "admin@contoso.com")
    kwargs = app.acquire_token_interactive.call_args.kwargs
    assert kwargs["parent_window_handle"] is None


def test_login_reuses_valid_session_without_prompt(user_dir) -> None:
    """Tests that switching to a signed-in tenant is silent."""
    _remember(AuthConfig("cid-a", "tid-a", "a@x"), AuthConfig("cid-b", "tid-b", "b@x"))
    token = _jwt({"preferred_username": "a@x", "tid": "tid-a"})
    app = _fake_app(accounts=[{"username": "a@x"}], silent={"access_token": token})

    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch("napt.auth.credentials._broker_available", return_value=False),
    ):
        status = login(tenant_id="tid-a")

    assert status.account == "a@x"
    app.acquire_token_interactive.assert_not_called()
    assert credentials.load_auth_store().active == "tid-a"


def test_login_prompts_when_cached_session_expired(user_dir) -> None:
    """Tests that an unrefreshable session falls through to interactive."""
    _remember(AuthConfig("cid", "tid", "u@x"))
    token = _jwt({"preferred_username": "u@x"})
    app = _fake_app(
        accounts=[{"username": "u@x"}],
        silent={"error": "invalid_grant", "error_description": "expired"},
        interactive={"access_token": token},
    )

    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch("napt.auth.credentials._broker_available", return_value=False),
    ):
        status = login()

    assert status.account == "u@x"
    app.acquire_token_interactive.assert_called_once()


def test_login_keeps_other_tenants(user_dir) -> None:
    """Tests that signing in to a new tenant preserves the others."""
    _remember(AuthConfig("cid-a", "tid-a", "a@x"))
    token = _jwt({"preferred_username": "b@x", "tid": "tid-b"})
    app = _fake_app(interactive={"access_token": token})

    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch("napt.auth.credentials._broker_available", return_value=False),
    ):
        login(client_id="cid-b", tenant_id="tid-b")

    store = credentials.load_auth_store()
    assert store.active == "tid-b"
    assert store.tenants["tid-a"] == AuthConfig("cid-a", "tid-a", "a@x")
    assert store.tenants["tid-b"] == AuthConfig("cid-b", "tid-b", "b@x")


def test_login_uses_broker_when_available(user_dir) -> None:
    """Tests that the broker path passes the console window handle."""
    token = _jwt({"scp": "Group.Read.All", "preferred_username": "u@x"})
    app = _fake_app(interactive={"access_token": token})

    with (
        patch("napt.auth.credentials._build_public_client", return_value=app) as build,
        patch("napt.auth.credentials._broker_available", return_value=True),
    ):
        status = login(client_id="cid", tenant_id="tid")

    assert status.method == "interactive (broker)"
    assert status.missing == ["DeviceManagementApps.ReadWrite.All"]
    assert build.call_args.kwargs["use_broker"] is True
    kwargs = app.acquire_token_interactive.call_args.kwargs
    assert kwargs["parent_window_handle"] is not None


def test_login_no_broker_flag_forces_browser(user_dir) -> None:
    """Tests that use_broker=False bypasses an available broker."""
    app = _fake_app(interactive={"access_token": _jwt({})})

    with (
        patch("napt.auth.credentials._build_public_client", return_value=app) as build,
        patch("napt.auth.credentials._broker_available", return_value=True),
    ):
        login(client_id="cid", tenant_id="tid", use_broker=False)

    assert build.call_args.kwargs["use_broker"] is False


def test_login_without_config_raises(user_dir) -> None:
    """Tests that login with no IDs anywhere explains how to supply them."""
    with pytest.raises(AuthError, match="--client-id"):
        login()


def test_login_surfaces_msal_error(user_dir) -> None:
    """Tests that an MSAL error dict becomes an AuthError with the code."""
    app = _fake_app(
        interactive={
            "error": "invalid_client",
            "error_description": "AADSTS50011: redirect URI mismatch\nTrace: x",
        }
    )
    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch("napt.auth.credentials._broker_available", return_value=False),
    ):
        with pytest.raises(AuthError, match="invalid_client: AADSTS50011") as exc:
            login(client_id="cid", tenant_id="tid")
    assert "redirect URI" in str(exc.value)
    assert _active_config() is None


def test_logout_signs_out_active_tenant_only(user_dir) -> None:
    """Tests that logout removes the active tenant's account and keeps its IDs."""
    _remember(AuthConfig("cid-a", "tid-a", "a@x"), AuthConfig("cid-b", "tid-b", "b@x"))
    app = _fake_app(accounts=[{"username": "b@x"}])

    with patch("napt.auth.credentials._build_public_client", return_value=app):
        assert logout() == ["tid-b"]

    app.get_accounts.assert_called_once_with(username="b@x")
    app.remove_account.assert_called_once()
    store = credentials.load_auth_store()
    assert store.tenants["tid-b"] == AuthConfig("cid-b", "tid-b", None)
    assert store.tenants["tid-a"] == AuthConfig("cid-a", "tid-a", "a@x")
    assert store.active == "tid-b"


def test_logout_all_signs_out_every_tenant(user_dir) -> None:
    """Tests that --all clears every remembered tenant's session."""
    _remember(AuthConfig("cid-a", "tid-a", "a@x"), AuthConfig("cid-b", "tid-b", "b@x"))
    app = _fake_app(accounts=[{"username": "x"}])

    with patch("napt.auth.credentials._build_public_client", return_value=app):
        assert sorted(logout(all_tenants=True)) == ["tid-a", "tid-b"]

    store = credentials.load_auth_store()
    assert all(c.username is None for c in store.tenants.values())


def test_logout_without_session_returns_empty(user_dir) -> None:
    """Tests that logout is a no-op when nothing was ever cached."""
    assert logout() == []


def test_get_status_reports_service_principal(user_dir, monkeypatch) -> None:
    """Tests that an application token is described as a service principal."""
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
    token = MagicMock()
    token.token = _jwt(
        {"appid": "cid", "tid": "tid", "roles": ["DeviceManagementApps.ReadWrite.All"]}
    )
    cred = MagicMock()
    cred.get_token.return_value = token

    with patch("napt.auth.credentials.get_credential", return_value=cred):
        status = get_status()

    assert status is not None
    assert status.method == "service principal"
    assert status.account == "cid"
    assert status.missing == ["Group.Read.All"]


def test_get_status_returns_none_when_unauthenticated(user_dir, chain_fails) -> None:
    """Tests that status is None with no env credential and no session."""
    assert get_status() is None


def test_status_handles_opaque_token() -> None:
    """Tests that an undecodable token still yields a status object."""
    status = credentials._status_from_token("not-a-jwt", "service principal")
    assert status.account is None
    assert status.permissions == []
    assert set(status.missing) == set(credentials.REQUIRED_PERMISSIONS)


def test_login_canceled_in_broker_explains_hidden_error(user_dir) -> None:
    """Tests that a WAM cancel points at the redirect-URI cause shown in the window."""

    class _Status:
        def __str__(self) -> str:
            return "Response_Status.Status_UserCanceled"

    app = _fake_app(
        interactive={
            "error": "broker_error",
            "error_description": "User canceled the flow. Status: ...",
            "_broker_status": _Status(),
            "correlation_id": "abc-123",
        }
    )
    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch("napt.auth.credentials._broker_available", return_value=True),
    ):
        with pytest.raises(AuthError, match="canceled") as exc:
            login(client_id="cid", tenant_id="tid")
    msg = str(exc.value)
    assert "AADSTS500113" in msg
    assert "correlation_id abc-123" in msg


def _org_response(
    domains: list[dict] | None, name: str | None = "Contoso"
) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {
        "value": [{"displayName": name, "verifiedDomains": domains or []}]
    }
    return resp


def test_login_stores_tenant_domain_and_name(user_dir) -> None:
    """Tests that a successful login records the default domain and display name."""
    token = _jwt({"preferred_username": "a@contoso.com", "tid": "tid"})
    app = _fake_app(interactive={"access_token": token})
    org = _org_response(
        [
            {"name": "contoso.onmicrosoft.com", "isInitial": True, "isDefault": False},
            {"name": "contoso.com", "isInitial": False, "isDefault": True},
        ]
    )
    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch("napt.auth.credentials._broker_available", return_value=False),
        patch("napt.auth.credentials.requests.get", return_value=org) as get,
    ):
        login(client_id="cid", tenant_id="tid")

    saved = _active_config()
    assert saved is not None
    assert saved.domain == "contoso.com"
    assert saved.display_name == "Contoso"
    assert saved.label == "Contoso (contoso.com)"
    assert get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {token}"


def test_login_without_user_read_leaves_label_empty(user_dir) -> None:
    """Tests that a Graph 403 on /organization never blocks or mislabels login."""
    import requests as _requests

    token = _jwt({"preferred_username": "a@msp.com"})
    app = _fake_app(interactive={"access_token": token})
    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch("napt.auth.credentials._broker_available", return_value=False),
        patch(
            "napt.auth.credentials.requests.get",
            side_effect=_requests.HTTPError("403 Forbidden"),
        ),
    ):
        status = login(client_id="cid", tenant_id="tid")

    assert status.account == "a@msp.com"
    saved = _active_config()
    assert saved is not None
    assert saved.label is None  # no UPN-domain guess


def test_logout_keeps_tenant_label(user_dir) -> None:
    """Tests that signing out clears the account but keeps the tenant label."""
    _remember(AuthConfig("cid", "tid", "u@x", domain="x.com", display_name="X"))
    app = _fake_app(accounts=[{"username": "u@x"}])
    with patch("napt.auth.credentials._build_public_client", return_value=app):
        logout()
    saved = credentials.load_auth_store().tenants["tid"]
    assert saved.username is None
    assert saved.label == "X (x.com)"


def test_resolve_auth_config_accepts_domain_for_tenant(user_dir) -> None:
    """Tests that --tenant-id may be a remembered tenant's default domain."""
    _remember(
        AuthConfig("cid-a", "tid-a", "a@x", domain="a.com", display_name="A"),
        AuthConfig("cid-b", "tid-b", "b@x", domain="b.com", display_name="B"),
    )
    resolved = resolve_auth_config(tenant_id="A.com")
    assert resolved is not None
    assert resolved.tenant_id == "tid-a"
    assert resolved.client_id == "cid-a"
    assert resolved.username == "a@x"
    # Unknown domains are passed through untouched so the error names them.
    assert resolve_auth_config(tenant_id="nope.com") is None


# ---------------------------------------------------------------------------
# Azure CLI session (OIDC login steps in CI)
# ---------------------------------------------------------------------------


def test_get_access_token_falls_back_to_azure_cli(user_dir, chain_fails) -> None:
    """Tests that an az login session is used when nothing else is configured."""
    with patch("napt.auth.credentials._azure_cli_token", return_value="cli-token"):
        assert get_access_token() == "cli-token"


def test_napt_session_wins_over_azure_cli(user_dir, chain_fails) -> None:
    """Tests that a developer's napt auth login beats a stray az login."""
    _remember(AuthConfig("cid", "tid", "u@x"))
    app = _fake_app(accounts=[{"username": "u@x"}], silent={"access_token": "napt"})
    with (
        patch("napt.auth.credentials._build_public_client", return_value=app),
        patch(
            "napt.auth.credentials._azure_cli_token", return_value="cli-token"
        ) as cli,
    ):
        assert get_access_token() == "napt"
    cli.assert_not_called()


def test_get_status_reports_azure_cli(user_dir, chain_fails) -> None:
    """Tests that status names the Azure CLI as the source and decodes its token."""
    token = _jwt(
        {"appid": "cid", "tid": "tid", "roles": list(credentials.REQUIRED_PERMISSIONS)}
    )
    with patch("napt.auth.credentials._azure_cli_token", return_value=token):
        status = get_status()
    assert status is not None
    assert status.method == "azure cli"
    assert status.missing == []


def test_azure_cli_token_is_none_when_unavailable() -> None:
    """Tests that a missing or signed-out Azure CLI yields None, not an error."""
    cred = MagicMock()
    cred.get_token.side_effect = ClientAuthenticationError("az not found")
    with patch("napt.auth.credentials.AzureCliCredential", return_value=cred):
        assert credentials._azure_cli_token() is None


def _cli_cred(token: str) -> MagicMock:
    access = MagicMock()
    access.token = token
    cred = MagicMock()
    cred.get_token.return_value = access
    return cred


def test_azure_cli_token_accepts_service_principal_session() -> None:
    """Tests that an app-only az session (azure/login in CI) is used."""
    token = _jwt({"idtyp": "app", "appid": "cid", "roles": ["Group.Read.All"]})
    with patch(
        "napt.auth.credentials.AzureCliCredential", return_value=_cli_cred(token)
    ):
        assert credentials._azure_cli_token() == token


def test_azure_cli_token_refuses_user_session() -> None:
    """Tests that a person's az login is refused with a pointer to napt auth login."""
    token = _jwt(
        {
            "idtyp": "user",
            "preferred_username": "dev@x",
            "scp": "DeviceManagementApps.ReadWrite.All Group.Read.All",
        }
    )
    with patch(
        "napt.auth.credentials.AzureCliCredential", return_value=_cli_cred(token)
    ):
        with pytest.raises(AuthError, match="signed in as a user") as exc:
            credentials._azure_cli_token()
    assert "napt auth login" in str(exc.value)
