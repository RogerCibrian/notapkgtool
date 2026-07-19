"""Tests for napt.cli command handlers."""

from __future__ import annotations

import argparse
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from napt.cli import (
    _resolve_build_dir_from_recipe,
    cmd_build,
    cmd_discover,
    cmd_init,
    cmd_package,
    cmd_promote_apply,
    cmd_promote_plan,
    cmd_status,
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
        with patch("napt.cli.discover_recipe", return_value=mock_result):
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
        with patch("napt.cli.discover_recipe", side_effect=ConfigError("bad config")):
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
        with patch("napt.cli.discover_recipe", side_effect=NetworkError("timeout")):
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
        with patch("napt.cli.discover_recipe", return_value=mock_result) as mock:
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
        with patch("napt.cli.discover_recipe", return_value=mock_result) as mock:
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
        with patch("napt.cli.upload_package", return_value=mock_result):
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
            "napt.cli.upload_package",
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
        with patch("napt.cli.upload_package", side_effect=ConfigError("bad")):
            assert cmd_upload(_args(recipe=str(recipe), force=False)) == 1

    def test_network_error_returns_one(self, tmp_path):
        """Tests that NetworkError returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch("napt.cli.upload_package", side_effect=NetworkError("net")):
            assert cmd_upload(_args(recipe=str(recipe), force=False)) == 1


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


# =============================================================================
# cmd_promote_plan
# =============================================================================


class TestCmdPromotePlan:
    """Tests for cmd_promote_plan handler."""

    def test_actions_write_plan_and_return_zero(self, tmp_path, capsys):
        """Tests that planned actions print a summary and report the plan file."""
        actions = [
            {
                "type": "enter_ring",
                "app_id": "test-app",
                "version": "1.0.0",
                "sha256": "a" * 64,
                "ring": "pilot",
                "groups": ["sg-pilot"],
            }
        ]
        with (
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.plan_promotions", return_value=actions),
            patch("napt.cli.write_plan_files", return_value=["p"]) as write_mock,
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "enters ring 'pilot'" in out
        assert "Plan written" in out
        assert write_mock.call_args.args[0] == actions

    def test_no_actions_returns_zero(self, tmp_path, capsys):
        """Tests that an empty plan reports nothing to promote."""
        with (
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.plan_promotions", return_value=[]),
            patch("napt.cli.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "Nothing to promote" in out

    def test_config_error_returns_one(self, tmp_path, capsys):
        """Tests that ConfigError is caught and returns 1."""
        with (
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.plan_promotions", side_effect=ConfigError("bad")),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 1
        assert "bad" in capsys.readouterr().out


# =============================================================================
# cmd_status
# =============================================================================


class TestCmdStatus:
    """Tests for cmd_status handler."""

    def test_table_lists_apps(self, tmp_path, capsys):
        """Tests that the text table lists each app with its versions."""
        from napt.state import (
            create_default_deployment_state,
            deployment_state_path,
            save_deployment_state,
        )

        state = create_default_deployment_state()
        state["deployed"] = {"version": "1.2.3", "sha256": "a"}
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

        from napt.state import (
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


# =============================================================================
# cmd_promote_apply
# =============================================================================


class TestCmdPromoteApply:
    """Tests for cmd_promote_apply handler."""

    def test_applied_actions_print_and_return_zero(self, tmp_path, capsys):
        """Tests that applied and skipped actions are summarized."""
        summary = {
            "applied": [
                {
                    "type": "enter_ring",
                    "app_id": "test-app",
                    "version": "1.0.0",
                    "sha256": "a" * 64,
                    "ring": "pilot",
                    "groups": ["sg-pilot"],
                }
            ],
            "skipped": [
                {
                    "action": {
                        "type": "assign_install",
                        "app_id": "other-app",
                        "version": "1.0.0",
                        "sha256": "b" * 64,
                        "intent": "available",
                        "groups": ["All Users"],
                    },
                    "reason": "already applied",
                }
            ],
            "failed": [],
        }
        with patch("napt.cli.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "[OK]" in out
        assert "[SKIP]" in out
        assert "already applied" in out
        assert "Applied 1 action(s), skipped 1." in out

    def test_nothing_to_apply_returns_zero(self, tmp_path, capsys):
        """Tests that an empty summary reports cleanly."""
        summary = {"applied": [], "skipped": [], "failed": []}
        with patch("napt.cli.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 0
        assert "Nothing to apply" in capsys.readouterr().out

    def test_failed_apps_print_and_return_one(self, tmp_path, capsys):
        """Tests that per-app failures are printed and fail the run."""
        summary = {
            "applied": [],
            "skipped": [],
            "failed": [
                {
                    "app_id": "test-app",
                    "error": "unresolvable groups: ghost-group",
                }
            ],
        }
        with patch("napt.cli.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 1
        out = capsys.readouterr().out
        assert "[FAIL] test-app: unresolvable groups: ghost-group" in out
        assert "1 app(s) failed" in out

    def test_auth_error_returns_one(self, tmp_path, capsys):
        """Tests that AuthError is caught and returns 1."""
        with patch("napt.cli.apply_plan", side_effect=AuthError("no creds")):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 1
        assert "Authentication error" in capsys.readouterr().out

    def test_state_error_returns_one(self, tmp_path, capsys):
        """Tests that StateError is caught and returns 1."""
        from napt.exceptions import StateError

        with patch("napt.cli.apply_plan", side_effect=StateError("bad plan")):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 1
        assert "bad plan" in capsys.readouterr().out


# =============================================================================
# drift output
# =============================================================================


class TestDriftOutput:
    """Tests for drift warning presentation."""

    def test_plan_check_drift_prints_findings(self, tmp_path, capsys):
        """Tests that --check-drift findings are printed as warnings."""
        finding = {
            "app_id": "test-app",
            "kind": "missing_assignment",
            "detail": "expected assignment gone",
        }
        with (
            patch("napt.cli.plan_promotions", return_value=[]),
            patch("napt.cli.write_plan_files", return_value=[]),
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.get_access_token", return_value="tok"),
            patch("napt.cli.list_mobile_apps", return_value=[]),
            patch("napt.cli.detect_drift", return_value=[finding]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=True,
                    reconcile=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "DRIFT CHECK" in out
        assert "[WARNING] test-app: expected assignment gone" in out

    def test_apply_prints_drift_from_summary(self, tmp_path, capsys):
        """Tests that apply prints drift findings from the summary."""
        summary = {
            "applied": [],
            "skipped": [],
            "failed": [],
            "drift": [
                {
                    "app_id": "test-app",
                    "kind": "orphaned_release",
                    "detail": "stray app",
                }
            ],
        }
        with patch("napt.cli.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "DRIFT CHECK" in out
        assert "[WARNING] test-app: stray app" in out


# =============================================================================
# reconciliation output
# =============================================================================


class TestReconcileOutput:
    """Tests for publication reconciliation presentation."""

    def test_plan_reconcile_prints_findings(self, tmp_path, capsys):
        """Tests that --reconcile findings are printed with kind markers."""
        findings = [
            {
                "app_id": "test-app",
                "kind": "recovered",
                "detail": "recorded publication of 2.0.0",
            },
            {
                "app_id": "other-app",
                "kind": "incomplete",
                "detail": "partially published - re-run publish to finish",
            },
        ]
        with (
            patch("napt.cli.plan_promotions", return_value=[]),
            patch("napt.cli.write_plan_files", return_value=[]),
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.get_access_token", return_value="tok"),
            patch("napt.cli.list_mobile_apps", return_value=[]),
            patch("napt.cli.reconcile_publications", return_value=findings),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=True,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "PUBLICATION RECONCILIATION" in out
        assert "[OK] test-app: recorded publication of 2.0.0" in out
        assert "[WARNING] other-app:" in out

    def test_plan_reconcile_runs_before_planning(self, tmp_path, capsys):
        """Tests that reconciliation happens before the plan is computed."""
        order: list[str] = []
        with (
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.get_access_token", return_value="tok"),
            patch("napt.cli.list_mobile_apps", return_value=[]),
            patch(
                "napt.cli.reconcile_publications",
                side_effect=lambda *a: order.append("reconcile") or [],
            ),
            patch(
                "napt.cli.plan_promotions",
                side_effect=lambda *a, **k: order.append("plan") or [],
            ),
            patch("napt.cli.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=True,
                )
            )
        assert code == 0
        assert order == ["reconcile", "plan"]

    def test_plan_validation_failure_writes_no_plan(self, tmp_path, capsys):
        """Tests that an unresolvable group fails the authenticated plan
        without writing a plan file."""
        actions = [
            {
                "type": "enter_ring",
                "app_id": "test-app",
                "version": "1.0.0",
                "sha256": "a" * 64,
                "ring": "pilot",
                "groups": ["ghost-group"],
            }
        ]
        with (
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.get_access_token", return_value="tok"),
            patch("napt.cli.list_mobile_apps", return_value=[]),
            patch("napt.cli.detect_drift", return_value=[]),
            patch("napt.cli.plan_promotions", return_value=actions),
            patch(
                "napt.cli.unresolvable_groups",
                return_value=[
                    "No Entra ID group found with displayName 'ghost-group'."
                ],
            ),
            patch("napt.cli.write_plan_files") as write_mock,
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=True,
                    reconcile=False,
                )
            )
        assert code == 1
        out = capsys.readouterr().out
        assert "Plan validation failed" in out
        assert "ghost-group" in out
        write_mock.assert_not_called()

    def test_offline_plan_skips_validation(self, tmp_path, capsys):
        """Tests that a plan without tenant flags never validates groups
        and that an empty plan draws no unvalidated warning."""
        with (
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.plan_promotions", return_value=[]),
            patch("napt.cli.write_plan_files", return_value=[]),
            patch("napt.cli.unresolvable_groups") as validate_mock,
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 0
        validate_mock.assert_not_called()
        assert "not validated" not in capsys.readouterr().out

    def test_offline_plan_with_actions_warns_unvalidated(self, tmp_path, capsys):
        """Tests that an offline plan producing actions warns that its
        groups were not validated."""
        actions = [
            {
                "type": "enter_ring",
                "app_id": "test-app",
                "version": "1.0.0",
                "sha256": "a" * 64,
                "ring": "pilot",
                "groups": ["sg-pilot"],
            }
        ]
        with (
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.plan_promotions", return_value=actions),
            patch("napt.cli.write_plan_files", return_value=["p"]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=False,
                    reconcile=False,
                )
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "Plan groups not validated against Entra ID" in out

    def test_plan_shares_one_session_for_reconcile_and_drift(self, tmp_path):
        """Tests that --reconcile --check-drift together authenticate and
        list the tenant only once."""
        with (
            patch("napt.cli.load_recipe_configs", return_value={}),
            patch("napt.cli.get_access_token", return_value="tok") as auth_mock,
            patch("napt.cli.list_mobile_apps", return_value=[]) as list_mock,
            patch("napt.cli.reconcile_publications", return_value=[]),
            patch("napt.cli.detect_drift", return_value=[]),
            patch("napt.cli.plan_promotions", return_value=[]),
            patch("napt.cli.write_plan_files", return_value=[]),
        ):
            code = cmd_promote_plan(
                _args(
                    recipes="recipes",
                    state_dir=tmp_path / "state",
                    check_drift=True,
                    reconcile=True,
                )
            )
        assert code == 0
        assert auth_mock.call_count == 1
        assert list_mock.call_count == 1

    def test_apply_prints_recovered_from_summary(self, tmp_path, capsys):
        """Tests that apply prints reconciliation findings from the summary."""
        summary = {
            "applied": [],
            "skipped": [],
            "failed": [],
            "drift": [],
            "recovered": [
                {
                    "app_id": "test-app",
                    "kind": "recovered",
                    "detail": "recorded publication of 2.0.0",
                }
            ],
        }
        with patch("napt.cli.apply_plan", return_value=summary):
            code = cmd_promote_apply(
                _args(recipes="recipes", state_dir=tmp_path, plan_file=None)
            )
        assert code == 0
        out = capsys.readouterr().out
        assert "PUBLICATION RECONCILIATION" in out
        assert "[OK] test-app: recorded publication of 2.0.0" in out
