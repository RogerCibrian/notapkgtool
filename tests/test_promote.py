"""Tests for napt.promote.planner."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from napt.exceptions import ConfigError, StateError
from napt.promote import (
    plan_path_for,
    plan_promotions,
    resolve_state_dir,
    write_plan_file,
)
from napt.state import (
    create_default_deployment_state,
    deployment_state_path,
    save_deployment_state,
)

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_project(tmp_path, monkeypatch):
    """Makes each test a self-contained NAPT project.

    pytest's basetemp lives inside the repo (.pytest-tmp), so the config
    loader's upward walk from a test recipe would otherwise find the
    repo's own defaults/org.yaml (which configures real deployment
    rings). A minimal org.yaml in tmp_path stops the walk there.
    """
    monkeypatch.chdir(tmp_path)
    org = tmp_path / "defaults" / "org.yaml"
    org.parent.mkdir(parents=True, exist_ok=True)
    org.write_text("apiVersion: napt/v1\n", encoding="utf-8")


_RINGS = [
    {"name": "pilot", "groups": ["sg-pilot"], "promote_after_days": 2},
    {"name": "broad", "groups": ["sg-broad"], "promote_after_days": 5},
    {"name": "production", "groups": ["sg-prod"]},
]


def _write_recipe(
    tmp_path: Path,
    app_id: str = "test-app",
    rings: list[dict[str, Any]] | None = None,
    install_groups: list[str] | None = None,
) -> Path:
    """Writes a minimal recipe with a deployment section."""
    deployment: dict[str, Any] = {}
    if rings is not None:
        deployment["rings"] = rings
    if install_groups is not None:
        deployment["install"] = {"intent": "available", "groups": install_groups}

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
    deployed: dict[str, Any] | None = None,
    rings: dict[str, Any] | None = None,
    install_assigned: bool = False,
) -> Path:
    """Writes a deployment state file and returns the deployment dir."""
    deployment_dir = tmp_path / "state" / "deployment"
    state = create_default_deployment_state()
    state["deployed"] = deployed
    if rings:
        state["rings"] = rings
    if install_assigned:
        state["install_assigned"] = True
    save_deployment_state(state, deployment_state_path(deployment_dir, app_id))
    return deployment_dir


def _deployed(
    version: str = "1.0.0",
    sha256: str = "a" * 64,
    update_id: str | None = "update-1",
    install_id: str | None = "install-1",
) -> dict[str, Any]:
    return {
        "version": version,
        "sha256": sha256,
        "intune_app_id": install_id,
        "intune_update_app_id": update_id,
    }


class TestPlanPromotions:
    """Tests for promotion action computation."""

    def test_nothing_deployed_plans_nothing(self, tmp_path):
        """Tests that an app with no deployed release yields no actions."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(tmp_path, deployed=None)

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == []

    def test_deployed_release_enters_first_ring(self, tmp_path):
        """Tests that a deployed release holding no ring enters ring 0."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(tmp_path, deployed=_deployed())

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == [
            {
                "type": "enter_ring",
                "app_id": "test-app",
                "version": "1.0.0",
                "sha256": "a" * 64,
                "ring": "pilot",
                "groups": ["sg-pilot"],
            }
        ]

    def test_install_assignment_planned_once(self, tmp_path):
        """Tests that install assignment is planned only when unassigned."""
        recipe = _write_recipe(tmp_path, install_groups=["All Users"])
        state_dir = _write_state(tmp_path, deployed=_deployed())

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == [
            {
                "type": "assign_install",
                "app_id": "test-app",
                "version": "1.0.0",
                "sha256": "a" * 64,
                "intent": "available",
                "groups": ["All Users"],
            }
        ]

        state_dir = _write_state(tmp_path, deployed=_deployed(), install_assigned=True)
        assert plan_promotions(recipe, state_dir=state_dir, now=NOW) == []

    def test_baking_release_does_not_advance(self, tmp_path):
        """Tests that a release still baking holds its ring."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            deployed=_deployed(),
            rings={
                "pilot": {
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "entered_at": "2026-07-07T12:00:00+00:00",  # 1 day < 2
                }
            },
        )

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == []

    def test_baked_release_advances_to_next_ring(self, tmp_path):
        """Tests that an eligible release advances with the next ring's groups."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            deployed=_deployed(),
            rings={
                "pilot": {
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "entered_at": "2026-07-06T12:00:00+00:00",  # exactly 2 days
                }
            },
        )

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == [
            {
                "type": "advance_ring",
                "app_id": "test-app",
                "version": "1.0.0",
                "sha256": "a" * 64,
                "from_ring": "pilot",
                "ring": "broad",
                "groups": ["sg-broad"],
            }
        ]

    def test_final_ring_never_advances(self, tmp_path):
        """Tests that a release at the final ring plans nothing."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            deployed=_deployed(),
            rings={
                "production": {
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "entered_at": "2026-01-01T00:00:00+00:00",
                }
            },
        )

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == []

    def test_ring_without_promote_after_days_holds(self, tmp_path):
        """Tests that a ring with no promote_after_days never auto-advances."""
        rings = [
            {"name": "pilot", "groups": ["sg-pilot"]},  # manual gate
            {"name": "production", "groups": ["sg-prod"]},
        ]
        recipe = _write_recipe(tmp_path, rings=rings)
        state_dir = _write_state(
            tmp_path,
            deployed=_deployed(),
            rings={
                "pilot": {
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "entered_at": "2026-01-01T00:00:00+00:00",
                }
            },
        )

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == []

    def test_new_release_restarts_at_first_ring(self, tmp_path):
        """Tests that a newly deployed release re-enters ring 0."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            deployed=_deployed(version="2.0.0", sha256="b" * 64),
            rings={
                "broad": {
                    "version": "1.0.0",
                    "sha256": "a" * 64,  # old release holds broad
                    "entered_at": "2026-01-01T00:00:00+00:00",
                }
            },
        )

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert len(actions) == 1
        assert actions[0]["type"] == "enter_ring"
        assert actions[0]["ring"] == "pilot"
        assert actions[0]["version"] == "2.0.0"

    def test_app_without_update_entry_skips_rings(self, tmp_path):
        """Tests that rings are skipped when there is no update entry."""
        recipe = _write_recipe(tmp_path, rings=_RINGS, install_groups=["All Users"])
        state_dir = _write_state(tmp_path, deployed=_deployed(update_id=None))

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert [a["type"] for a in actions] == ["assign_install"]

    def test_actions_sorted_by_app_id(self, tmp_path):
        """Tests that actions across apps are deterministically ordered."""
        _write_recipe(tmp_path, app_id="zeta-app", rings=_RINGS)
        _write_recipe(tmp_path, app_id="alpha-app", rings=_RINGS)
        _write_state(tmp_path, app_id="zeta-app", deployed=_deployed())
        state_dir = _write_state(tmp_path, app_id="alpha-app", deployed=_deployed())

        actions = plan_promotions(tmp_path / "recipes", state_dir=state_dir, now=NOW)

        assert [a["app_id"] for a in actions] == ["alpha-app", "zeta-app"]

    def test_corrupted_entered_at_raises(self, tmp_path):
        """Tests that an unparseable ring timestamp raises ConfigError."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            deployed=_deployed(),
            rings={
                "pilot": {
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "entered_at": "not-a-timestamp",
                }
            },
        )

        with pytest.raises(StateError, match="entered_at"):
            plan_promotions(recipe, state_dir=state_dir, now=NOW)

    def test_missing_recipes_path_raises(self, tmp_path):
        """Tests that a nonexistent recipes path raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            plan_promotions(tmp_path / "nope", state_dir=tmp_path, now=NOW)

    def test_omitted_state_dir_uses_recipe_config(self, tmp_path, monkeypatch):
        """Tests that directories.state from config applies without a flag."""
        monkeypatch.chdir(tmp_path)
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        # Point the recipe's directories.state at a custom location
        data = yaml.safe_load(recipe.read_text(encoding="utf-8"))
        data["directories"] = {"state": "customstate"}
        recipe.write_text(yaml.dump(data), encoding="utf-8")

        deployment_dir = tmp_path / "customstate" / "deployment"
        state = create_default_deployment_state()
        state["deployed"] = _deployed()
        save_deployment_state(state, deployment_state_path(deployment_dir, "test-app"))

        actions = plan_promotions(recipe, state_dir=None, now=NOW)

        assert len(actions) == 1
        assert actions[0]["type"] == "enter_ring"


class TestResolveStateDir:
    """Tests for state directory resolution from configuration."""

    def test_resolves_configured_state_dir(self, tmp_path):
        """Tests that directories.state is read from the first recipe."""
        recipe = _write_recipe(tmp_path)
        data = yaml.safe_load(recipe.read_text(encoding="utf-8"))
        data["directories"] = {"state": "customstate"}
        recipe.write_text(yaml.dump(data), encoding="utf-8")

        assert resolve_state_dir(recipe) == Path("customstate")

    def test_default_state_dir(self, tmp_path):
        """Tests that the built-in default resolves to state."""
        recipe = _write_recipe(tmp_path)

        assert resolve_state_dir(recipe) == Path("state")


class TestWritePlanFile:
    """Tests for plan file lifecycle."""

    def test_writes_deterministic_plan(self, tmp_path):
        """Tests that identical actions produce byte-identical plan files."""
        plan_path = plan_path_for(tmp_path / "state")
        actions = [
            {
                "type": "enter_ring",
                "app_id": "a",
                "version": "1.0",
                "sha256": "x",
                "ring": "pilot",
                "groups": ["g"],
            }
        ]

        assert write_plan_file(actions, plan_path) is True
        first = plan_path.read_bytes()
        assert write_plan_file(actions, plan_path) is True

        assert plan_path.read_bytes() == first
        assert json.loads(first.decode("utf-8")) == {"actions": actions}

    def test_no_actions_removes_stale_plan(self, tmp_path):
        """Tests that an empty plan removes an existing plan file."""
        plan_path = plan_path_for(tmp_path / "state")
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text('{"actions": []}', encoding="utf-8")

        assert write_plan_file([], plan_path) is False

        assert not plan_path.exists()

    def test_no_actions_no_file_is_noop(self, tmp_path):
        """Tests that an empty plan with no existing file writes nothing."""
        plan_path = plan_path_for(tmp_path / "state")

        assert write_plan_file([], plan_path) is False

        assert not plan_path.exists()
