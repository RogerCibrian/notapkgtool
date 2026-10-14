"""Tests for napt.cli.upstream."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from napt.cli.common import run_handler
from napt.cli.upstream import (
    cmd_upstream_add,
    cmd_upstream_check,
    cmd_upstream_remove,
    cmd_upstream_update,
)
from napt.exceptions import ConfigError
from napt.upstream.add import AddResult, PlannedRecipe
from napt.upstream.refresh import RecipeStatus, RefreshResult
from napt.upstream.remove import RemoveResult
from tests.cli.conftest import _args


def _add_args(**overrides):
    defaults = {
        "url": "https://github.com/org/recipes.git",
        "path": ["recipes/Google/chrome.yaml"],
        "ref": None,
        "dest": None,
        "id": None,
        "exclude": [],
        "dry_run": False,
    }
    defaults.update(overrides)
    return _args(**defaults)


def _planned(**overrides) -> PlannedRecipe:
    defaults = {
        "path": "recipes/Google/chrome.yaml",
        "pinned": "upstream/github.com/org/recipes/recipes/Google/chrome.yaml",
        "override": "recipes/Google/chrome.override.yaml",
        "app_id": "google-chrome",
        "dropped": ("deployment",),
    }
    defaults.update(overrides)
    return PlannedRecipe(**defaults)


class TestCmdUpstreamAdd:
    """Tests for the add handler."""

    def test_passes_arguments_and_prints_each_recipe(self, capsys):
        """Tests that every flag reaches the engine and each recipe is listed."""
        result = AddResult(
            url="https://github.com/org/recipes.git",
            ref="main",
            commit="abc123",
            recipes=(_planned(),),
            skipped=("recipes/Mozilla/firefox.yaml",),
            dry_run=False,
        )
        with patch("napt.upstream.add.add_recipes", return_value=result) as add:
            code = cmd_upstream_add(
                _add_args(ref="v2", dest="apps", id="x", exclude=["Beta/*"])
            )

        assert code == 0
        add.assert_called_once_with(
            Path.cwd(),
            "https://github.com/org/recipes.git",
            ["recipes/Google/chrome.yaml"],
            ref="v2",
            dest="apps",
            app_id="x",
            excludes=["Beta/*"],
            dry_run=False,
        )
        out = capsys.readouterr().out
        assert (
            "[OK] recipes/Google/chrome.yaml -> recipes/Google/chrome.override.yaml "
            "(id google-chrome)"
        ) in out
        assert "UPSTREAM ADD RESULTS" in out
        assert "Commit:" in out and "abc123" in out
        assert "[SKIP] recipes/Mozilla/firefox.yaml (already imported" in out
        assert "Skipped:" in out
        assert "[SUCCESS] Imported 1 recipe(s)" in out

    def test_dry_run_prints_the_plan(self, capsys):
        """Tests that a dry run is labelled and ends with nothing written."""
        result = AddResult(
            url="u",
            ref="main",
            commit="abc",
            recipes=(_planned(),),
            skipped=(),
            dry_run=True,
        )
        with patch("napt.upstream.add.add_recipes", return_value=result):
            cmd_upstream_add(_add_args(dry_run=True))

        out = capsys.readouterr().out
        assert "[PLAN] recipes/Google/chrome.yaml" in out
        assert "DRY RUN" in out and "Nothing written." in out

    def test_nothing_new_is_reported(self, capsys):
        """Tests that a re-run with only skips ends with nothing to import."""
        result = AddResult(
            url="u",
            ref="main",
            commit="abc",
            recipes=(),
            skipped=("a.yaml",),
            dry_run=False,
        )
        with patch("napt.upstream.add.add_recipes", return_value=result):
            cmd_upstream_add(_add_args())

        out = capsys.readouterr().out
        assert "Nothing new to import." in out
        assert "Skipped:" in out

    def test_errors_are_reported_by_run_handler(self, capsys):
        """Tests that a ConfigError becomes an error line and exit 1."""
        with patch("napt.upstream.add.add_recipes", side_effect=ConfigError("nope")):
            code = run_handler(cmd_upstream_add, _add_args())

        assert code == 1
        assert "Error: nope" in capsys.readouterr().out


class TestCmdUpstreamRemove:
    """Tests for the remove handler."""

    def test_prints_what_was_removed(self, capsys):
        """Tests that the override state and repository entry are shown."""
        result = RemoveResult(
            path="upstream/github.com/org/recipes/recipes/Google/chrome.yaml",
            override="recipes/Google/chrome.override.yaml",
            override_deleted=False,
            repo_removed=True,
        )
        with patch("napt.upstream.remove.remove_recipe", return_value=result) as rm:
            code = cmd_upstream_remove(
                _args(
                    path=Path("recipes/Google/chrome.override.yaml"),
                    delete_override=False,
                )
            )

        assert code == 0
        rm.assert_called_once_with(
            Path.cwd(),
            Path("recipes/Google/chrome.override.yaml"),
            delete_override=False,
        )
        out = capsys.readouterr().out
        assert "Override State:" in out and "kept" in out
        assert "Repository Entry:" in out and "removed" in out

    def test_missing_override_row_is_left_out(self, capsys):
        """Tests that None rows are skipped when the override was already gone."""
        result = RemoveResult(
            path="upstream/x/y/recipes/a.yaml",
            override=None,
            override_deleted=False,
            repo_removed=False,
        )
        with patch("napt.upstream.remove.remove_recipe", return_value=result):
            cmd_upstream_remove(_args(path=Path("upstream/x"), delete_override=True))

        out = capsys.readouterr().out
        assert "Override:" not in out
        assert "Override State:" not in out


def _status(**overrides) -> RecipeStatus:
    defaults = {
        "url": "https://github.com/org/recipes.git",
        "path": "recipes/Google/chrome.yaml",
        "override": "recipes/Google/chrome.override.yaml",
        "status": "changed",
        "old_commit": "aaa",
        "new_commit": "bbb",
        "old_blob": "111",
        "new_blob": "222",
    }
    defaults.update(overrides)
    return RecipeStatus(**defaults)


class TestCmdUpstreamCheck:
    """Tests for the check handler."""

    def test_prints_statuses_and_exits_zero_by_default(self, capsys):
        """Tests that drift is listed and the exit code stays 0 without --exit-code."""
        result = RefreshResult(
            recipes=(_status(), _status(path="recipes/x.yaml", status="unchanged")),
            wrote=False,
        )
        with patch("napt.upstream.refresh.refresh", return_value=result) as run:
            code = cmd_upstream_check(_args(path=[], format="text", exit_code=False))

        assert code == 0
        run.assert_called_once_with(Path.cwd(), write=False, paths=[], quiet=False)
        out = capsys.readouterr().out
        assert (
            "[CHANGED] recipes/Google/chrome.yaml -> "
            "recipes/Google/chrome.override.yaml" in out
        )
        assert "[UNCHANGED] recipes/x.yaml" in out
        assert "Changed:" in out and "1 recipe(s) differ upstream." in out

    def test_exit_code_flag_fails_on_drift(self):
        """Tests that --exit-code returns 1 on changed or missing, 0 otherwise."""
        drifted = RefreshResult(recipes=(_status(status="missing"),), wrote=False)
        clean = RefreshResult(recipes=(_status(status="unchanged"),), wrote=False)
        with patch("napt.upstream.refresh.refresh", return_value=drifted):
            assert (
                cmd_upstream_check(_args(path=[], format="text", exit_code=True)) == 1
            )
        with patch("napt.upstream.refresh.refresh", return_value=clean):
            assert (
                cmd_upstream_check(_args(path=[], format="text", exit_code=True)) == 0
            )

    def test_modified_locally_is_not_a_failure_for_check(self, capsys):
        """Tests that check reports a hand-edited copy without a [FAIL] block."""
        result = RefreshResult(
            recipes=(_status(status="modified-locally"),), wrote=False
        )
        with patch("napt.upstream.refresh.refresh", return_value=result):
            code = cmd_upstream_check(_args(path=[], format="text", exit_code=True))

        assert code == 0
        out = capsys.readouterr().out
        assert "[MODIFIED-LOCALLY] recipes/Google/chrome.yaml" in out
        assert "[FAIL]" not in out and "[SUCCESS]" in out
        assert "--force" not in out

    def test_json_output_carries_every_field(self, capsys):
        """Tests that --format json emits one object per recipe with the pins."""
        result = RefreshResult(recipes=(_status(),), wrote=False)
        with patch("napt.upstream.refresh.refresh", return_value=result):
            cmd_upstream_check(_args(path=[], format="json", exit_code=False))

        data = json.loads(capsys.readouterr().out)
        assert data[0]["status"] == "changed"
        assert data[0]["old_commit"] == "aaa" and data[0]["new_commit"] == "bbb"
        assert data[0]["override"] == "recipes/Google/chrome.override.yaml"


class TestCmdUpstreamUpdate:
    """Tests for the update handler."""

    def test_reports_rewrites_and_passes_paths_and_force(self, capsys):
        """Tests that update prints what it rewrote and forwards its flags."""
        result = RefreshResult(recipes=(_status(updated=True),), wrote=True)
        with patch("napt.upstream.refresh.refresh", return_value=result) as run:
            code = cmd_upstream_update(
                _args(path=[Path("recipes/a.override.yaml")], format="text", force=True)
            )

        assert code == 0
        run.assert_called_once_with(
            Path.cwd(),
            write=True,
            paths=[Path("recipes/a.override.yaml")],
            force=True,
            quiet=False,
        )
        out = capsys.readouterr().out
        assert "[CHANGED] recipes/Google/chrome.yaml" in out and "(updated)" in out
        assert "Rewrote 1 pinned copy." in out

    def test_refused_local_edit_exits_one(self, capsys):
        """Tests that a left-alone modified copy fails the run with the fix named."""
        result = RefreshResult(
            recipes=(_status(status="modified-locally"),), wrote=True
        )
        with patch("napt.upstream.refresh.refresh", return_value=result):
            code = cmd_upstream_update(_args(path=[], format="text", force=False))

        assert code == 1
        out = capsys.readouterr().out
        assert "left alone; pass --force to overwrite" in out
        assert "[FAIL] Rewrote 0 pinned copies; 1 edited locally" in out
        assert "[SUCCESS]" not in out

    def test_json_mode_runs_quietly(self, capsys):
        """Tests that --format json asks the engine for no progress lines."""
        result = RefreshResult(recipes=(_status(updated=True),), wrote=True)
        with patch("napt.upstream.refresh.refresh", return_value=result) as run:
            cmd_upstream_update(_args(path=[], format="json", force=False))

        assert run.call_args.kwargs["quiet"] is True
        assert json.loads(capsys.readouterr().out)[0]["updated"] is True
