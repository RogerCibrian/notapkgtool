"""Tests for napt.promote.drift."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from napt.promote import detect_drift
from napt.state import (
    create_default_deployment_state,
    deployment_state_path,
    save_deployment_state,
)

TOKEN = "tok"


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


def _config(
    app_id: str = "test-app",
    rings: list[dict[str, Any]] | None = None,
    install_groups: list[str] | None = None,
) -> dict[str, Any]:
    """Builds an effective config via the real loader for realism."""
    from napt.config import load_effective_config

    deployment: dict[str, Any] = {}
    if rings is not None:
        deployment["rings"] = rings
    deployment["install"] = {
        "intent": "available",
        "groups": install_groups or [],
    }

    recipe: dict[str, Any] = {
        "apiVersion": "napt/v1",
        "name": f"App {app_id}",
        "id": app_id,
        "discovery": {
            "strategy": "url_download",
            "url": "https://example.com/app.msi",
        },
        "deployment": deployment,
    }
    path = Path("recipes") / f"{app_id}.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.dump(recipe), encoding="utf-8")
    return load_effective_config(path)


def _write_state(
    tmp_path: Path,
    app_id: str = "test-app",
    **sections: Any,
) -> Path:
    """Writes a deployment state file and returns the deployment dir."""
    deployment_dir = tmp_path / "state" / "deployment"
    state = create_default_deployment_state()
    state.update(sections)
    save_deployment_state(state, deployment_state_path(deployment_dir, app_id))
    return deployment_dir


def _stamped(app_id: str, entry: str, sha256: str, graph_id: str) -> dict[str, Any]:
    return {
        "id": graph_id,
        "displayName": f"{app_id} ({entry})",
        "notes": f"napt/v1 id={app_id} entry={entry} sha256={sha256}",
    }


def _group_target(group: str) -> dict[str, Any]:
    return {
        "@odata.type": "#microsoft.graph.groupAssignmentTarget",
        "groupId": f"gid-{group}",
    }


def _assignment(group: str, intent: str = "required") -> dict[str, Any]:
    return {"id": "a1", "intent": intent, "target": _group_target(group)}


_RINGS = [{"name": "pilot", "groups": ["Pilot Devices"], "promote_after_days": 2}]

_HELD_PILOT = {
    "pilot": {
        "version": "1.0.0",
        "sha256": "a" * 64,
        "entered_at": "2026-07-01T00:00:00+00:00",
    }
}


def _detect(
    tmp_path: Path,
    config: dict[str, Any],
    deployment_dir: Path,
    existing_apps: list[dict[str, Any]],
    assignments: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Runs detect_drift with Graph calls mocked."""
    assignments = assignments or {}
    with (
        patch(
            "napt.promote.drift.resolve_assignment_target",
            side_effect=lambda token, group, cache=None: _group_target(group),
        ),
        patch(
            "napt.promote.drift.get_app_assignments",
            MagicMock(
                side_effect=lambda token, app_id: list(assignments.get(app_id, []))
            ),
        ),
    ):
        return detect_drift(
            TOKEN, {config["id"]: config}, deployment_dir, existing_apps
        )


class TestDetectDrift:
    """Tests for drift finding computation."""

    def test_matching_state_reports_nothing(self, tmp_path):
        """Tests that Intune matching state produces no findings."""
        config = _config(rings=_RINGS)
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            rings=_HELD_PILOT,
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "update", "a" * 64, "update-1")],
            assignments={"update-1": [_assignment("Pilot Devices")]},
        )

        assert findings == []

    def test_missing_assignment_reported(self, tmp_path):
        """Tests that a removed ring assignment is reported."""
        config = _config(rings=_RINGS)
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            rings=_HELD_PILOT,
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "update", "a" * 64, "update-1")],
            assignments={"update-1": []},
        )

        assert [f["kind"] for f in findings] == ["missing_assignment"]
        assert "Pilot Devices" in findings[0]["detail"]

    def test_intent_mismatch_reported(self, tmp_path):
        """Tests that a changed assignment intent is reported."""
        config = _config(rings=_RINGS)
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            rings=_HELD_PILOT,
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "update", "a" * 64, "update-1")],
            assignments={
                "update-1": [_assignment("Pilot Devices", intent="available")]
            },
        )

        assert [f["kind"] for f in findings] == ["intent_mismatch"]

    def test_unexpected_assignment_reported(self, tmp_path):
        """Tests that an admin-made assignment is reported, not corrected."""
        config = _config(rings=_RINGS)
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            rings=_HELD_PILOT,
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "update", "a" * 64, "update-1")],
            assignments={
                "update-1": [
                    _assignment("Pilot Devices"),
                    _assignment("Admin Group"),
                ]
            },
        )

        assert [f["kind"] for f in findings] == ["unexpected_assignment"]
        assert "NAPT has no record" in findings[0]["detail"]
        assert "leaving it alone" in findings[0]["detail"]

    def test_unrecorded_install_assignment_reported(self, tmp_path):
        """Tests that an unrecorded assignment matching the configured
        install target is classified as unrecorded, not unexpected."""
        config = _config(install_groups=["Pilot Devices"])
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            # No install_assigned record: the apply writeback was lost.
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "install", "a" * 64, "install-1")],
            assignments={
                "install-1": [_assignment("Pilot Devices", intent="available")]
            },
        )

        assert [f["kind"] for f in findings] == ["unrecorded_assignment"]
        assert "matches the configured target" in findings[0]["detail"]
        assert "NAPT has no record" in findings[0]["detail"]

    def test_unrecorded_ring_assignment_reported(self, tmp_path):
        """Tests that an unrecorded assignment matching a configured ring
        group is classified as unrecorded."""
        config = _config(rings=_RINGS)
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            # No ring record: the apply writeback was lost.
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "update", "a" * 64, "update-1")],
            assignments={"update-1": [_assignment("Pilot Devices")]},
        )

        assert [f["kind"] for f in findings] == ["unrecorded_assignment"]

    def test_intent_mismatch_with_config_stays_unexpected(self, tmp_path):
        """Tests that an unrecorded assignment whose intent differs from
        the configured target stays unexpected."""
        config = _config(install_groups=["Pilot Devices"])
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "install", "a" * 64, "install-1")],
            assignments={
                # Config says available; this assignment is required.
                "install-1": [_assignment("Pilot Devices", intent="required")]
            },
        )

        assert [f["kind"] for f in findings] == ["unexpected_assignment"]

    def test_missing_app_reported(self, tmp_path):
        """Tests that a state-referenced release missing from Intune reports."""
        config = _config(rings=_RINGS)
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            rings=_HELD_PILOT,
        )

        findings = _detect(tmp_path, config, deployment_dir, [])

        assert [f["kind"] for f in findings] == ["missing_app"]

    def test_orphaned_release_reported(self, tmp_path):
        """Tests that a stamped app unreferenced by state is reported."""
        config = _config(rings=_RINGS)
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "2.0.0", "sha256": "b" * 64},
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [
                _stamped("test-app", "update", "b" * 64, "update-2"),
                _stamped("test-app", "update", "f" * 64, "update-ghost"),
            ],
        )

        assert [f["kind"] for f in findings] == ["orphaned_release"]
        assert "f" * 12 in findings[0]["detail"]

    def test_unknown_recipe_reported(self, tmp_path):
        """Tests that a stamped app without a recipe is reported."""
        config = _config(rings=_RINGS)
        deployment_dir = _write_state(tmp_path)

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("ghost-app", "update", "a" * 64, "update-x")],
        )

        assert [f["kind"] for f in findings] == ["unknown_app"]

    def test_install_assignment_checked(self, tmp_path):
        """Tests that install-entry expectations are checked too."""
        config = _config(install_groups=["All Users"])
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            install_assigned={"version": "1.0.0", "sha256": "a" * 64},
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "install", "a" * 64, "install-1")],
            assignments={"install-1": []},
        )

        assert [f["kind"] for f in findings] == ["missing_assignment"]
        assert "All Users" in findings[0]["detail"]

    def test_removed_ring_expects_nothing(self, tmp_path):
        """Tests that a ring removed from config drops its expectations."""
        config = _config(rings=[])  # all rings removed
        deployment_dir = _write_state(
            tmp_path,
            published={"version": "1.0.0", "sha256": "a" * 64},
            rings=_HELD_PILOT,
        )

        findings = _detect(
            tmp_path,
            config,
            deployment_dir,
            [_stamped("test-app", "update", "a" * 64, "update-1")],
            assignments={"update-1": [_assignment("Pilot Devices")]},
        )

        # The old ring assignment is no longer expected -> unexpected
        assert [f["kind"] for f in findings] == ["unexpected_assignment"]
