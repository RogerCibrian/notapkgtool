"""Tests for napt.cli.validate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from napt.cli.validate import _display_path, cmd_validate
from napt.exceptions import ConfigError
from napt.results import ValidationResult
from tests.cli.conftest import _args, _mock_result


class TestCmdValidate:
    """Tests for cmd_validate handler."""

    def test_valid_recipe_returns_zero(self, tmp_path, capsys):
        """Tests that a valid recipe prints success and returns 0."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            is_valid=True,
            errors=[],
            warnings=[],
            recipe_path=str(recipe),
        )
        with patch("napt.validation.validate_recipe", return_value=mock_result):
            assert cmd_validate(_args(recipe=recipe)) == 0
        out = capsys.readouterr().out
        assert "[SUCCESS]" in out
        assert "Status:      VALID" in out
        assert "App Count" not in out

    def test_invalid_recipe_returns_one(self, tmp_path, capsys):
        """Tests that an invalid recipe prints errors and returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            is_valid=False,
            errors=["Missing required field: id"],
            warnings=[],
            recipe_path=str(recipe),
        )
        with patch("napt.validation.validate_recipe", return_value=mock_result):
            assert cmd_validate(_args(recipe=recipe)) == 1
        out = capsys.readouterr().out
        assert "[FAILED]" in out
        assert "Missing required field: id" in out
        assert "[X]" in out

    def test_warnings_printed_on_valid_recipe(self, tmp_path, capsys):
        """Tests that warnings are shown even when recipe is valid."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            is_valid=True,
            errors=[],
            warnings=["Unknown field 'foo'"],
            recipe_path=str(recipe),
        )
        with patch("napt.validation.validate_recipe", return_value=mock_result):
            assert cmd_validate(_args(recipe=recipe)) == 0
        out = capsys.readouterr().out
        assert "[WARNING]" in out
        assert "Unknown field 'foo'" in out

    def test_multiple_errors_all_displayed(self, tmp_path, capsys):
        """Tests that all errors are printed."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            is_valid=False,
            errors=["Error one", "Error two", "Error three"],
            warnings=[],
            recipe_path=str(recipe),
        )
        with patch("napt.validation.validate_recipe", return_value=mock_result):
            cmd_validate(_args(recipe=recipe))
        out = capsys.readouterr().out
        assert "Error one" in out
        assert "Error two" in out
        assert "Error three" in out
        assert "3 error" in out

    def test_parent_line_printed_when_present(self, tmp_path, capsys):
        """Tests that the parent recipe is named in the results when merged."""
        recipe = tmp_path / "app.override.yaml"
        recipe.touch()
        result = ValidationResult(
            errors=[],
            warnings=[],
            recipe_path=str(recipe),
            parent_path=str(tmp_path / "base.yaml"),
        )
        with patch("napt.validation.validate_recipe", return_value=result):
            assert cmd_validate(_args(recipe=recipe)) == 0
        out = capsys.readouterr().out
        assert f"Parent:      {tmp_path / 'base.yaml'}" in out

    def test_parent_line_absent_without_parent(self, tmp_path, capsys):
        """Tests that no parent line is printed for a plain recipe."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        result = ValidationResult(
            errors=[],
            warnings=[],
            recipe_path=str(recipe),
        )
        with patch("napt.validation.validate_recipe", return_value=result):
            cmd_validate(_args(recipe=recipe))
        out = capsys.readouterr().out
        assert "Parent:" not in out


class TestDebugProvenance:
    """Tests for the provenance block that --debug adds."""

    @staticmethod
    def _valid_recipe(tmp_path):
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nname: App\nid: app\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n"
        )
        return recipe

    def test_load_failure_is_reported_not_hidden(self, tmp_path, capsys):
        """Tests that a recipe that validates but cannot be merged says so."""
        recipe = self._valid_recipe(tmp_path)

        with patch(
            "napt.config.loader.load_effective_config",
            side_effect=ConfigError("merge failed"),
        ):
            code = cmd_validate(_args(recipe=recipe, debug=True))

        assert code == 0
        assert "Provenance unavailable: merge failed" in capsys.readouterr().out

    def test_unexpected_error_is_not_swallowed(self, tmp_path):
        """Tests that a bug in the loader surfaces instead of printing VALID."""
        recipe = self._valid_recipe(tmp_path)

        with patch(
            "napt.config.loader.load_effective_config",
            side_effect=TypeError("bug"),
        ):
            with pytest.raises(TypeError):
                cmd_validate(_args(recipe=recipe, debug=True))


class TestDirectoryMode:
    """Tests for validating a directory of recipes."""

    @staticmethod
    def _write(recipes, name: str, body: str):
        path = recipes / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    def test_all_valid_returns_zero(self, tmp_path, capsys):
        """Tests that a directory of valid recipes lists each and returns 0."""
        recipes = tmp_path / "recipes"
        self._write(
            recipes,
            "a/one.yaml",
            "apiVersion: napt/v1\nname: One\nid: one\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n",
        )
        self._write(
            recipes,
            "b/two.yaml",
            "apiVersion: napt/v1\nname: Two\nid: two\n"
            "discovery:\n  strategy: url_download\n  url: https://x/b.msi\n",
        )

        assert cmd_validate(_args(recipe=recipes)) == 0

        out = capsys.readouterr().out
        assert "[OK]" in out
        assert "one.yaml" in out
        assert "two.yaml" in out
        assert "[FAIL]" not in out

    def test_any_invalid_returns_one_with_errors_listed(self, tmp_path, capsys):
        """Tests that one bad recipe fails the run and its errors are shown
        under its path, while the good one still reads as OK."""
        recipes = tmp_path / "recipes"
        self._write(
            recipes,
            "one.yaml",
            "apiVersion: napt/v1\nname: One\nid: one\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n",
        )
        self._write(recipes, "two.yaml", "apiVersion: napt/v1\nname: Two\nid: two\n")

        assert cmd_validate(_args(recipe=recipes)) == 1

        out = capsys.readouterr().out
        assert "[OK]" in out
        assert "[FAIL]" in out
        assert "two.yaml" in out
        assert "Missing required field: discovery" in out

    def test_duplicate_ids_fail_the_run(self, tmp_path, capsys):
        """Tests that a parent and child sharing an id are reported."""
        recipes = tmp_path / "recipes"
        self._write(
            recipes,
            "base.yaml",
            "apiVersion: napt/v1\nname: One\nid: one\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n",
        )
        self._write(
            recipes, "base.override.yaml", "apiVersion: napt/v1\nparent: base.yaml\n"
        )

        assert cmd_validate(_args(recipe=recipes)) == 1

        out = capsys.readouterr().out
        assert "Recipe id 'one' is declared by both" in out

    def test_warnings_are_listed_under_the_recipe(self, tmp_path, capsys):
        """Tests that a recipe that validates with warnings shows them."""
        recipes = tmp_path / "recipes"
        self._write(
            recipes,
            "one.yaml",
            "apiVersion: napt/v1\nname: One\nid: one\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n"
            "intune:\n  colour: blue\n",
        )

        assert cmd_validate(_args(recipe=recipes)) == 0

        out = capsys.readouterr().out
        assert "[OK]" in out
        assert "[WARNING] intune: Unknown field 'colour'" in out

    def test_debug_prints_provenance_per_recipe(self, tmp_path, capsys):
        """Tests that --debug adds a provenance block for each valid recipe."""
        recipes = tmp_path / "recipes"
        self._write(
            recipes,
            "one.yaml",
            "apiVersion: napt/v1\nname: One\nid: one\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n",
        )
        self._write(
            recipes,
            "two.yaml",
            "apiVersion: napt/v1\nname: Two\nid: two\n"
            "discovery:\n  strategy: url_download\n  url: https://x/b.msi\n",
        )

        assert cmd_validate(_args(recipe=recipes, debug=True)) == 0

        out = capsys.readouterr().out
        assert out.count("CONFIGURATION PROVENANCE") == 2
        assert "Recipe: one.yaml" in out
        assert "Recipe: two.yaml" in out


class TestDisplayPath:
    """Tests for the path shown beside each directory-mode result."""

    def test_recipe_under_the_root_is_shown_relative(self, tmp_path):
        """Tests that a recipe inside the scanned directory is shortened."""
        result = ValidationResult(
            errors=[],
            warnings=[],
            recipe_path=str(tmp_path / "recipes" / "a" / "one.yaml"),
        )

        assert _display_path(result, tmp_path / "recipes") == str(
            Path("a") / "one.yaml"
        )

    def test_recipe_outside_the_root_is_shown_as_recorded(self, tmp_path):
        """Tests that a path not under the root is printed unchanged."""
        elsewhere = str(tmp_path / "other" / "one.yaml")
        result = ValidationResult(
            errors=["x"],
            warnings=[],
            recipe_path=elsewhere,
        )

        assert _display_path(result, tmp_path / "recipes") == elsewhere
