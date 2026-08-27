"""Tests for napt.cli.status."""

from __future__ import annotations

from napt.cli.status import cmd_status
from tests.cli.conftest import _args


class TestCmdStatus:
    """Tests for cmd_status handler."""

    def test_table_lists_apps(self, tmp_path, capsys):
        """Tests that the text table lists each app with its versions."""
        from napt.state.deployment import (
            create_default_deployment_state,
            deployment_state_path,
            save_deployment_state,
        )

        state = create_default_deployment_state()
        state["published"] = {"version": "1.2.3", "sha256": "a"}
        state["rings"] = {
            "pilot": {"version": "1.2.3", "sha256": "a", "entered_at": "x"}
        }
        save_deployment_state(
            state,
            deployment_state_path(tmp_path / "state" / "deployment", "napt-chrome"),
        )

        code = cmd_status(_args(state_dir=tmp_path / "state", format="text"))

        assert code == 0
        out = capsys.readouterr().out
        assert "napt-chrome" in out
        assert "1.2.3" in out
        assert "pilot=1.2.3" in out

    def test_json_format(self, tmp_path, capsys):
        """Tests that JSON output parses and carries the summary."""
        import json as json_module

        from napt.state.deployment import (
            create_default_deployment_state,
            deployment_state_path,
            save_deployment_state,
        )

        state = create_default_deployment_state()
        state["pending"] = {"version": "2.0.0", "sha256": "b", "url": "u"}
        save_deployment_state(
            state,
            deployment_state_path(tmp_path / "state" / "deployment", "app-x"),
        )

        code = cmd_status(_args(state_dir=tmp_path / "state", format="json"))

        assert code == 0
        rows = json_module.loads(capsys.readouterr().out)
        assert rows[0]["app_id"] == "app-x"
        assert rows[0]["pending"] == "2.0.0"

    def test_empty_state_dir_returns_zero(self, tmp_path, capsys):
        """Tests that no state files reports cleanly with exit 0."""
        code = cmd_status(_args(state_dir=tmp_path / "state", format="text"))

        assert code == 0
        assert "No deployment state found" in capsys.readouterr().out
