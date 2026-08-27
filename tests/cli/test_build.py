"""Tests for napt.cli.build."""

from __future__ import annotations

from unittest.mock import patch

from napt.cli.build import cmd_build
from napt.exceptions import ConfigError, PackagingError
from tests.cli.conftest import _args, _mock_result


class TestCmdBuild:
    """Tests for cmd_build handler."""

    def test_missing_recipe_returns_one(self, tmp_path, capsys):
        """Tests that a missing recipe file exits with code 1."""
        code = cmd_build(
            _args(
                recipe=str(tmp_path / "nonexistent.yaml"),
                downloads_dir=None,
                output_dir=None,
            )
        )
        assert code == 1
        assert "not found" in capsys.readouterr().out

    def test_success_prints_results_returns_zero(self, tmp_path, capsys):
        """Tests that successful build prints all result fields."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            app_name="Test App",
            app_id="test-app",
            version="1.2.3",
            psadt_version="4.1.7",
            build_dir=tmp_path / "build",
            status="success",
        )
        with patch("napt.cli.build.build_package", return_value=mock_result):
            code = cmd_build(
                _args(recipe=str(recipe), downloads_dir=None, output_dir=None)
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "[SUCCESS]" in out
        assert "4.1.7" in out
        assert "1.2.3" in out

    def test_packaging_error_prints_message_returns_one(self, tmp_path, capsys):
        """Tests that PackagingError is caught and returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch(
            "napt.cli.build.build_package", side_effect=PackagingError("build failed")
        ):
            code = cmd_build(
                _args(recipe=str(recipe), downloads_dir=None, output_dir=None)
            )
        assert code == 1
        assert "build failed" in capsys.readouterr().out

    def test_config_error_returns_one(self, tmp_path):
        """Tests that ConfigError returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch(
            "napt.cli.build.build_package", side_effect=ConfigError("no installer")
        ):
            assert (
                cmd_build(
                    _args(recipe=str(recipe), downloads_dir=None, output_dir=None)
                )
                == 1
            )
