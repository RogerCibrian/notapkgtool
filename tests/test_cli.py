"""Tests for napt.cli command handlers."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import pytest

from napt.cli import (
    _resolve_build_dir_from_recipe,
    cmd_build,
    cmd_discover,
    cmd_init,
    cmd_package,
    cmd_upload,
    cmd_validate,
)
from napt.exceptions import AuthError, ConfigError, NetworkError, PackagingError


def _args(**kwargs) -> argparse.Namespace:
    """Build Namespace with verbose=False, debug=False defaults."""
    defaults = {"verbose": False, "debug": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _mock_result(**kwargs) -> MagicMock:
    """Build a MagicMock with the given attributes."""
    result = MagicMock()
    for k, v in kwargs.items():
        setattr(result, k, v)
    return result


# =============================================================================
# cmd_validate
# =============================================================================


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
        with patch("napt.cli.validate_recipe", return_value=mock_result):
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
        with patch("napt.cli.validate_recipe", return_value=mock_result):
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
        with patch("napt.cli.validate_recipe", return_value=mock_result):
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
        with patch("napt.cli.validate_recipe", return_value=mock_result):
            cmd_validate(_args(recipe=str(recipe)))
        out = capsys.readouterr().out
        assert "Error one" in out
        assert "Error two" in out
        assert "Error three" in out
        assert "3 error" in out


# =============================================================================
# cmd_discover
# =============================================================================


class TestCmdDiscover:
    """Tests for cmd_discover handler."""

    def test_missing_recipe_returns_one(self, tmp_path, capsys):
        """Tests that a missing recipe file exits with code 1."""
        code = cmd_discover(
            _args(
                recipe=str(tmp_path / "nonexistent.yaml"),
                output_dir=None,
                state_file=Path("state/versions.json"),
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
        with patch("napt.cli.discover_recipe", return_value=mock_result):
            code = cmd_discover(
                _args(
                    recipe=str(recipe),
                    output_dir=None,
                    state_file=Path("state/versions.json"),
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
        with patch("napt.cli.discover_recipe", side_effect=ConfigError("bad config")):
            code = cmd_discover(
                _args(
                    recipe=str(recipe),
                    output_dir=None,
                    state_file=Path("state/versions.json"),
                    stateless=False,
                )
            )
        assert code == 1
        assert "bad config" in capsys.readouterr().out

    def test_network_error_returns_one(self, tmp_path):
        """Tests that NetworkError returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch("napt.cli.discover_recipe", side_effect=NetworkError("timeout")):
            assert (
                cmd_discover(
                    _args(
                        recipe=str(recipe),
                        output_dir=None,
                        state_file=Path("state/versions.json"),
                        stateless=False,
                    )
                )
                == 1
            )

    def test_stateless_passes_none_state_file(self, tmp_path):
        """Tests that --stateless causes state_file=None to be passed."""
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
        with patch("napt.cli.discover_recipe", return_value=mock_result) as mock:
            cmd_discover(
                _args(
                    recipe=str(recipe),
                    output_dir=None,
                    state_file=Path("state/versions.json"),
                    stateless=True,
                )
            )
        _, kwargs = mock.call_args
        assert kwargs["state_file"] is None

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
        with patch("napt.cli.discover_recipe", return_value=mock_result) as mock:
            cmd_discover(
                _args(
                    recipe=str(recipe),
                    output_dir=str(custom_output),
                    state_file=Path("state/versions.json"),
                    stateless=False,
                )
            )
        call_args = mock.call_args[0]
        assert call_args[1] == custom_output.resolve()


# =============================================================================
# cmd_build
# =============================================================================


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
        with patch("napt.cli.build_package", return_value=mock_result):
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
            "napt.cli.build_package", side_effect=PackagingError("build failed")
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
        with patch("napt.cli.build_package", side_effect=ConfigError("no installer")):
            assert (
                cmd_build(
                    _args(recipe=str(recipe), downloads_dir=None, output_dir=None)
                )
                == 1
            )


# =============================================================================
# cmd_package
# =============================================================================


class TestCmdPackage:
    """Tests for cmd_package handler."""

    def test_missing_recipe_returns_one(self, tmp_path, capsys):
        """Tests that a missing recipe file exits with code 1."""
        code = cmd_package(
            _args(
                recipe=str(tmp_path / "nonexistent.yaml"),
                version=None,
                builds_dir=None,
                output_dir=None,
                clean_source=False,
            )
        )
        assert code == 1

    def test_resolve_config_error_returns_one(self, tmp_path, capsys):
        """Tests that ConfigError from _resolve_build_dir_from_recipe returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch(
            "napt.cli._resolve_build_dir_from_recipe",
            side_effect=ConfigError("no builds found"),
        ):
            code = cmd_package(
                _args(
                    recipe=str(recipe),
                    version=None,
                    builds_dir=None,
                    output_dir=None,
                    clean_source=False,
                )
            )
        assert code == 1
        assert "no builds found" in capsys.readouterr().out

    def test_success_returns_zero(self, tmp_path, capsys):
        """Tests that successful packaging returns 0."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        build_dir = tmp_path / "build"
        mock_result = _mock_result(
            app_id="test-app",
            version="1.2.3",
            package_path=tmp_path / "test.intunewin",
            build_dir=build_dir,
            status="success",
        )
        mock_config = {
            "directories": {"package": "packages"},
            "intunewin": {"release": "latest"},
        }
        with patch("napt.cli._resolve_build_dir_from_recipe", return_value=build_dir):
            with patch("napt.cli.load_effective_config", return_value=mock_config):
                with patch("napt.cli.create_intunewin", return_value=mock_result):
                    code = cmd_package(
                        _args(
                            recipe=str(recipe),
                            version=None,
                            builds_dir=None,
                            output_dir=None,
                            clean_source=False,
                        )
                    )
        assert code == 0
        assert "[SUCCESS]" in capsys.readouterr().out

    def test_clean_source_shows_removed_label(self, tmp_path, capsys):
        """Tests that --clean-source appends '(removed)' to the build dir line."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        build_dir = tmp_path / "build"
        mock_result = _mock_result(
            app_id="test-app",
            version="1.2.3",
            package_path=tmp_path / "test.intunewin",
            build_dir=build_dir,
            status="success",
        )
        mock_config = {
            "directories": {"package": "packages"},
            "intunewin": {"release": "latest"},
        }
        with patch("napt.cli._resolve_build_dir_from_recipe", return_value=build_dir):
            with patch("napt.cli.load_effective_config", return_value=mock_config):
                with patch("napt.cli.create_intunewin", return_value=mock_result):
                    cmd_package(
                        _args(
                            recipe=str(recipe),
                            version=None,
                            builds_dir=None,
                            output_dir=None,
                            clean_source=True,
                        )
                    )
        assert "(removed)" in capsys.readouterr().out

    def test_packaging_error_returns_one(self, tmp_path, capsys):
        """Tests that PackagingError from create_intunewin returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        build_dir = tmp_path / "build"
        mock_config = {
            "directories": {"package": "packages"},
            "intunewin": {"release": "latest"},
        }
        with patch("napt.cli._resolve_build_dir_from_recipe", return_value=build_dir):
            with patch("napt.cli.load_effective_config", return_value=mock_config):
                with patch(
                    "napt.cli.create_intunewin",
                    side_effect=PackagingError("pack fail"),
                ):
                    code = cmd_package(
                        _args(
                            recipe=str(recipe),
                            version=None,
                            builds_dir=None,
                            output_dir=None,
                            clean_source=False,
                        )
                    )
        assert code == 1
        assert "pack fail" in capsys.readouterr().out

    def test_custom_output_dir_used(self, tmp_path):
        """Tests that --output-dir overrides the config directory."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        build_dir = tmp_path / "build"
        custom_out = tmp_path / "custom_packages"
        mock_result = _mock_result(
            app_id="test-app",
            version="1.2.3",
            package_path=custom_out / "test.intunewin",
            build_dir=build_dir,
            status="success",
        )
        mock_config = {
            "directories": {"package": "packages"},
            "intunewin": {"release": "latest"},
        }
        with patch("napt.cli._resolve_build_dir_from_recipe", return_value=build_dir):
            with patch("napt.cli.load_effective_config", return_value=mock_config):
                with patch(
                    "napt.cli.create_intunewin", return_value=mock_result
                ) as mock_create:
                    cmd_package(
                        _args(
                            recipe=str(recipe),
                            version=None,
                            builds_dir=None,
                            output_dir=str(custom_out),
                            clean_source=False,
                        )
                    )
        _, kwargs = mock_create.call_args
        assert kwargs["output_dir"] == custom_out


# =============================================================================
# cmd_upload
# =============================================================================


class TestCmdUpload:
    """Tests for cmd_upload handler."""

    def test_missing_recipe_returns_one(self, tmp_path, capsys):
        """Tests that a missing recipe file exits with code 1."""
        code = cmd_upload(_args(recipe=str(tmp_path / "nonexistent.yaml")))
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
        with patch("napt.cli.upload_package", return_value=mock_result):
            code = cmd_upload(_args(recipe=str(recipe)))
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
            "napt.cli.upload_package",
            side_effect=AuthError("credential chain exhausted"),
        ):
            code = cmd_upload(_args(recipe=str(recipe)))
        assert code == 1
        out = capsys.readouterr().out
        assert "Authentication error" in out
        assert "credential chain exhausted" in out

    def test_config_error_returns_one(self, tmp_path):
        """Tests that ConfigError returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch("napt.cli.upload_package", side_effect=ConfigError("bad")):
            assert cmd_upload(_args(recipe=str(recipe))) == 1

    def test_network_error_returns_one(self, tmp_path):
        """Tests that NetworkError returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch("napt.cli.upload_package", side_effect=NetworkError("net")):
            assert cmd_upload(_args(recipe=str(recipe))) == 1


# =============================================================================
# cmd_init
# =============================================================================


class TestCmdInit:
    """Tests for cmd_init handler."""

    def test_fresh_directory_creates_full_structure(self, tmp_path, capsys):
        """Tests that init creates recipes/, defaults/vendors/, defaults/org.yaml."""
        code = cmd_init(_args(directory=str(tmp_path), force=False))
        assert code == 0
        assert (tmp_path / "recipes").is_dir()
        assert (tmp_path / "defaults" / "vendors").is_dir()
        assert (tmp_path / "defaults" / "org.yaml").exists()
        out = capsys.readouterr().out
        assert "[SUCCESS]" in out
        assert "[OK]" in out

    def test_existing_files_skipped_without_force(self, tmp_path, capsys):
        """Tests that existing files are preserved when --force is not used."""
        (tmp_path / "recipes").mkdir()
        org_yaml = tmp_path / "defaults" / "org.yaml"
        org_yaml.parent.mkdir(parents=True)
        org_yaml.write_text("original content")

        cmd_init(_args(directory=str(tmp_path), force=False))

        assert org_yaml.read_text() == "original content"
        out = capsys.readouterr().out
        assert "[SKIP]" in out
        assert "Existing files were preserved" in out

    def test_force_backs_up_and_recreates_org_yaml(self, tmp_path, capsys):
        """Tests that --force backs up existing org.yaml and creates a fresh one."""
        org_yaml = tmp_path / "defaults" / "org.yaml"
        org_yaml.parent.mkdir(parents=True)
        org_yaml.write_text("original content")

        cmd_init(_args(directory=str(tmp_path), force=True))

        backup = tmp_path / "defaults" / "org.yaml.backup"
        assert backup.exists()
        assert backup.read_text() == "original content"
        assert org_yaml.exists()
        assert org_yaml.read_text() != "original content"
        out = capsys.readouterr().out
        assert "Backed Up" in out

    def test_org_yaml_contains_template_content(self, tmp_path):
        """Tests that the created org.yaml matches ORG_YAML_TEMPLATE exactly."""
        from napt.config.defaults import ORG_YAML_TEMPLATE

        cmd_init(_args(directory=str(tmp_path), force=False))
        content = (tmp_path / "defaults" / "org.yaml").read_text(encoding="utf-8")
        assert content == ORG_YAML_TEMPLATE


# =============================================================================
# _resolve_build_dir_from_recipe
# =============================================================================


class TestResolveBuildDirFromRecipe:
    """Tests for _resolve_build_dir_from_recipe helper."""

    def test_no_app_build_dir_raises(self, tmp_path, create_yaml_file):
        """Tests that missing app build directory raises ConfigError."""
        recipe = create_yaml_file("recipe.yaml", {"id": "test-app"})
        builds_dir = tmp_path / "builds"
        mock_config = {
            "id": "test-app",
            "directories": {"build": str(builds_dir)},
        }
        with patch("napt.cli.load_effective_config", return_value=mock_config):
            with pytest.raises(ConfigError, match="No builds found"):
                _resolve_build_dir_from_recipe(recipe)

    def test_specific_version_found(self, tmp_path, create_yaml_file):
        """Tests that a specific version directory is returned when it exists."""
        recipe = create_yaml_file("recipe.yaml", {"id": "test-app"})
        builds_dir = tmp_path / "builds"
        app_ver_dir = builds_dir / "test-app" / "1.2.3"
        (app_ver_dir / "packagefiles").mkdir(parents=True)
        mock_config = {
            "id": "test-app",
            "directories": {"build": str(builds_dir)},
        }
        with patch("napt.cli.load_effective_config", return_value=mock_config):
            result = _resolve_build_dir_from_recipe(recipe, version="1.2.3")
        assert result == app_ver_dir

    def test_specific_version_missing_raises(self, tmp_path, create_yaml_file):
        """Tests that a missing specific version raises ConfigError."""
        recipe = create_yaml_file("recipe.yaml", {"id": "test-app"})
        builds_dir = tmp_path / "builds"
        (builds_dir / "test-app").mkdir(parents=True)
        mock_config = {
            "id": "test-app",
            "directories": {"build": str(builds_dir)},
        }
        with patch("napt.cli.load_effective_config", return_value=mock_config):
            with pytest.raises(ConfigError, match="not found"):
                _resolve_build_dir_from_recipe(recipe, version="9.9.9")

    def test_specific_version_without_packagefiles_raises(
        self, tmp_path, create_yaml_file
    ):
        """Tests that a version dir without packagefiles/ raises ConfigError."""
        recipe = create_yaml_file("recipe.yaml", {"id": "test-app"})
        builds_dir = tmp_path / "builds"
        (builds_dir / "test-app" / "1.2.3").mkdir(parents=True)  # no packagefiles/
        mock_config = {
            "id": "test-app",
            "directories": {"build": str(builds_dir)},
        }
        with patch("napt.cli.load_effective_config", return_value=mock_config):
            with pytest.raises(ConfigError, match="not found"):
                _resolve_build_dir_from_recipe(recipe, version="1.2.3")

    def test_most_recent_version_selected(self, tmp_path, create_yaml_file):
        """Tests that the most recently modified version directory is returned."""
        recipe = create_yaml_file("recipe.yaml", {"id": "test-app"})
        builds_dir = tmp_path / "builds"
        old_dir = builds_dir / "test-app" / "1.0.0"
        new_dir = builds_dir / "test-app" / "2.0.0"
        (old_dir / "packagefiles").mkdir(parents=True)
        (new_dir / "packagefiles").mkdir(parents=True)
        os.utime(old_dir, (time.time() - 100, time.time() - 100))
        os.utime(new_dir, (time.time(), time.time()))
        mock_config = {
            "id": "test-app",
            "directories": {"build": str(builds_dir)},
        }
        with patch("napt.cli.load_effective_config", return_value=mock_config):
            result = _resolve_build_dir_from_recipe(recipe)
        assert result == new_dir

    def test_no_completed_builds_raises(self, tmp_path, create_yaml_file):
        """Tests that app dir with no packagefiles/ subdirs raises ConfigError."""
        recipe = create_yaml_file("recipe.yaml", {"id": "test-app"})
        builds_dir = tmp_path / "builds"
        (builds_dir / "test-app" / "1.0.0").mkdir(parents=True)  # no packagefiles/
        mock_config = {
            "id": "test-app",
            "directories": {"build": str(builds_dir)},
        }
        with patch("napt.cli.load_effective_config", return_value=mock_config):
            with pytest.raises(ConfigError, match="No completed builds"):
                _resolve_build_dir_from_recipe(recipe)

    def test_custom_builds_dir_overrides_config(self, tmp_path, create_yaml_file):
        """Tests that an explicit builds_dir overrides the config directory."""
        recipe = create_yaml_file("recipe.yaml", {"id": "test-app"})
        custom_builds = tmp_path / "custom_builds"
        app_ver_dir = custom_builds / "test-app" / "3.0.0"
        (app_ver_dir / "packagefiles").mkdir(parents=True)
        mock_config = {
            "id": "test-app",
            "directories": {"build": str(tmp_path / "other_builds")},
        }
        with patch("napt.cli.load_effective_config", return_value=mock_config):
            result = _resolve_build_dir_from_recipe(recipe, builds_dir=custom_builds)
        assert result == app_ver_dir
