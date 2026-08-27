"""Tests for napt.cli.promote."""

from __future__ import annotations

from unittest.mock import patch

from napt.cli.promote import cmd_promote_apply, cmd_promote_plan
from napt.exceptions import AuthError, ConfigError
from tests.cli.conftest import _args


class TestCmdPromotePlan:
    """Tests for cmd_promote_plan handler."""

    def test_actions_write_plan_and_return_zero(self, tmp_path, capsys):
        """Tests that planned actions print a summary and report the plan file."""
        actions = [
            {
                "app_id": "test-app",
                "name": "App test-app",
                "summary": (
                    "Start rolling out 1.0.0: assign the update entry to "
                    "the pilot ring (sg-pilot)."
                ),
                "type": "promote",
                "entry": "update",
                "version": "1.0.0",
                "displaces": None,
                "from_ring": None,
                "from_ring_entered_at": None,
                "promote_after_days": None,
                "ring": "pilot",
                "groups": ["sg-pilot"],
                "sha256": "a" * 64,
            }
        ]
        with (
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.plan_promotions", return_value=actions),
            patch(
                "napt.cli.promote.write_plan_files", return_value=["p"]
            ) as write_mock,
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "test-app: Start rolling out 1.0.0" in out
        assert "Plan written" in out
        assert write_mock.call_args.args[0] == actions

    def test_no_actions_returns_zero(self, tmp_path, capsys):
        """Tests that an empty plan reports nothing to promote."""
        with (
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.plan_promotions", return_value=[]),
            patch("napt.cli.promote.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "Nothing to promote" in out

    def test_config_error_returns_one(self, tmp_path, capsys):
        """Tests that ConfigError is caught and returns 1."""
        with (
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.plan_promotions", side_effect=ConfigError("bad")),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 1
        assert "bad" in capsys.readouterr().out


class TestCmdPromoteApply:
    """Tests for cmd_promote_apply handler."""

    def test_applied_actions_print_and_return_zero(self, tmp_path, capsys):
        """Tests that applied and skipped actions are summarized."""
        summary = {
            "applied": [
                {
                    "app_id": "test-app",
                    "summary": (
                        "Start rolling out 1.0.0: assign the update entry "
                        "to the pilot ring (sg-pilot)."
                    ),
                    "type": "promote",
                    "version": "1.0.0",
                    "ring": "pilot",
                    "groups": ["sg-pilot"],
                    "sha256": "a" * 64,
                }
            ],
            "skipped": [
                {
                    "action": {
                        "app_id": "other-app",
                        "summary": (
                            "Point new installs at 1.0.0: assign the "
                            "install entry to All Users (available)."
                        ),
                        "type": "assign",
                        "version": "1.0.0",
                        "intent": "available",
                        "groups": ["All Users"],
                        "sha256": "b" * 64,
                    },
                    "reason": "already applied",
                }
            ],
            "failed": [],
        }
        with patch("napt.cli.promote.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "[OK]" in out
        assert "[SKIP]" in out
        assert "already applied" in out
        assert "Applied 1 action(s), skipped 1." in out

    def test_nothing_to_apply_returns_zero(self, tmp_path, capsys):
        """Tests that an empty summary reports cleanly."""
        summary = {"applied": [], "skipped": [], "failed": []}
        with patch("napt.cli.promote.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 0
        assert "Nothing to apply" in capsys.readouterr().out

    def test_failed_apps_print_and_return_one(self, tmp_path, capsys):
        """Tests that per-app failures are printed and fail the run."""
        summary = {
            "applied": [],
            "skipped": [],
            "failed": [
                {
                    "app_id": "test-app",
                    "error": "unresolvable groups: ghost-group",
                }
            ],
        }
        with patch("napt.cli.promote.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 1
        out = capsys.readouterr().out
        assert "[FAIL] test-app: unresolvable groups: ghost-group" in out
        assert "1 app(s) failed" in out

    def test_auth_error_returns_one(self, tmp_path, capsys):
        """Tests that AuthError is caught and returns 1."""
        with patch("napt.cli.promote.apply_plan", side_effect=AuthError("no creds")):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 1
        assert "Authentication error" in capsys.readouterr().out

    def test_state_error_returns_one(self, tmp_path, capsys):
        """Tests that StateError is caught and returns 1."""
        from napt.exceptions import StateError

        with patch("napt.cli.promote.apply_plan", side_effect=StateError("bad plan")):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 1
        assert "bad plan" in capsys.readouterr().out


class TestDriftOutput:
    """Tests for drift warning presentation."""

    def test_plan_check_drift_prints_findings(self, tmp_path, capsys):
        """Tests that --check-drift findings are printed as warnings."""
        finding = {
            "app_id": "test-app",
            "kind": "missing_assignment",
            "detail": "expected assignment gone",
        }
        with (
            patch("napt.cli.promote.plan_promotions", return_value=[]),
            patch("napt.cli.promote.write_plan_files", return_value=[]),
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.get_access_token", return_value="tok"),
            patch("napt.cli.promote.list_mobile_apps", return_value=[]),
            patch("napt.cli.promote.detect_drift", return_value=[finding]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=True,
                    reconcile=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "DRIFT CHECK" in out
        assert "[WARNING] test-app: expected assignment gone" in out

    def test_apply_prints_drift_from_summary(self, tmp_path, capsys):
        """Tests that apply prints drift findings from the summary."""
        summary = {
            "applied": [],
            "skipped": [],
            "failed": [],
            "drift": [
                {
                    "app_id": "test-app",
                    "kind": "orphaned_release",
                    "detail": "stray app",
                }
            ],
        }
        with patch("napt.cli.promote.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "DRIFT CHECK" in out
        assert "[WARNING] test-app: stray app" in out


class TestReconcileOutput:
    """Tests for publication reconciliation presentation."""

    def test_plan_reconcile_prints_findings(self, tmp_path, capsys):
        """Tests that --reconcile findings are printed with kind markers."""
        findings = [
            {
                "app_id": "test-app",
                "kind": "recovered",
                "detail": "recorded publication of 2.0.0",
            },
            {
                "app_id": "other-app",
                "kind": "incomplete",
                "detail": "partially published - re-run publish to finish",
            },
        ]
        with (
            patch("napt.cli.promote.plan_promotions", return_value=[]),
            patch("napt.cli.promote.write_plan_files", return_value=[]),
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.get_access_token", return_value="tok"),
            patch("napt.cli.promote.list_mobile_apps", return_value=[]),
            patch("napt.cli.promote.reconcile_publications", return_value=findings),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=True,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "PUBLICATION RECONCILIATION" in out
        assert "[OK] test-app: recorded publication of 2.0.0" in out
        assert "[WARNING] other-app:" in out

    def test_plan_reconcile_runs_before_planning(self, tmp_path, capsys):
        """Tests that reconciliation happens before the plan is computed."""
        order: list[str] = []
        with (
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.get_access_token", return_value="tok"),
            patch("napt.cli.promote.list_mobile_apps", return_value=[]),
            patch(
                "napt.cli.promote.reconcile_publications",
                side_effect=lambda *a: order.append("reconcile") or [],
            ),
            patch(
                "napt.cli.promote.plan_promotions",
                side_effect=lambda *a, **k: order.append("plan") or [],
            ),
            patch("napt.cli.promote.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=True,
                )
            )
        assert code == 0
        assert order == ["reconcile", "plan"]

    def test_plan_validation_failure_writes_no_plan(self, tmp_path, capsys):
        """Tests that an unresolvable group fails the authenticated plan
        without writing a plan file."""
        actions = [
            {
                "app_id": "test-app",
                "summary": (
                    "Start rolling out 1.0.0: assign the update entry to "
                    "the pilot ring (ghost-group)."
                ),
                "type": "promote",
                "version": "1.0.0",
                "ring": "pilot",
                "groups": ["ghost-group"],
                "sha256": "a" * 64,
            }
        ]
        with (
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.get_access_token", return_value="tok"),
            patch("napt.cli.promote.list_mobile_apps", return_value=[]),
            patch("napt.cli.promote.detect_drift", return_value=[]),
            patch("napt.cli.promote.plan_promotions", return_value=actions),
            patch(
                "napt.cli.promote.unresolvable_groups",
                return_value=[
                    "No Entra ID group found with displayName 'ghost-group'."
                ],
            ),
            patch("napt.cli.promote.write_plan_files") as write_mock,
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=True,
                    reconcile=False,
                )
            )
        assert code == 1
        out = capsys.readouterr().out
        assert "Plan validation failed" in out
        assert "ghost-group" in out
        write_mock.assert_not_called()

    def test_offline_plan_skips_validation(self, tmp_path, capsys):
        """Tests that a plan without tenant flags never validates groups
        and that an empty plan draws no unvalidated warning."""
        with (
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.plan_promotions", return_value=[]),
            patch("napt.cli.promote.write_plan_files", return_value=[]),
            patch("napt.cli.promote.unresolvable_groups") as validate_mock,
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 0
        validate_mock.assert_not_called()
        assert "not validated" not in capsys.readouterr().out

    def test_offline_plan_with_actions_warns_unvalidated(self, tmp_path, capsys):
        """Tests that an offline plan producing actions warns that its
        groups were not validated."""
        actions = [
            {
                "app_id": "test-app",
                "summary": (
                    "Start rolling out 1.0.0: assign the update entry to "
                    "the pilot ring (sg-pilot)."
                ),
                "type": "promote",
                "version": "1.0.0",
                "ring": "pilot",
                "groups": ["sg-pilot"],
                "sha256": "a" * 64,
            }
        ]
        with (
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.plan_promotions", return_value=actions),
            patch("napt.cli.promote.write_plan_files", return_value=["p"]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "Plan groups not validated against Entra ID" in out

    def test_plan_shares_one_session_for_reconcile_and_drift(self, tmp_path):
        """Tests that --reconcile --check-drift together authenticate and
        list the tenant only once."""
        with (
            patch("napt.cli.promote.load_recipe_configs", return_value={}),
            patch("napt.cli.promote.get_access_token", return_value="tok") as auth_mock,
            patch("napt.cli.promote.list_mobile_apps", return_value=[]) as list_mock,
            patch("napt.cli.promote.reconcile_publications", return_value=[]),
            patch("napt.cli.promote.detect_drift", return_value=[]),
            patch("napt.cli.promote.plan_promotions", return_value=[]),
            patch("napt.cli.promote.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=True,
                    reconcile=True,
                )
            )
        assert code == 0
        assert auth_mock.call_count == 1
        assert list_mock.call_count == 1

    def test_apply_prints_recovered_from_summary(self, tmp_path, capsys):
        """Tests that apply prints reconciliation findings from the summary."""
        summary = {
            "applied": [],
            "skipped": [],
            "failed": [],
            "drift": [],
            "recovered": [
                {
                    "app_id": "test-app",
                    "kind": "recovered",
                    "detail": "recorded publication of 2.0.0",
                }
            ],
        }
        with patch("napt.cli.promote.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "PUBLICATION RECONCILIATION" in out
        assert "[OK] test-app: recorded publication of 2.0.0" in out
