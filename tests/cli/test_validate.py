"""Tests for napt.cli.validate."""

from __future__ import annotations

from unittest.mock import patch

from napt.cli.validate import cmd_validate
from napt.results import ValidationResult
from tests.cli.conftest import _args, _mock_result


class TestCmdValidate:
    """Tests for cmd_validate handler."""

    def test_valid_recipe_returns_zero(self, tmp_path, capsys):
        """Tests that a valid recipe prints success and returns 0."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            status="valid",
            app_count=1,
            errors=[],
            warnings=[],
            recipe_path=str(recipe),
        )
        with patch("napt.cli.validate.validate_recipe", return_value=mock_result):
            assert cmd_validate(_args(recipe=str(recipe))) == 0
        out = capsys.readouterr().out
        assert "[SUCCESS]" in out
        assert "App Count:   1" in out

    def test_invalid_recipe_returns_one(self, tmp_path, capsys):
        """Tests that an invalid recipe prints errors and returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            status="invalid",
            app_count=0,
            errors=["Missing required field: id"],
            warnings=[],
            recipe_path=str(recipe),
        )
        with patch("napt.cli.validate.validate_recipe", return_value=mock_result):
            assert cmd_validate(_args(recipe=str(recipe))) == 1
        out = capsys.readouterr().out
        assert "[FAILED]" in out
        assert "Missing required field: id" in out
        assert "[X]" in out

    def test_warnings_printed_on_valid_recipe(self, tmp_path, capsys):
        """Tests that warnings are shown even when recipe is valid."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            status="valid",
            app_count=1,
            errors=[],
            warnings=["Unknown field 'foo'"],
            recipe_path=str(recipe),
        )
        with patch("napt.cli.validate.validate_recipe", return_value=mock_result):
            assert cmd_validate(_args(recipe=str(recipe))) == 0
        out = capsys.readouterr().out
        assert "[WARNING]" in out
        assert "Unknown field 'foo'" in out

    def test_multiple_errors_all_displayed(self, tmp_path, capsys):
        """Tests that all errors are printed."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            status="invalid",
            app_count=0,
            errors=["Error one", "Error two", "Error three"],
            warnings=[],
            recipe_path=str(recipe),
        )
        with patch("napt.cli.validate.validate_recipe", return_value=mock_result):
            cmd_validate(_args(recipe=str(recipe)))
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
            status="valid",
            errors=[],
            warnings=[],
            app_count=1,
            recipe_path=str(recipe),
            parent_path=str(tmp_path / "base.yaml"),
        )
        with patch("napt.cli.validate.validate_recipe", return_value=result):
            assert cmd_validate(_args(recipe=str(recipe))) == 0
        out = capsys.readouterr().out
        assert f"Parent:      {tmp_path / 'base.yaml'}" in out

    def test_parent_line_absent_without_parent(self, tmp_path, capsys):
        """Tests that no parent line is printed for a plain recipe."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        result = ValidationResult(
            status="valid",
            errors=[],
            warnings=[],
            app_count=1,
            recipe_path=str(recipe),
        )
        with patch("napt.cli.validate.validate_recipe", return_value=result):
            cmd_validate(_args(recipe=str(recipe)))
        out = capsys.readouterr().out
        assert "Parent:" not in out
