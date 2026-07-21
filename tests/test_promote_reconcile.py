"""Tests for napt.promote.reconcile."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from napt.promote.reconcile import reconcile_publications
from napt.state import (
    create_default_deployment_state,
    deployment_state_path,
    load_deployment_state,
    save_deployment_state,
)

TOKEN = "fake-token"
SHA = "b" * 64


def _configs(app_id: str = "test-app", build_types: str = "both") -> dict[str, Any]:
    return {
        app_id: {
            "id": app_id,
            "name": f"App {app_id}",
            "intune": {"build_types": build_types},
        }
    }


def _write_pending(
    deployment_dir: Path,
    app_id: str = "test-app",
    version: str = "2.0.0",
    sha256: str = SHA,
) -> Path:
    state = create_default_deployment_state()
    state["pending"] = {
        "version": version,
        "sha256": sha256,
        "url": "https://vendor.com/app.msi",
    }
    path = deployment_state_path(deployment_dir, app_id)
    save_deployment_state(state, path)
    return path


def _stamped(app_id: str, entry: str, sha256: str, graph_id: str) -> dict[str, Any]:
    return {
        "id": graph_id,
        "displayName": app_id,
        "notes": f"napt/v1 id={app_id} entry={entry} sha256={sha256}",
    }


def _committed(*_args) -> dict[str, Any]:
    return {"committedContentVersion": "1"}


class TestReconcilePublications:
    """Tests for recovering lost publication writebacks."""

    def test_recovers_fully_committed_publication(self, tmp_path):
        """Tests that a pending release with all entries committed in the
        tenant is recorded as published."""
        state_path = _write_pending(tmp_path)
        apps = [
            _stamped("test-app", "install", SHA, "install-1"),
            _stamped("test-app", "update", SHA, "update-1"),
        ]

        with patch(
            "napt.promote.reconcile.get_mobile_app", side_effect=_committed
        ):
            findings = reconcile_publications(TOKEN, _configs(), tmp_path, apps)

        assert [f["kind"] for f in findings] == ["recovered"]
        state = load_deployment_state(state_path)
        assert state["pending"] is None
        assert state["published"] == {
            "version": "2.0.0",
            "sha256": SHA,
            "intune_app_id": "install-1",
            "intune_update_app_id": "update-1",
        }

    def test_app_only_requires_only_install_entry(self, tmp_path):
        """Tests that build_types app_only recovers from the install entry
        alone."""
        state_path = _write_pending(tmp_path)
        apps = [_stamped("test-app", "install", SHA, "install-1")]

        with patch(
            "napt.promote.reconcile.get_mobile_app", side_effect=_committed
        ):
            findings = reconcile_publications(
                TOKEN, _configs(build_types="app_only"), tmp_path, apps
            )

        assert [f["kind"] for f in findings] == ["recovered"]
        state = load_deployment_state(state_path)
        assert state["published"]["intune_app_id"] == "install-1"
        assert state["published"]["intune_update_app_id"] is None

    def test_update_only_requires_only_update_entry(self, tmp_path):
        """Tests that build_types update_only recovers from the update entry
        alone."""
        state_path = _write_pending(tmp_path)
        apps = [_stamped("test-app", "update", SHA, "update-1")]

        with patch(
            "napt.promote.reconcile.get_mobile_app", side_effect=_committed
        ):
            findings = reconcile_publications(
                TOKEN, _configs(build_types="update_only"), tmp_path, apps
            )

        assert [f["kind"] for f in findings] == ["recovered"]
        state = load_deployment_state(state_path)
        assert state["published"]["intune_app_id"] is None
        assert state["published"]["intune_update_app_id"] == "update-1"

    def test_missing_entry_warns_without_recording(self, tmp_path):
        """Tests that a missing required entry reports incomplete and leaves
        state untouched."""
        state_path = _write_pending(tmp_path)
        apps = [_stamped("test-app", "install", SHA, "install-1")]

        with patch(
            "napt.promote.reconcile.get_mobile_app", side_effect=_committed
        ):
            findings = reconcile_publications(TOKEN, _configs(), tmp_path, apps)

        assert [f["kind"] for f in findings] == ["incomplete"]
        assert "no stamped update entry" in findings[0]["detail"]
        state = load_deployment_state(state_path)
        assert state["published"] is None
        assert state["pending"]["sha256"] == SHA

    def test_uncommitted_content_warns_without_recording(self, tmp_path):
        """Tests that an entry with uncommitted content reports incomplete
        and leaves state untouched."""
        state_path = _write_pending(tmp_path)
        apps = [
            _stamped("test-app", "install", SHA, "install-1"),
            _stamped("test-app", "update", SHA, "update-1"),
        ]

        def by_id(_token: str, graph_id: str) -> dict[str, Any]:
            if graph_id == "update-1":
                return {"committedContentVersion": None}
            return {"committedContentVersion": "1"}

        with patch("napt.promote.reconcile.get_mobile_app", side_effect=by_id):
            findings = reconcile_publications(TOKEN, _configs(), tmp_path, apps)

        assert [f["kind"] for f in findings] == ["incomplete"]
        assert "never committed" in findings[0]["detail"]
        state = load_deployment_state(state_path)
        assert state["published"] is None
        assert state["pending"]["sha256"] == SHA

    def test_unpublished_pending_is_silent(self, tmp_path):
        """Tests that a pending release with no stamped entries produces no
        findings and no tenant lookups."""
        _write_pending(tmp_path)
        apps = [_stamped("test-app", "install", "c" * 64, "other-release")]

        with patch("napt.promote.reconcile.get_mobile_app") as get_mock:
            findings = reconcile_publications(TOKEN, _configs(), tmp_path, apps)

        assert findings == []
        get_mock.assert_not_called()

    def test_no_pending_is_silent(self, tmp_path):
        """Tests that an app without a pending release produces no findings."""
        state = create_default_deployment_state()
        state["published"] = {
            "version": "1.0.0",
            "sha256": "a" * 64,
            "intune_app_id": "i",
            "intune_update_app_id": "u",
        }
        save_deployment_state(
            state, deployment_state_path(tmp_path, "test-app")
        )
        apps = [_stamped("test-app", "install", "a" * 64, "install-1")]

        with patch("napt.promote.reconcile.get_mobile_app") as get_mock:
            findings = reconcile_publications(TOKEN, _configs(), tmp_path, apps)

        assert findings == []
        get_mock.assert_not_called()

    def test_missing_state_file_is_silent(self, tmp_path):
        """Tests that an app with no state file produces no findings."""
        findings = reconcile_publications(TOKEN, _configs(), tmp_path, [])

        assert findings == []
