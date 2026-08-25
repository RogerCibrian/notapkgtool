"""Tests for napt.cli.upload."""

from __future__ import annotations

from unittest.mock import patch

from napt.cli.upload import cmd_upload
from napt.exceptions import AuthError, ConfigError, NetworkError
from tests.cli.conftest import _args, _mock_result


class TestCmdUpload:
    """Tests for cmd_upload handler."""

    def test_missing_recipe_returns_one(self, tmp_path, capsys):
        """Tests that a missing recipe file exits with code 1."""
        code = cmd_upload(_args(recipe=str(tmp_path / "nonexistent.yaml"), force=False))
        assert code == 1

    def test_success_prints_results_returns_zero(self, tmp_path, capsys):
        """Tests that successful upload prints all result fields."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        mock_result = _mock_result(
            app_id="test-app",
            app_name="Test App",
            version="1.2.3",
            intune_app_id="guid-abc-123",
            package_path=tmp_path / "test.intunewin",
            status="success",
        )
        with patch("napt.cli.upload.upload_package", return_value=mock_result):
            code = cmd_upload(_args(recipe=str(recipe), force=False))
        assert code == 0
        out = capsys.readouterr().out
        assert "[SUCCESS]" in out
        assert "guid-abc-123" in out
        assert "Test App" in out

    def test_auth_error_prints_authentication_prefix(self, tmp_path, capsys):
        """Tests that AuthError prints 'Authentication error:' prefix."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch(
            "napt.cli.upload.upload_package",
            side_effect=AuthError("credential chain exhausted"),
        ):
            code = cmd_upload(_args(recipe=str(recipe), force=False))
        assert code == 1
        out = capsys.readouterr().out
        assert "Authentication error" in out
        assert "credential chain exhausted" in out

    def test_config_error_returns_one(self, tmp_path):
        """Tests that ConfigError returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch("napt.cli.upload.upload_package", side_effect=ConfigError("bad")):
            assert cmd_upload(_args(recipe=str(recipe), force=False)) == 1

    def test_network_error_returns_one(self, tmp_path):
        """Tests that NetworkError returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch("napt.cli.upload.upload_package", side_effect=NetworkError("net")):
            assert cmd_upload(_args(recipe=str(recipe), force=False)) == 1
