"""Tests for napt.cli.status."""

from __future__ import annotations

import json
from pathlib import Path

from napt.cli.common import run_handler
from napt.cli.status import cmd_status
from napt.state.deployment import (
    create_default_deployment_state,
    deployment_state_path,
    save_deployment_state,
)
from tests.cli.conftest import _args

_RECIPE = (
    "apiVersion: napt/v1\nname: App\nid: app-x\n"
    "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n"
)


def _record(state_dir: Path, app_id: str, **sections) -> None:
    """Writes one app's deployment state under state_dir/deployment."""
    state = create_default_deployment_state()
    state.update(sections)
    save_deployment_state(
        state, deployment_state_path(state_dir / "deployment", app_id)
    )


def _status_args(**overrides):
    defaults = {"recipes": Path("recipes"), "state_dir": None, "format": "text"}
    defaults.update(overrides)
    return _args(**defaults)


class TestCmdStatus:
    """Tests for cmd_status handler."""

    def test_table_lists_apps(self, tmp_path, capsys):
        """Tests that the text table lists each app with its versions."""
        _record(
            tmp_path / "state",
            "napt-chrome",
            published={"version": "1.2.3", "sha256": "a"},
            rings={"pilot": {"version": "1.2.3", "sha256": "a", "entered_at": "x"}},
        )

        code = cmd_status(_status_args(state_dir=tmp_path / "state"))

        assert code == 0
        out = capsys.readouterr().out
        assert "napt-chrome" in out
        assert "1.2.3" in out
        assert "pilot=1.2.3" in out

    def test_json_format(self, tmp_path, capsys):
        """Tests that JSON output parses and carries the summary."""
        _record(
            tmp_path / "state",
            "app-x",
            pending={"version": "2.0.0", "sha256": "b", "url": "u"},
        )

        code = cmd_status(_status_args(state_dir=tmp_path / "state", format="json"))

        assert code == 0
        rows = json.loads(capsys.readouterr().out)
        assert rows[0]["app_id"] == "app-x"
        assert rows[0]["pending"] == "2.0.0"

    def test_downgrade_is_flagged_in_both_formats(self, tmp_path, capsys):
        """Tests that a pending version below the published one is called out."""
        _record(
            tmp_path / "state",
            "app-x",
            published={"version": "2.0.0", "sha256": "a"},
            pending={"version": "1.9.0", "sha256": "b", "url": "u"},
        )

        cmd_status(_status_args(state_dir=tmp_path / "state"))
        assert "1.9.0 [DOWNGRADE]" in capsys.readouterr().out

        cmd_status(_status_args(state_dir=tmp_path / "state", format="json"))
        rows = json.loads(capsys.readouterr().out)
        assert rows[0]["pending_is_downgrade"] is True

    def test_upgrade_is_not_flagged(self, tmp_path, capsys):
        """Tests that an ordinary newer pending release carries no flag."""
        _record(
            tmp_path / "state",
            "app-x",
            published={"version": "2.0.0", "sha256": "a"},
            pending={"version": "2.1.0", "sha256": "b", "url": "u"},
        )

        cmd_status(_status_args(state_dir=tmp_path / "state"))

        assert "DOWNGRADE" not in capsys.readouterr().out

    def test_empty_state_dir_returns_zero(self, tmp_path, capsys):
        """Tests that no state files reports cleanly with exit 0."""
        code = cmd_status(_status_args(state_dir=tmp_path / "state"))

        assert code == 0
        assert "No deployment state found" in capsys.readouterr().out

    def test_state_dir_defaults_to_the_configured_directory(
        self, tmp_path, monkeypatch, capsys
    ):
        """Tests that without --state-dir the recipes' directories.state is
        read, the same directory the pipeline wrote to."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "defaults").mkdir()
        (tmp_path / "defaults" / "org.yaml").write_text(
            "directories:\n  state: elsewhere\n", encoding="utf-8"
        )
        (tmp_path / "recipes").mkdir()
        (tmp_path / "recipes" / "app.yaml").write_text(_RECIPE, encoding="utf-8")
        _record(
            tmp_path / "elsewhere",
            "app-x",
            published={"version": "1.2.3", "sha256": "a"},
        )

        code = cmd_status(_status_args())

        assert code == 0
        out = capsys.readouterr().out
        assert "app-x" in out
        assert "1.2.3" in out

    def test_missing_recipes_without_state_dir_is_an_error(
        self, tmp_path, monkeypatch, capsys
    ):
        """Tests that with nothing to read the state directory from, the
        command says so instead of guessing."""
        monkeypatch.chdir(tmp_path)

        code = run_handler(cmd_status, _status_args())

        assert code == 1
        assert "Recipe path not found" in capsys.readouterr().out
