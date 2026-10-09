"""Tests for napt.cli.upstream."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from napt.cli.common import run_handler
from napt.cli.upstream import cmd_upstream_add, cmd_upstream_remove
from napt.exceptions import ConfigError
from napt.upstream.add import AddResult, PlannedRecipe
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
