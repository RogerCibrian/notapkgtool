"""Tests for napt.cli.promote."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from napt.cli.common import run_handler
from napt.cli.promote import cmd_promote_apply, cmd_promote_plan
from napt.exceptions import AuthError, ConfigError, StateError
from napt.promote.applier import ApplyResult
from tests.cli.conftest import _args


def _plan_args(tmp_path, **overrides):
    defaults = {
        "recipes": Path("recipes"),
        "state_dir": tmp_path / "state",
        "check_drift": False,
        "reconcile": False,
    }
    defaults.update(overrides)
    return _args(**defaults)


def _apply_args(tmp_path, **overrides):
    defaults = {"recipes": Path("recipes"), "state_dir": tmp_path, "plan_file": None}
    defaults.update(overrides)
    return _args(**defaults)


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
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch("napt.promote.planner.plan_promotions", return_value=actions),
            patch(
                "napt.promote.planner.write_plan_files", return_value=["p"]
            ) as write_mock,
        ):
            code = cmd_promote_plan(_plan_args(tmp_path))
        assert code == 0
        out = capsys.readouterr().out
        assert "test-app: Start rolling out 1.0.0" in out
        assert "Plan written" in out
        assert write_mock.call_args.args[0] == actions

    def test_no_actions_returns_zero(self, tmp_path, capsys):
        """Tests that an empty plan reports nothing to promote."""
        with (
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch("napt.promote.planner.plan_promotions", return_value=[]),
            patch("napt.promote.planner.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(_plan_args(tmp_path))
        assert code == 0
        out = capsys.readouterr().out
        assert "Nothing to promote" in out

    def test_config_error_returns_one(self, tmp_path, capsys):
        """Tests that ConfigError reaches the shared wrapper and returns 1."""
        with (
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch(
                "napt.promote.planner.plan_promotions", side_effect=ConfigError("bad")
            ),
        ):
            code = run_handler(cmd_promote_plan, _plan_args(tmp_path))
        assert code == 1
        assert "bad" in capsys.readouterr().out


class TestCmdPromoteApply:
    """Tests for cmd_promote_apply handler."""

    def test_applied_actions_print_and_return_zero(self, tmp_path, capsys):
        """Tests that applied and skipped actions are summarized."""
        summary = ApplyResult(
            applied=[
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
            skipped=[
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
        )
        with patch("napt.promote.applier.apply_plan", return_value=summary):
            code = cmd_promote_apply(_apply_args(tmp_path))
        assert code == 0
        out = capsys.readouterr().out
        assert "[OK]" in out
        assert "[SKIP]" in out
        assert "already applied" in out
        assert "Applied 1 action(s), skipped 1." in out

    def test_nothing_to_apply_returns_zero(self, tmp_path, capsys):
        """Tests that an empty summary reports cleanly."""
        with patch("napt.promote.applier.apply_plan", return_value=ApplyResult()):
            code = cmd_promote_apply(_apply_args(tmp_path))
        assert code == 0
        assert "Nothing to apply" in capsys.readouterr().out

    def test_configs_are_loaded_once_and_handed_to_apply(self, tmp_path):
        """Tests that apply receives the loaded configs, the state directory
        from the first one, and whether the run covers the whole fleet."""
        configs = {"a": {"id": "a", "directories": {"state": "custom"}}}
        with (
            patch(
                "napt.promote.planner.load_recipe_configs", return_value=configs
            ) as load,
            patch(
                "napt.config.loader.load_effective_config",
                side_effect=AssertionError("loaded a recipe twice"),
            ),
            patch(
                "napt.promote.applier.apply_plan", return_value=ApplyResult()
            ) as apply,
        ):
            cmd_promote_apply(
                _apply_args(tmp_path, state_dir=None, recipes=tmp_path / "a.yaml")
            )
        assert load.call_count == 1
        assert apply.call_args.args[0] is configs
        assert apply.call_args.kwargs["state_dir"] == Path("custom")
        assert apply.call_args.kwargs["report_unknown_apps"] is False

    def test_failed_apps_print_and_return_one(self, tmp_path, capsys):
        """Tests that per-app failures are printed and fail the run."""
        summary = ApplyResult(
            failed=[{"app_id": "test-app", "error": "unresolvable groups: ghost-group"}]
        )
        with patch("napt.promote.applier.apply_plan", return_value=summary):
            code = cmd_promote_apply(_apply_args(tmp_path))
        assert code == 1
        out = capsys.readouterr().out
        assert "[FAIL] test-app: unresolvable groups: ghost-group" in out
        assert "1 app(s) failed" in out

    def test_auth_error_returns_one(self, tmp_path, capsys):
        """Tests that AuthError is reported as such and returns 1."""
        with patch(
            "napt.promote.applier.apply_plan", side_effect=AuthError("no creds")
        ):
            code = run_handler(cmd_promote_apply, _apply_args(tmp_path))
        assert code == 1
        assert "Authentication error" in capsys.readouterr().out

    def test_state_error_returns_one(self, tmp_path, capsys):
        """Tests that StateError is reported and returns 1."""
        with patch(
            "napt.promote.applier.apply_plan", side_effect=StateError("bad plan")
        ):
            code = run_handler(cmd_promote_apply, _apply_args(tmp_path))
        assert code == 1
        assert "bad plan" in capsys.readouterr().out


class TestLoadOnce:
    """Tests that plan loads each recipe and state file once."""

    def test_plan_state_dir_comes_from_the_loaded_configs(self, tmp_path):
        """Tests that the state directory is read from the configs the run
        already holds instead of loading the first recipe again."""
        configs = {"a": {"id": "a", "directories": {"state": "custom"}}}
        with (
            patch("napt.promote.planner.load_recipe_configs", return_value=configs),
            patch(
                "napt.config.loader.load_effective_config",
                side_effect=AssertionError("loaded a recipe twice"),
            ),
            patch(
                "napt.state.deployment.load_deployment_states", return_value={}
            ) as load_states,
            patch("napt.promote.planner.plan_promotions", return_value=[]) as plan,
            patch("napt.promote.planner.write_plan_files", return_value=[]) as write,
        ):
            cmd_promote_plan(_plan_args(tmp_path, state_dir=None))
        assert load_states.call_args.args[0] == Path("custom") / "deployment"
        assert plan.call_args.args[0] is configs
        assert write.call_args.args[1] == Path("custom")


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
            patch("napt.promote.planner.plan_promotions", return_value=[]),
            patch("napt.promote.planner.write_plan_files", return_value=[]),
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch("napt.auth.credentials.get_access_token", return_value="tok"),
            patch("napt.graph.intune.list_mobile_apps", return_value=[]),
            patch("napt.promote.drift.detect_drift", return_value=[finding]),
        ):
            code = cmd_promote_plan(_plan_args(tmp_path, check_drift=True))
        assert code == 0
        out = capsys.readouterr().out
        assert "DRIFT CHECK" in out
        assert "[WARNING] test-app: expected assignment gone" in out

    def test_apply_prints_drift_from_summary(self, tmp_path, capsys):
        """Tests that apply prints drift findings from the summary."""
        summary = ApplyResult(
            drift=[
                {
                    "app_id": "test-app",
                    "kind": "orphaned_release",
                    "detail": "stray app",
                }
            ]
        )
        with patch("napt.promote.applier.apply_plan", return_value=summary):
            code = cmd_promote_apply(_apply_args(tmp_path))
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
            patch("napt.promote.planner.plan_promotions", return_value=[]),
            patch("napt.promote.planner.write_plan_files", return_value=[]),
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch("napt.auth.credentials.get_access_token", return_value="tok"),
            patch("napt.graph.intune.list_mobile_apps", return_value=[]),
            patch(
                "napt.promote.reconcile.reconcile_publications", return_value=findings
            ),
        ):
            code = cmd_promote_plan(_plan_args(tmp_path, reconcile=True))
        assert code == 0
        out = capsys.readouterr().out
        assert "PUBLICATION RECONCILIATION" in out
        assert "[OK] test-app: recorded publication of 2.0.0" in out
        assert "[WARNING] other-app:" in out

    def test_plan_reconcile_runs_before_planning(self, tmp_path, capsys):
        """Tests that reconciliation happens before the plan is computed."""
        order: list[str] = []
        with (
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch("napt.auth.credentials.get_access_token", return_value="tok"),
            patch("napt.graph.intune.list_mobile_apps", return_value=[]),
            patch(
                "napt.promote.reconcile.reconcile_publications",
                side_effect=lambda *a: order.append("reconcile") or [],
            ),
            patch(
                "napt.promote.planner.plan_promotions",
                side_effect=lambda *a, **k: order.append("plan") or [],
            ),
            patch("napt.promote.planner.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(_plan_args(tmp_path, reconcile=True))
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
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch("napt.auth.credentials.get_access_token", return_value="tok"),
            patch("napt.graph.intune.list_mobile_apps", return_value=[]),
            patch("napt.promote.drift.detect_drift", return_value=[]),
            patch("napt.promote.planner.plan_promotions", return_value=actions),
            patch(
                "napt.promote.preflight.unresolvable_groups",
                return_value=[
                    "No Entra ID group found with displayName 'ghost-group'."
                ],
            ),
            patch("napt.promote.planner.write_plan_files") as write_mock,
        ):
            code = run_handler(cmd_promote_plan, _plan_args(tmp_path, check_drift=True))
        assert code == 1
        out = capsys.readouterr().out
        assert "Plan validation failed" in out
        assert "ghost-group" in out
        write_mock.assert_not_called()

    def test_offline_plan_skips_validation(self, tmp_path, capsys):
        """Tests that a plan without tenant flags never validates groups
        and that an empty plan draws no unvalidated warning."""
        with (
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch("napt.promote.planner.plan_promotions", return_value=[]),
            patch("napt.promote.planner.write_plan_files", return_value=[]),
            patch("napt.promote.preflight.unresolvable_groups") as validate_mock,
        ):
            code = cmd_promote_plan(_plan_args(tmp_path))
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
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch("napt.promote.planner.plan_promotions", return_value=actions),
            patch("napt.promote.planner.write_plan_files", return_value=["p"]),
        ):
            code = cmd_promote_plan(_plan_args(tmp_path))
        assert code == 0
        out = capsys.readouterr().out
        assert "Plan groups not validated against Entra ID" in out

    def test_plan_shares_one_session_for_reconcile_and_drift(self, tmp_path):
        """Tests that --reconcile --check-drift together authenticate and
        list the tenant only once."""
        with (
            patch("napt.promote.planner.load_recipe_configs", return_value={}),
            patch(
                "napt.auth.credentials.get_access_token", return_value="tok"
            ) as auth_mock,
            patch("napt.graph.intune.list_mobile_apps", return_value=[]) as list_mock,
            patch("napt.promote.reconcile.reconcile_publications", return_value=[]),
            patch("napt.promote.drift.detect_drift", return_value=[]),
            patch("napt.promote.planner.plan_promotions", return_value=[]),
            patch("napt.promote.planner.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(
                _plan_args(tmp_path, check_drift=True, reconcile=True)
            )
        assert code == 0
        assert auth_mock.call_count == 1
        assert list_mock.call_count == 1

    def test_apply_prints_recovered_from_summary(self, tmp_path, capsys):
        """Tests that apply prints reconciliation findings from the summary."""
        summary = ApplyResult(
            recovered=[
                {
                    "app_id": "test-app",
                    "kind": "recovered",
                    "detail": "recorded publication of 2.0.0",
                }
            ]
        )
        with patch("napt.promote.applier.apply_plan", return_value=summary):
            code = cmd_promote_apply(_apply_args(tmp_path))
        assert code == 0
        out = capsys.readouterr().out
        assert "PUBLICATION RECONCILIATION" in out
        assert "[OK] test-app: recorded publication of 2.0.0" in out
