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
    write_plan_files,
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
    published: dict[str, Any] | None = None,
    rings: dict[str, Any] | None = None,
    install_assigned: str | None = None,
) -> Path:
    """Writes a deployment state file and returns the deployment dir."""
    deployment_dir = tmp_path / "state" / "deployment"
    state = create_default_deployment_state()
    state["published"] = published
    if rings:
        state["rings"] = rings
    if install_assigned:
        state["install_assigned"] = {"version": "prev", "sha256": install_assigned}
    save_deployment_state(state, deployment_state_path(deployment_dir, app_id))
    return deployment_dir


def _published(
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

    def test_nothing_published_plans_nothing(self, tmp_path):
        """Tests that an app with no published release yields no actions."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(tmp_path, published=None)

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == []

    def test_published_release_starts_rollout_in_first_ring(self, tmp_path):
        """Tests that a published release holding no ring starts at ring 0."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(tmp_path, published=_published())

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == [
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

    def test_install_assignment_planned_once(self, tmp_path):
        """Tests that install assignment is planned only when unassigned."""
        recipe = _write_recipe(tmp_path, install_groups=["All Users"])
        state_dir = _write_state(tmp_path, published=_published())

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == [
            {
                "app_id": "test-app",
                "name": "App test-app",
                "summary": (
                    "Point new installs at 1.0.0: assign the install entry "
                    "to All Users (available)."
                ),
                "type": "assign",
                "entry": "install",
                "version": "1.0.0",
                "displaces": None,
                "intent": "available",
                "groups": ["All Users"],
                "sha256": "a" * 64,
            }
        ]

        state_dir = _write_state(
            tmp_path, published=_published(), install_assigned="a" * 64
        )
        assert plan_promotions(recipe, state_dir=state_dir, now=NOW) == []

    def test_no_install_groups_plans_no_install_assignment(self, tmp_path):
        """Tests that NAPT assigns nothing unless groups are configured."""
        recipe = _write_recipe(tmp_path)  # no deployment section at all
        state_dir = _write_state(tmp_path, published=_published())

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert actions == []

    def test_new_release_replans_install_assignment(self, tmp_path):
        """Tests that a new release plans install assignment again."""
        recipe = _write_recipe(tmp_path, install_groups=["All Users"])
        state_dir = _write_state(
            tmp_path,
            published=_published(version="2.0.0", sha256="b" * 64),
            install_assigned="a" * 64,  # previous release's assignment
        )

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert [a["type"] for a in actions] == ["assign"]
        assert actions[0]["sha256"] == "b" * 64
        assert actions[0]["displaces"] == "prev"
        assert ", displacing prev." in actions[0]["summary"]

    def test_baking_release_does_not_advance(self, tmp_path):
        """Tests that a release still baking holds its ring."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            published=_published(),
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

    def test_baked_release_promotes_to_next_ring(self, tmp_path):
        """Tests that an eligible release promotes with the next ring's groups."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            published=_published(),
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
                "app_id": "test-app",
                "name": "App test-app",
                "summary": (
                    "Promote 1.0.0 from pilot to broad; it has held pilot "
                    "since 2026-07-06 (threshold: 2 days)."
                ),
                "type": "promote",
                "entry": "update",
                "version": "1.0.0",
                "displaces": None,
                "from_ring": "pilot",
                "from_ring_entered_at": "2026-07-06T12:00:00+00:00",
                "promote_after_days": 2,
                "ring": "broad",
                "groups": ["sg-broad"],
                "sha256": "a" * 64,
            }
        ]

    def test_final_ring_never_advances(self, tmp_path):
        """Tests that a release at the final ring plans nothing."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            published=_published(),
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
            published=_published(),
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
        """Tests that a newly published release re-enters ring 0."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            published=_published(version="2.0.0", sha256="b" * 64),
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
        assert actions[0]["type"] == "promote"
        assert actions[0]["from_ring"] is None
        assert actions[0]["ring"] == "pilot"
        assert actions[0]["version"] == "2.0.0"

    def test_app_without_update_entry_skips_rings(self, tmp_path):
        """Tests that rings are skipped when there is no update entry."""
        recipe = _write_recipe(tmp_path, rings=_RINGS, install_groups=["All Users"])
        state_dir = _write_state(tmp_path, published=_published(update_id=None))

        actions = plan_promotions(recipe, state_dir=state_dir, now=NOW)

        assert [a["type"] for a in actions] == ["assign"]

    def test_actions_sorted_by_app_id(self, tmp_path):
        """Tests that actions across apps are deterministically ordered."""
        _write_recipe(tmp_path, app_id="zeta-app", rings=_RINGS)
        _write_recipe(tmp_path, app_id="alpha-app", rings=_RINGS)
        _write_state(tmp_path, app_id="zeta-app", published=_published())
        state_dir = _write_state(tmp_path, app_id="alpha-app", published=_published())

        actions = plan_promotions(tmp_path / "recipes", state_dir=state_dir, now=NOW)

        assert [a["app_id"] for a in actions] == ["alpha-app", "zeta-app"]

    def test_corrupted_entered_at_raises(self, tmp_path):
        """Tests that an unparseable ring timestamp raises ConfigError."""
        recipe = _write_recipe(tmp_path, rings=_RINGS)
        state_dir = _write_state(
            tmp_path,
            published=_published(),
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
        state["published"] = _published()
        save_deployment_state(state, deployment_state_path(deployment_dir, "test-app"))

        actions = plan_promotions(recipe, state_dir=None, now=NOW)

        assert len(actions) == 1
        assert actions[0]["type"] == "promote"


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


def _action(app_id: str = "a") -> dict[str, Any]:
    return {
        "app_id": app_id,
        "name": f"App {app_id}",
        "summary": (
            "Start rolling out 1.0: assign the update entry to the "
            "pilot ring (g)."
        ),
        "type": "promote",
        "entry": "update",
        "version": "1.0",
        "displaces": None,
        "from_ring": None,
        "from_ring_entered_at": None,
        "promote_after_days": None,
        "ring": "pilot",
        "groups": ["g"],
        "sha256": "x",
    }


class TestWritePlanFiles:
    """Tests for per-app plan file lifecycle."""

    def test_writes_deterministic_plan(self, tmp_path):
        """Tests that identical actions produce byte-identical plan files."""
        state_dir = tmp_path / "state"
        actions = [_action()]

        assert write_plan_files(actions, state_dir, ["a"]) == [
            plan_path_for(state_dir, "a")
        ]
        first = plan_path_for(state_dir, "a").read_bytes()
        assert write_plan_files(actions, state_dir, ["a"]) == [
            plan_path_for(state_dir, "a")
        ]

        assert plan_path_for(state_dir, "a").read_bytes() == first
        assert json.loads(first.decode("utf-8")) == {
            "schemaVersion": 1,
            "app_id": "a",
            "name": "App a",
            "actions": [
                {
                    key: value
                    for key, value in _action().items()
                    if key not in ("app_id", "name")
                }
            ],
        }

    def test_plan_file_keys_in_reading_order(self, tmp_path):
        """Tests that plan files keep reading order, summary first."""
        state_dir = tmp_path / "state"
        write_plan_files([_action()], state_dir, ["a"])

        text = plan_path_for(state_dir, "a").read_text(encoding="utf-8")

        top_level = ['"schemaVersion"', '"app_id"', '"name"', '"actions"']
        action_keys = [
            '"summary"',
            '"type"',
            '"entry"',
            '"version"',
            '"displaces"',
            '"ring"',
            '"groups"',
            '"sha256"',
        ]
        positions = [text.index(key) for key in top_level + action_keys]
        assert positions == sorted(positions)

    def test_splits_actions_per_app(self, tmp_path):
        """Tests that each app's actions land in that app's plan file."""
        state_dir = tmp_path / "state"
        actions = [_action("a"), _action("b"), _action("a")]

        written = write_plan_files(actions, state_dir, ["a", "b"])

        assert written == [
            plan_path_for(state_dir, "a"),
            plan_path_for(state_dir, "b"),
        ]
        plan_a = json.loads(written[0].read_text(encoding="utf-8"))
        plan_b = json.loads(written[1].read_text(encoding="utf-8"))
        assert len(plan_a["actions"]) == 2
        assert len(plan_b["actions"]) == 1
        assert plan_a["app_id"] == "a"
        assert plan_a["name"] == "App a"
        assert all("app_id" not in a for a in plan_a["actions"])

    def test_no_actions_removes_stale_plan(self, tmp_path):
        """Tests that an app with no work has its stale plan file removed."""
        state_dir = tmp_path / "state"
        write_plan_files([_action("a")], state_dir, ["a"])

        assert write_plan_files([], state_dir, ["a"]) == []

        assert not plan_path_for(state_dir, "a").exists()

    def test_stale_removal_scoped_to_run(self, tmp_path):
        """Tests that apps outside the run keep their plan files."""
        state_dir = tmp_path / "state"
        write_plan_files([_action("a"), _action("b")], state_dir, ["a", "b"])

        # A single-recipe run covering only "a" with no work for it.
        assert write_plan_files([], state_dir, ["a"]) == []

        assert not plan_path_for(state_dir, "a").exists()
        assert plan_path_for(state_dir, "b").exists()

    def test_no_actions_no_file_is_noop(self, tmp_path):
        """Tests that an empty plan with no existing files writes nothing."""
        state_dir = tmp_path / "state"

        assert write_plan_files([], state_dir, ["a"]) == []

        assert not plan_path_for(state_dir, "a").exists()
