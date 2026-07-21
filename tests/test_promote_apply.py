"""Tests for napt.promote.applier."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from napt.exceptions import NetworkError, StateError
from napt.promote import apply_plan, load_plan_file, plan_path_for
from napt.state import (
    create_default_deployment_state,
    deployment_state_path,
    load_deployment_state,
    save_deployment_state,
)
from napt.upload.graph import VIRTUAL_TARGETS

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)

_RINGS = [
    {"name": "pilot", "groups": ["Pilot Devices"], "promote_after_days": 2},
    {"name": "broad", "groups": ["Broad Devices"], "promote_after_days": 5},
]


@pytest.fixture(autouse=True)
def _isolate_project(tmp_path, monkeypatch):
    """Makes each test a self-contained NAPT project.

    pytest's basetemp lives inside the repo (.pytest-tmp), so the config
    loader's upward walk from a test recipe would otherwise find the
    repo's own defaults/org.yaml. A minimal org.yaml in tmp_path stops
    the walk there.
    """
    monkeypatch.chdir(tmp_path)
    org = tmp_path / "defaults" / "org.yaml"
    org.parent.mkdir(parents=True, exist_ok=True)
    org.write_text("apiVersion: napt/v1\n", encoding="utf-8")


def _write_recipe(
    tmp_path: Path,
    app_id: str = "test-app",
    rings: list[dict[str, Any]] | None = None,
    install_groups: list[str] | None = None,
    retain_versions: int | None = None,
) -> Path:
    """Writes a minimal recipe with a deployment section."""
    deployment: dict[str, Any] = {}
    if rings is not None:
        deployment["rings"] = rings
    if install_groups is not None:
        deployment["install"] = {"intent": "available", "groups": install_groups}
    if retain_versions is not None:
        deployment["retain_versions"] = retain_versions

    recipe: dict[str, Any] = {
        "apiVersion": "napt/v1",
        "name": f"App {app_id}",
        "id": app_id,
        "discovery": {
            "strategy": "url_download",
            "url": "https://example.com/app.msi",
        },
    }
    if deployment:
        recipe["deployment"] = deployment

    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir(exist_ok=True)
    path = recipes_dir / f"{app_id}.yaml"
    path.write_text(yaml.dump(recipe), encoding="utf-8")
    return path


def _write_state(
    tmp_path: Path,
    app_id: str = "test-app",
    published: dict[str, Any] | None = None,
    rings: dict[str, Any] | None = None,
    retained: list[dict[str, Any]] | None = None,
    install_assigned: str | None = None,
) -> Path:
    """Writes a deployment state file and returns its path."""
    state = create_default_deployment_state()
    state["published"] = published
    if rings:
        state["rings"] = rings
    if retained:
        state["retained"] = retained
    if install_assigned:
        state["install_assigned"] = {"version": "prev", "sha256": install_assigned}
    path = deployment_state_path(tmp_path / "state" / "deployment", app_id)
    save_deployment_state(state, path)
    return path


def _published(version: str = "2.0.0", sha256: str = "b" * 64) -> dict[str, Any]:
    return {
        "version": version,
        "sha256": sha256,
        "intune_app_id": "install-new",
        "intune_update_app_id": "update-new",
    }


def _stamped(app_id: str, entry: str, sha256: str, graph_id: str) -> dict[str, Any]:
    return {
        "id": graph_id,
        "displayName": app_id,
        "notes": f"napt/v1 id={app_id} entry={entry} sha256={sha256}",
    }


def _tenant(sha_new: str = "b" * 64, sha_old: str = "a" * 64) -> list[dict[str, Any]]:
    """Returns a fake tenant with stamped apps for two releases."""
    return [
        _stamped("test-app", "install", sha_new, "install-new"),
        _stamped("test-app", "update", sha_new, "update-new"),
        _stamped("test-app", "install", sha_old, "install-old"),
        _stamped("test-app", "update", sha_old, "update-old"),
        {"id": "foreign", "displayName": "Hand-made", "notes": "by an admin"},
    ]


def _fake_resolve_target(
    token: str, group: str, cache: dict | None = None
) -> dict[str, Any]:
    """Mirrors resolve_assignment_target without Graph calls."""
    if group in VIRTUAL_TARGETS:
        return dict(VIRTUAL_TARGETS[group])
    return {
        "@odata.type": "#microsoft.graph.groupAssignmentTarget",
        "groupId": f"gid-{group}",
    }


def _run_apply(
    tmp_path: Path,
    existing_apps: list[dict[str, Any]] | None = None,
    assignments: dict[str, list[dict[str, Any]]] | None = None,
    assign_side_effect: Any = None,
    drift_findings: list[dict[str, Any]] | None = None,
    resolve_side_effect: Any = None,
) -> tuple[dict[str, Any], dict[str, MagicMock]]:
    """Runs apply_plan with all Graph calls mocked.

    Args:
        tmp_path: Test project directory.
        existing_apps: list_mobile_apps return value.
        assignments: Map of app graph ID to current assignment list
            (default empty for every app).
        assign_side_effect: Optional side effect for assign_app.
        drift_findings: detect_drift return value.
        resolve_side_effect: Overrides the group resolution fake (shared
            by the preflight and the action loop).

    Returns:
        A tuple of (summary, mocks).

    """
    assignments = assignments or {}
    mocks = {
        "assign_app": MagicMock(side_effect=assign_side_effect),
        "delete_mobile_app": MagicMock(),
        "get_app_assignments": MagicMock(
            side_effect=lambda token, app_id: list(assignments.get(app_id, []))
        ),
        "resolve_assignment_target": MagicMock(
            side_effect=resolve_side_effect or _fake_resolve_target
        ),
    }

    with ExitStack() as stack:
        stack.enter_context(
            patch("napt.promote.applier.get_access_token", return_value="tok")
        )
        stack.enter_context(
            patch(
                "napt.promote.applier.list_mobile_apps",
                return_value=existing_apps if existing_apps is not None else [],
            )
        )
        for name, mock in mocks.items():
            stack.enter_context(patch(f"napt.promote.applier.{name}", mock))
        # The apply preflight resolves groups through its own module.
        stack.enter_context(
            patch(
                "napt.promote.preflight.resolve_assignment_target",
                mocks["resolve_assignment_target"],
            )
        )
        stack.enter_context(
            patch(
                "napt.promote.applier.detect_drift",
                return_value=drift_findings or [],
            )
        )
        # Reconciliation's committed-content lookups; only reached when a
        # test seeds a pending release with stamped tenant entries.
        stack.enter_context(
            patch(
                "napt.promote.reconcile.get_mobile_app",
                return_value={"committedContentVersion": "1"},
            )
        )
        summary = apply_plan(
            tmp_path / "recipes",
            state_dir=tmp_path / "state",
            now=NOW,
        )

    return summary, mocks


def _write_plan(tmp_path: Path, actions: list[dict[str, Any]]) -> Path:
    app_id = actions[0]["app_id"]
    plan_path = plan_path_for(tmp_path / "state", app_id)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "app_id": app_id,
                "name": f"App {app_id}",
                "actions": [
                    {
                        key: value
                        for key, value in action.items()
                        if key not in ("app_id", "name")
                    }
                    for action in actions
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return plan_path


def _promote_action(sha256: str = "b" * 64, version: str = "2.0.0") -> dict[str, Any]:
    return {
        "type": "promote",
        "app_id": "test-app",
        "version": version,
        "sha256": sha256,
        "ring": "pilot",
        "groups": ["Pilot Devices"],
    }


class TestApplyPromoteActions:
    """Tests for promote execution."""

    def test_promote_assigns_and_records(self, tmp_path):
        """Tests that promoting into a ring assigns groups and writes state."""
        _write_recipe(tmp_path, rings=_RINGS)
        state_path = _write_state(tmp_path, published=_published())
        plan_path = _write_plan(tmp_path, [_promote_action()])

        summary, mocks = _run_apply(tmp_path, existing_apps=_tenant())

        assert len(summary["applied"]) == 1
        assert summary["skipped"] == []
        # Assigned the ring group (required) to the new update app
        call = mocks["assign_app"].call_args
        assert call.args[1] == "update-new"
        assert call.args[2] == [
            {
                "@odata.type": "#microsoft.graph.mobileAppAssignment",
                "intent": "required",
                "target": {
                    "@odata.type": "#microsoft.graph.groupAssignmentTarget",
                    "groupId": "gid-Pilot Devices",
                },
            }
        ]
        # State records the ring with the apply timestamp
        state = load_deployment_state(state_path)
        assert state["rings"]["pilot"] == {
            "version": "2.0.0",
            "sha256": "b" * 64,
            "entered_at": NOW.isoformat(),
        }
        # Plan file consumed
        assert not plan_path.exists()

    def test_preserves_foreign_assignments(self, tmp_path):
        """Tests that admin-made assignments survive the assign call."""
        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(tmp_path, published=_published())
        _write_plan(tmp_path, [_promote_action()])
        admin_assignment = {
            "id": "existing-1",
            "intent": "available",
            "target": {"@odata.type": "#microsoft.graph.allDevicesAssignmentTarget"},
        }

        _, mocks = _run_apply(
            tmp_path,
            existing_apps=_tenant(),
            assignments={"update-new": [admin_assignment]},
        )

        sent = mocks["assign_app"].call_args.args[2]
        assert {
            "@odata.type": "#microsoft.graph.mobileAppAssignment",
            "intent": "available",
            "target": {"@odata.type": "#microsoft.graph.allDevicesAssignmentTarget"},
        } in sent
        assert all("id" not in a for a in sent)

    def test_displacement_unassigns_previous_release(self, tmp_path):
        """Tests that the displaced release loses the ring's groups."""
        _write_recipe(tmp_path, rings=_RINGS)
        state_path = _write_state(
            tmp_path,
            published=_published(),
            rings={
                "pilot": {
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "entered_at": "2026-07-01T00:00:00+00:00",
                }
            },
        )
        _write_plan(tmp_path, [_promote_action()])
        old_assignment = {
            "id": "x",
            "intent": "required",
            "target": {
                "@odata.type": "#microsoft.graph.groupAssignmentTarget",
                "groupId": "gid-Pilot Devices",
            },
        }

        summary, mocks = _run_apply(
            tmp_path,
            existing_apps=_tenant(),
            assignments={"update-old": [old_assignment]},
        )

        assert len(summary["applied"]) == 1
        # Second assign call strips the pilot group from the old app
        targets = [c.args[1] for c in mocks["assign_app"].call_args_list]
        assert targets == ["update-new", "update-old"]
        assert mocks["assign_app"].call_args_list[1].args[2] == []
        # Old release holds nothing and moves to retained
        state = load_deployment_state(state_path)
        assert state["retained"] == [{"version": "1.0.0", "sha256": "a" * 64}]
        mocks["delete_mobile_app"].assert_not_called()

    def test_retention_deletes_beyond_limit(self, tmp_path):
        """Tests that displaced releases beyond retain_versions are deleted."""
        _write_recipe(tmp_path, rings=_RINGS, retain_versions=1)
        _write_state(
            tmp_path,
            published=_published(),
            rings={
                "pilot": {
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "entered_at": "2026-07-01T00:00:00+00:00",
                }
            },
            retained=[{"version": "0.9.0", "sha256": "9" * 64}],
        )
        _write_plan(tmp_path, [_promote_action()])
        tenant = _tenant() + [
            _stamped("test-app", "install", "9" * 64, "install-ancient"),
            _stamped("test-app", "update", "9" * 64, "update-ancient"),
        ]

        summary, mocks = _run_apply(tmp_path, existing_apps=tenant)

        assert len(summary["applied"]) == 1
        deleted = [c.args[1] for c in mocks["delete_mobile_app"].call_args_list]
        assert deleted == ["install-ancient", "update-ancient"]

    def test_stale_action_skipped(self, tmp_path):
        """Tests that an action for a superseded release is skipped."""
        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(tmp_path, published=_published(version="3.0.0", sha256="c" * 64))
        _write_plan(tmp_path, [_promote_action()])  # plans v2, published v3

        summary, mocks = _run_apply(tmp_path, existing_apps=_tenant())

        assert summary["applied"] == []
        assert len(summary["skipped"]) == 1
        assert "stale" in summary["skipped"][0]["reason"]
        mocks["assign_app"].assert_not_called()

    def test_already_applied_skipped(self, tmp_path):
        """Tests that an already-held ring skips idempotently."""
        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(
            tmp_path,
            published=_published(),
            rings={
                "pilot": {
                    "version": "2.0.0",
                    "sha256": "b" * 64,
                    "entered_at": "2026-07-01T00:00:00+00:00",
                }
            },
        )
        _write_plan(tmp_path, [_promote_action()])

        summary, mocks = _run_apply(tmp_path, existing_apps=_tenant())

        assert summary["applied"] == []
        assert summary["skipped"][0]["reason"] == "already applied"
        mocks["assign_app"].assert_not_called()

    def test_missing_update_app_skipped(self, tmp_path):
        """Tests that a release without a stamped update entry is skipped."""
        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(tmp_path, published=_published())
        _write_plan(tmp_path, [_promote_action()])

        summary, mocks = _run_apply(tmp_path, existing_apps=[])

        assert summary["applied"] == []
        assert "no stamped update entry" in summary["skipped"][0]["reason"]
        mocks["assign_app"].assert_not_called()

    def test_failure_keeps_plan_file(self, tmp_path):
        """Tests that a Graph failure fails the app and keeps its plan file."""
        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(tmp_path, published=_published())
        plan_path = _write_plan(tmp_path, [_promote_action()])

        summary, _ = _run_apply(
            tmp_path,
            existing_apps=_tenant(),
            assign_side_effect=NetworkError("Graph down"),
        )

        assert plan_path.exists()
        assert [f["app_id"] for f in summary["failed"]] == ["test-app"]
        assert "Graph down" in summary["failed"][0]["error"]


class TestApplyAssignActions:
    """Tests for assign execution."""

    def _assign_action(self, sha256: str = "b" * 64) -> dict[str, Any]:
        return {
            "type": "assign",
            "app_id": "test-app",
            "version": "2.0.0",
            "sha256": sha256,
            "intent": "available",
            "groups": ["All Users"],
        }

    def test_assigns_and_records_release(self, tmp_path):
        """Tests that the install entry is assigned and recorded by sha."""
        _write_recipe(tmp_path, install_groups=["All Users"])
        state_path = _write_state(tmp_path, published=_published())
        _write_plan(tmp_path, [self._assign_action()])

        summary, mocks = _run_apply(tmp_path, existing_apps=_tenant())

        assert len(summary["applied"]) == 1
        call = mocks["assign_app"].call_args
        assert call.args[1] == "install-new"
        # "All Users" is Intune's built-in virtual target, not a group
        assert call.args[2] == [
            {
                "@odata.type": "#microsoft.graph.mobileAppAssignment",
                "intent": "available",
                "target": {
                    "@odata.type": (
                        "#microsoft.graph.allLicensedUsersAssignmentTarget"
                    ),
                },
            }
        ]
        state = load_deployment_state(state_path)
        assert state["install_assigned"] == {"version": "2.0.0", "sha256": "b" * 64}

    def test_displaces_previous_install_assignment(self, tmp_path):
        """Tests that the previous release's install entry loses the groups."""
        _write_recipe(tmp_path, install_groups=["All Users"])
        _write_state(tmp_path, published=_published(), install_assigned="a" * 64)
        _write_plan(tmp_path, [self._assign_action()])
        old_assignment = {
            "id": "x",
            "intent": "available",
            "target": {
                "@odata.type": "#microsoft.graph.allLicensedUsersAssignmentTarget",
            },
        }

        summary, mocks = _run_apply(
            tmp_path,
            existing_apps=_tenant(),
            assignments={"install-old": [old_assignment]},
        )

        assert len(summary["applied"]) == 1
        targets = [c.args[1] for c in mocks["assign_app"].call_args_list]
        assert targets == ["install-new", "install-old"]
        assert mocks["assign_app"].call_args_list[1].args[2] == []


class TestApplyOrchestration:
    """Tests for plan sourcing and file lifecycle."""

    def test_bare_apply_plans_fresh(self, tmp_path):
        """Tests that apply without a plan file plans and applies."""
        _write_recipe(tmp_path, rings=_RINGS)
        state_path = _write_state(tmp_path, published=_published())

        summary, mocks = _run_apply(tmp_path, existing_apps=_tenant())

        assert len(summary["applied"]) == 1
        assert mocks["assign_app"].call_count == 1
        state = load_deployment_state(state_path)
        assert state["rings"]["pilot"]["sha256"] == "b" * 64

    def test_nothing_to_apply(self, tmp_path):
        """Tests that no plan and no eligible actions is a clean no-op."""
        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(tmp_path, published=None)

        summary, mocks = _run_apply(tmp_path, existing_apps=[])

        assert summary == {
            "applied": [],
            "skipped": [],
            "failed": [],
            "drift": [],
            "recovered": [],
        }
        mocks["assign_app"].assert_not_called()

    def test_recovers_lost_writeback_and_promotes_same_run(self, tmp_path):
        """Tests that a publication whose writeback was lost is recovered
        and enters the first ring in the same apply run."""
        _write_recipe(tmp_path, rings=_RINGS)
        # State still shows the release as pending: the publish run
        # uploaded successfully but its state commit never landed.
        state = create_default_deployment_state()
        state["pending"] = {
            "version": "2.0.0",
            "sha256": "b" * 64,
            "url": "https://example.com/app.msi",
        }
        state_path = deployment_state_path(
            tmp_path / "state" / "deployment", "test-app"
        )
        save_deployment_state(state, state_path)

        summary, _ = _run_apply(tmp_path, existing_apps=_tenant())

        assert [f["kind"] for f in summary["recovered"]] == ["recovered"]
        assert [a["type"] for a in summary["applied"]] == ["promote"]
        state = load_deployment_state(state_path)
        assert state["pending"] is None
        assert state["published"]["intune_app_id"] == "install-new"
        assert state["rings"]["pilot"]["sha256"] == "b" * 64

    def test_preflight_fails_app_with_zero_mutations(self, tmp_path):
        """Tests that an unresolvable group fails the app with zero mutations."""
        from napt.exceptions import ConfigError

        _write_recipe(tmp_path, rings=_RINGS)
        state_path = _write_state(tmp_path, published=_published())
        plan_path = _write_plan(
            tmp_path,
            [
                _promote_action(),  # resolvable: Pilot Devices
                {
                    "type": "promote",
                    "app_id": "test-app",
                    "version": "2.0.0",
                    "sha256": "b" * 64,
                    "from_ring": "pilot",
                    "ring": "broad",
                    "groups": ["missing-group"],
                },
            ],
        )

        def _resolve(token, group, cache=None):
            if group == "missing-group":
                raise ConfigError(
                    f"No Entra ID group found with displayName '{group}'."
                )
            return _fake_resolve_target(token, group, cache)

        summary, mocks = _run_apply(
            tmp_path,
            existing_apps=_tenant(),
            resolve_side_effect=_resolve,
        )

        assert summary["applied"] == []
        assert [f["app_id"] for f in summary["failed"]] == ["test-app"]
        assert "missing-group" in summary["failed"][0]["error"]
        mocks["assign_app"].assert_not_called()
        state = load_deployment_state(state_path)
        assert state["rings"] == {}  # the resolvable action did not apply
        assert plan_path.exists()  # plan not consumed

    def test_preflight_ignores_dead_group_on_stale_action(self, tmp_path):
        """Tests that an unresolvable group referenced only by a stale
        action is never resolved, preserving resume safety."""
        from napt.exceptions import ConfigError

        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(tmp_path, published=_published())  # published is b*64
        _write_plan(
            tmp_path,
            [
                _promote_action(),  # live: Pilot Devices
                # Stale: sha no longer published; its group was deleted
                # after the action originally applied.
                {
                    "type": "promote",
                    "app_id": "test-app",
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "ring": "pilot",
                    "groups": ["deleted-group"],
                },
            ],
        )

        def _resolve(token, group, cache=None):
            if group == "deleted-group":
                raise ConfigError(
                    f"No Entra ID group found with displayName '{group}'."
                )
            return _fake_resolve_target(token, group, cache)

        summary, _ = _run_apply(
            tmp_path,
            existing_apps=_tenant(),
            resolve_side_effect=_resolve,
        )

        assert [a["type"] for a in summary["applied"]] == ["promote"]
        assert [s["reason"] for s in summary["skipped"]] == [
            "stale action - the published release has changed"
        ]

    def test_failed_app_does_not_block_others(self, tmp_path):
        """Tests that one app's preflight failure does not block another app."""
        from napt.exceptions import ConfigError

        _write_recipe(tmp_path, app_id="app-bad", rings=_RINGS)
        _write_recipe(tmp_path, app_id="app-good", rings=_RINGS)
        _write_state(tmp_path, app_id="app-bad", published=_published())
        good_state = _write_state(tmp_path, app_id="app-good", published=_published())
        bad_action = _promote_action()
        bad_action["app_id"] = "app-bad"
        bad_action["groups"] = ["missing-group"]
        good_action = _promote_action()
        good_action["app_id"] = "app-good"
        bad_plan = _write_plan(tmp_path, [bad_action])
        good_plan = _write_plan(tmp_path, [good_action])
        tenant = [
            _stamped("app-bad", "update", "b" * 64, "update-bad"),
            _stamped("app-good", "update", "b" * 64, "update-good"),
        ]

        def _resolve(token, group, cache=None):
            if group == "missing-group":
                raise ConfigError(
                    f"No Entra ID group found with displayName '{group}'."
                )
            return _fake_resolve_target(token, group, cache)

        summary, _ = _run_apply(
            tmp_path,
            existing_apps=tenant,
            resolve_side_effect=_resolve,
        )

        assert [a["app_id"] for a in summary["applied"]] == ["app-good"]
        assert [f["app_id"] for f in summary["failed"]] == ["app-bad"]
        assert bad_plan.exists()
        assert not good_plan.exists()
        state = load_deployment_state(good_state)
        assert state["rings"]["pilot"]["sha256"] == "b" * 64

    def test_graph_failure_isolated_to_one_app(self, tmp_path):
        """Tests that a Graph failure applying one app spares the others."""
        _write_recipe(tmp_path, app_id="app-bad", rings=_RINGS)
        _write_recipe(tmp_path, app_id="app-good", rings=_RINGS)
        _write_state(tmp_path, app_id="app-bad", published=_published())
        _write_state(tmp_path, app_id="app-good", published=_published())
        bad_action = _promote_action()
        bad_action["app_id"] = "app-bad"
        good_action = _promote_action()
        good_action["app_id"] = "app-good"
        bad_plan = _write_plan(tmp_path, [bad_action])
        good_plan = _write_plan(tmp_path, [good_action])
        tenant = [
            _stamped("app-bad", "update", "b" * 64, "update-bad"),
            _stamped("app-good", "update", "b" * 64, "update-good"),
        ]

        def _assign(token, app_id, assignments):
            if app_id == "update-bad":
                raise NetworkError("Graph down")

        summary, _ = _run_apply(
            tmp_path,
            existing_apps=tenant,
            assign_side_effect=_assign,
        )

        assert [a["app_id"] for a in summary["applied"]] == ["app-good"]
        assert [f["app_id"] for f in summary["failed"]] == ["app-bad"]
        assert bad_plan.exists()
        assert not good_plan.exists()

    def test_unknown_app_in_plan_skipped(self, tmp_path):
        """Tests that a plan action without a matching recipe is skipped."""
        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(tmp_path, published=_published())
        action = _promote_action()
        action["app_id"] = "ghost-app"
        _write_plan(tmp_path, [action])

        summary, _ = _run_apply(tmp_path, existing_apps=_tenant())

        assert summary["applied"] == []
        assert "no recipe" in summary["skipped"][0]["reason"]


class TestLoadPlanFile:
    """Tests for plan file loading."""

    def test_corrupted_plan_raises(self, tmp_path):
        """Tests that invalid plan JSON raises StateError."""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text("not json{{{", encoding="utf-8")

        with pytest.raises(StateError, match="Corrupted plan file"):
            load_plan_file(plan_path)

    def test_missing_actions_key_raises(self, tmp_path):
        """Tests that a plan without an actions list raises StateError."""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text('{"app_id": "test-app"}', encoding="utf-8")

        with pytest.raises(StateError, match="Corrupted plan file"):
            load_plan_file(plan_path)

    def test_missing_app_id_raises(self, tmp_path):
        """Tests that a plan without a declared app id raises StateError."""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            '{"schemaVersion": 1, "actions": []}', encoding="utf-8"
        )

        with pytest.raises(StateError, match="Corrupted plan file"):
            load_plan_file(plan_path)

    def test_foreign_action_app_id_raises(self, tmp_path):
        """Tests that an action referencing another app is rejected."""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "app_id": "test-app",
                    "actions": [
                        _promote_action(),
                        {**_promote_action(), "app_id": "other-app"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(StateError, match="per-app"):
            load_plan_file(plan_path)

    def test_injects_file_level_app_id_and_name(self, tmp_path):
        """Tests that the file's app id and name are injected into actions."""
        plan_path = tmp_path / "plan.json"
        action = {
            key: value
            for key, value in _promote_action().items()
            if key != "app_id"
        }
        plan_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "app_id": "test-app",
                    "name": "App test-app",
                    "actions": [action],
                }
            ),
            encoding="utf-8",
        )

        actions = load_plan_file(plan_path)

        assert actions[0]["app_id"] == "test-app"
        assert actions[0]["name"] == "App test-app"

    def test_unsupported_plan_schema_version_raises(self, tmp_path):
        """Tests that an unsupported plan schema version is rejected."""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            '{"schemaVersion": 99, "app_id": "test-app", "actions": []}',
            encoding="utf-8",
        )

        with pytest.raises(StateError, match="schema version 99"):
            load_plan_file(plan_path)


class TestApplyDrift:
    """Tests for drift reporting in the apply summary."""

    def test_drift_findings_included_in_summary(self, tmp_path):
        """Tests that drift findings pass through to the summary."""
        _write_recipe(tmp_path, rings=_RINGS)
        _write_state(tmp_path, published=_published())
        finding = {"app_id": "test-app", "kind": "missing_assignment", "detail": "x"}

        summary, _ = _run_apply(
            tmp_path, existing_apps=_tenant(), drift_findings=[finding]
        )

        assert summary["drift"] == [finding]
