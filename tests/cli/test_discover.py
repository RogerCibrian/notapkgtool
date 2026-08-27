"""Tests for napt.cli.discover."""

from __future__ import annotations

from unittest.mock import patch

from napt.cli.discover import cmd_discover
from napt.exceptions import ConfigError, NetworkError
from tests.cli.conftest import _args, _mock_result


class TestCmdDiscover:
    """Tests for cmd_discover handler."""

    def test_missing_recipe_returns_one(self, tmp_path, capsys):
        """Tests that a missing recipe file exits with code 1."""
        code = cmd_discover(
            _args(
                recipe=str(tmp_path / "nonexistent.yaml"),
                output_dir=None,
                cache_file=None,
                state_dir=None,
                stateless=False,
            )
        )
        assert code == 1
        assert "not found" in capsys.readouterr().out

    def test_success_prints_results_returns_zero(self, tmp_path, capsys):
        """Tests that successful discovery prints all result fields."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            app_name="Chrome",
            app_id="napt-chrome",
            strategy="api_github",
            version="130.0.6723.116",
            version_source="regex_in_tag",
            file_path=tmp_path / "chrome.msi",
            sha256="a" * 64,
            status="success",
        )
        with patch("napt.cli.discover.discover_recipe", return_value=mock_result):
            code = cmd_discover(
                _args(
                    recipe=str(recipe),
                    output_dir=None,
                    cache_file=None,
                    state_dir=None,
                    stateless=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "[SUCCESS]" in out
        assert "130.0.6723.116" in out
        assert "napt-chrome" in out

    def test_config_error_prints_message_returns_one(self, tmp_path, capsys):
        """Tests that ConfigError is caught, message printed, returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch(
            "napt.cli.discover.discover_recipe", side_effect=ConfigError("bad config")
        ):
            code = cmd_discover(
                _args(
                    recipe=str(recipe),
                    output_dir=None,
                    cache_file=None,
                    state_dir=None,
                    stateless=False,
                )
            )
        assert code == 1
        assert "bad config" in capsys.readouterr().out

    def test_network_error_returns_one(self, tmp_path):
        """Tests that NetworkError returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch(
            "napt.cli.discover.discover_recipe", side_effect=NetworkError("timeout")
        ):
            assert (
                cmd_discover(
                    _args(
                        recipe=str(recipe),
                        output_dir=None,
                        cache_file=None,
                        state_dir=None,
                        stateless=False,
                    )
                )
                == 1
            )

    def test_stateless_flag_passed_through(self, tmp_path):
        """Tests that --stateless is passed to discover_recipe."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            app_name="T",
            app_id="t",
            strategy="url_download",
            version="1.0",
            version_source="msi",
            file_path=tmp_path / "f.msi",
            sha256="a" * 64,
            status="success",
        )
        with patch(
            "napt.cli.discover.discover_recipe", return_value=mock_result
        ) as mock:
            cmd_discover(
                _args(
                    recipe=str(recipe),
                    output_dir=None,
                    cache_file=None,
                    state_dir=None,
                    stateless=True,
                )
            )
        _, kwargs = mock.call_args
        assert kwargs["stateless"] is True
        assert kwargs["cache_file"] is None
        assert kwargs["state_dir"] is None

    def test_output_dir_passed_through(self, tmp_path):
        """Tests that --output-dir is resolved and passed to discover_recipe."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        custom_output = tmp_path / "custom_output"
        mock_result = _mock_result(
            app_name="T",
            app_id="t",
            strategy="url_download",
            version="1.0",
            version_source="msi",
            file_path=tmp_path / "f.msi",
            sha256="a" * 64,
            status="success",
        )
        with patch(
            "napt.cli.discover.discover_recipe", return_value=mock_result
        ) as mock:
            cmd_discover(
                _args(
                    recipe=str(recipe),
                    output_dir=str(custom_output),
                    cache_file=None,
                    state_dir=None,
                    stateless=False,
                )
            )
        call_args = mock.call_args[0]
        assert call_args[1] == custom_output.resolve()
