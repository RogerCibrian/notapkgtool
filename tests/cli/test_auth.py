"""Tests for napt.cli.auth."""

from __future__ import annotations

from unittest.mock import patch

from napt.auth.credentials import AuthStatus
from napt.cli.auth import (
    cmd_auth_login,
    cmd_auth_logout,
    cmd_auth_setup,
    cmd_auth_status,
)
from napt.exceptions import AuthError, ConfigError
from tests.cli.conftest import _args


class TestCmdAuth:
    """Tests for the 'napt auth' subcommand handlers."""

    def test_login_prints_account_and_permissions(self, capsys):
        """Tests that a successful login prints the signed-in status block."""
        status = AuthStatus(
            method="interactive (broker)",
            account="admin@contoso.com",
            tenant_id="tid",
            client_id="cid",
            permissions=["DeviceManagementApps.ReadWrite.All", "Group.Read.All"],
        )
        with patch("napt.cli.auth.auth_login", return_value=status) as login:
            code = cmd_auth_login(
                _args(client_id="cid", tenant_id="tid", no_broker=True)
            )
        assert code == 0
        assert login.call_args.kwargs["use_broker"] is False
        out = capsys.readouterr().out
        assert "[OK] Signed in as admin@contoso.com" in out
        assert "interactive (broker)" in out
        assert "[WARNING]" not in out

    def test_login_warns_about_missing_permissions(self, capsys):
        """Tests that a token lacking required permissions is flagged."""
        status = AuthStatus(
            method="interactive (browser)",
            account="u@x",
            permissions=["Group.Read.All"],
            missing=["DeviceManagementApps.ReadWrite.All"],
        )
        with patch("napt.cli.auth.auth_login", return_value=status):
            code = cmd_auth_login(
                _args(client_id=None, tenant_id=None, no_broker=False)
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "Missing required permissions: DeviceManagementApps" in out

    def test_login_auth_error_returns_one(self, capsys):
        """Tests that AuthError from login is reported and returns 1."""
        with patch(
            "napt.cli.auth.auth_login", side_effect=AuthError("no redirect uri")
        ):
            code = cmd_auth_login(
                _args(client_id=None, tenant_id=None, no_broker=False)
            )
        assert code == 1
        assert "Authentication error: no redirect uri" in capsys.readouterr().out

    def test_logout_reports_removed_session(self, capsys):
        """Tests that logout confirms which tenants were signed out."""
        with patch("napt.cli.auth.auth_logout", return_value=["tid-a"]) as lo:
            assert cmd_auth_logout(_args(all=False)) == 0
        assert lo.call_args.kwargs["all_tenants"] is False
        assert "[OK] Signed out of 1 tenant(s): tid-a" in capsys.readouterr().out

    def test_logout_all_passes_flag(self, capsys):
        """Tests that --all is forwarded to the auth module."""
        with patch("napt.cli.auth.auth_logout", return_value=["a", "b"]) as lo:
            assert cmd_auth_logout(_args(all=True)) == 0
        assert lo.call_args.kwargs["all_tenants"] is True

    def test_logout_reports_nothing_to_do(self, capsys):
        """Tests that logout says so when no session was cached."""
        with patch("napt.cli.auth.auth_logout", return_value=[]):
            assert cmd_auth_logout(_args(all=False)) == 0
        assert "No interactive session" in capsys.readouterr().out

    def test_status_lists_known_tenants(self, capsys, tmp_path, monkeypatch):
        """Tests that interactive status lists remembered tenants, marking the active."""
        from napt.auth.credentials import AuthConfig, AuthStore, _save_auth_store

        monkeypatch.setenv("NAPT_USER_DIR", str(tmp_path))
        _save_auth_store(
            AuthStore(
                active="tid-b",
                tenants={
                    "tid-a": AuthConfig(
                        "cid-a", "tid-a", "a@x", domain="a.com", display_name="A"
                    ),
                    "tid-b": AuthConfig("cid-b", "tid-b", "b@x"),
                },
            )
        )
        status = AuthStatus(
            method="interactive (browser)",
            account="b@x",
            permissions=["DeviceManagementApps.ReadWrite.All", "Group.Read.All"],
        )
        with patch("napt.cli.auth.auth_status", return_value=status):
            assert cmd_auth_status(_args()) == 0
        out = capsys.readouterr().out
        assert "Known tenants:" in out
        assert (
            "    A (a.com)\n"
            "      Account:   a@x\n"
            "      Tenant ID: tid-a\n"
            "      Client ID: cid-a\n"
            "  * (name unknown)\n"
            "      Account:   b@x\n"
            "      Tenant ID: tid-b\n"
            "      Client ID: cid-b\n"
        ) in out

    def test_status_not_authenticated_returns_one(self, capsys):
        """Tests that status exits 1 and points at login when unauthenticated."""
        with patch("napt.cli.auth.auth_status", return_value=None):
            assert cmd_auth_status(_args()) == 1
        out = capsys.readouterr().out
        assert "Not authenticated" in out
        assert "napt auth login" in out

    def test_status_ok_returns_zero(self, capsys):
        """Tests that a fully permissioned credential exits 0."""
        status = AuthStatus(
            method="service principal",
            account="cid",
            permissions=["DeviceManagementApps.ReadWrite.All", "Group.Read.All"],
        )
        with patch("napt.cli.auth.auth_status", return_value=status):
            assert cmd_auth_status(_args()) == 0
        assert "service principal" in capsys.readouterr().out

    def test_status_missing_permission_returns_one(self, capsys):
        """Tests that a credential missing a required permission exits 1."""
        status = AuthStatus(
            method="service principal",
            account="cid",
            permissions=[],
            missing=["DeviceManagementApps.ReadWrite.All", "Group.Read.All"],
        )
        with patch("napt.cli.auth.auth_status", return_value=status):
            assert cmd_auth_status(_args()) == 1
        assert "[WARNING] Missing required permissions" in capsys.readouterr().out

    def test_status_auth_error_returns_one(self, capsys):
        """Tests that an expired session surfaces as an authentication error."""
        with patch("napt.cli.auth.auth_status", side_effect=AuthError("expired")):
            assert cmd_auth_status(_args()) == 1
        assert "Authentication error: expired" in capsys.readouterr().out

    @staticmethod
    def _setup_args(**overrides):
        defaults = {
            "tenant_id": "tid",
            "name": "NAPT",
            "client_id": None,
            "federated_issuer": None,
            "federated_subject": None,
            "federated_audience": "api://AzureADTokenExchange",
            "federated_name": None,
            "adopt": False,
            "print_only": False,
        }
        defaults.update(overrides)
        return _args(**defaults)

    def test_setup_warns_and_exits_one_when_adopt_is_needed(self, capsys):
        """Tests that an unstamped name match prints the adopt warning and fails."""
        from napt.auth.registration import SetupResult

        result = SetupResult(
            tenant_id="tid", client_id="cid", display_name="NAPT", needs_adopt=True
        )
        with patch(
            "napt.cli.auth.setup_app_registration", return_value=result
        ) as setup:
            assert cmd_auth_setup(self._setup_args()) == 1
        assert setup.call_args.args[0].adopt is False
        out = capsys.readouterr().out
        assert "[WARNING] Found existing registration 'NAPT' (cid)" in out
        assert "Re-run with --adopt" in out
        assert "never removes existing settings" in out
        assert (
            "To create a new registration instead, re-run with "
            "--name <a name other than 'NAPT'>." in out
        )

    def test_setup_reports_adoption(self, capsys):
        """Tests that --adopt is forwarded and an adopted registration is announced."""
        from napt.auth.registration import SPEC_VERSION, SetupResult

        result = SetupResult(
            tenant_id="tid",
            client_id="cid",
            display_name="NAPT",
            adopted=True,
            changes=["Stamped internal notes: napt/v1 spec=1 version=x"],
        )
        with patch(
            "napt.cli.auth.setup_app_registration", return_value=result
        ) as setup:
            assert cmd_auth_setup(self._setup_args(adopt=True)) == 0
        assert setup.call_args.args[0].adopt is True
        out = capsys.readouterr().out
        assert (
            f"[OK] Adopted 'NAPT' (cid) -- stamped as napt/v1 spec={SPEC_VERSION}"
            in (out)
        )

    def test_setup_reports_changes_and_next_steps(self, capsys):
        """Tests that a provisioning run lists its changes and the IDs to use."""
        from napt.auth.registration import SetupResult

        result = SetupResult(
            tenant_id="tid",
            client_id="cid",
            display_name="NAPT",
            created=True,
            changes=["Created app registration 'NAPT'", "Created service principal"],
        )
        with patch(
            "napt.cli.auth.setup_app_registration", return_value=result
        ) as setup:
            assert (
                cmd_auth_setup(
                    self._setup_args(
                        federated_issuer="https://issuer", federated_subject="sub"
                    )
                )
                == 0
            )
        spec = setup.call_args.args[0]
        assert spec.tenant_id == "tid"
        assert spec.federated_issuer == "https://issuer"
        assert spec.federated_subject == "sub"
        out = capsys.readouterr().out
        assert "[OK] App registration is ready" in out
        assert "  - Created service principal" in out
        assert "Client ID:  cid" in out
        assert "OIDC login mint the token" in out

    def test_setup_rejects_half_specified_federated_credential(self, capsys):
        """Tests that --federated-issuer without --federated-subject fails early."""
        with patch("napt.cli.auth.setup_app_registration") as setup:
            code = cmd_auth_setup(self._setup_args(federated_issuer="https://issuer"))
        assert code == 1
        setup.assert_not_called()
        assert "both an issuer and a subject" in capsys.readouterr().out

    def test_setup_reports_nothing_to_change(self, capsys):
        """Tests that a complete registration is reported as already done."""
        from napt.auth.registration import SetupResult

        result = SetupResult(tenant_id="tid", client_id="cid", display_name="NAPT")
        with patch("napt.cli.auth.setup_app_registration", return_value=result):
            assert cmd_auth_setup(self._setup_args()) == 0
        out = capsys.readouterr().out
        assert "is at spec 1; nothing to change" in out
        assert "--federated-issuer/--federated-subject" in out

    def test_setup_print_only_never_calls_graph(self, capsys):
        """Tests that --print-only prints the checklist without signing in."""
        with patch("napt.cli.auth.setup_app_registration") as setup:
            code = cmd_auth_setup(
                self._setup_args(
                    print_only=True,
                    client_id="cid",
                    federated_issuer="https://issuer",
                    federated_subject="repo:o/r:ref:refs/heads/main",
                )
            )
        assert code == 0
        setup.assert_not_called()
        out = capsys.readouterr().out
        assert "ms-appx-web://Microsoft.AAD.BrokerPlugin/cid" in out
        assert "DeviceManagementApps.ReadWrite.All" in out
        assert "Issuer:   https://issuer" in out
        assert "Subject:  repo:o/r:ref:refs/heads/main" in out
        assert "Audience: api://AzureADTokenExchange" in out

    def test_setup_error_returns_one(self, capsys):
        """Tests that setup failures are reported and return 1."""
        with patch(
            "napt.cli.auth.setup_app_registration",
            side_effect=ConfigError("ambiguous"),
        ):
            assert cmd_auth_setup(self._setup_args()) == 1
        assert "Error: ambiguous" in capsys.readouterr().out
