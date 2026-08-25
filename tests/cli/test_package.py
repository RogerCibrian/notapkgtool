"""Tests for napt.cli.package."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from napt.cli.package import _resolve_build_dir_from_recipe, cmd_package
from napt.exceptions import ConfigError, PackagingError
from tests.cli.conftest import _args, _mock_result


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
            "napt.cli.package._resolve_build_dir_from_recipe",
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
        with patch(
            "napt.cli.package._resolve_build_dir_from_recipe", return_value=build_dir
        ):
            with patch(
                "napt.cli.package.load_effective_config", return_value=mock_config
            ):
                with patch(
                    "napt.cli.package.create_intunewin", return_value=mock_result
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
        with patch(
            "napt.cli.package._resolve_build_dir_from_recipe", return_value=build_dir
        ):
            with patch(
                "napt.cli.package.load_effective_config", return_value=mock_config
            ):
                with patch(
                    "napt.cli.package.create_intunewin", return_value=mock_result
                ):
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
        with patch(
            "napt.cli.package._resolve_build_dir_from_recipe", return_value=build_dir
        ):
            with patch(
                "napt.cli.package.load_effective_config", return_value=mock_config
            ):
                with patch(
                    "napt.cli.package.create_intunewin",
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
        with patch(
            "napt.cli.package._resolve_build_dir_from_recipe", return_value=build_dir
        ):
            with patch(
                "napt.cli.package.load_effective_config", return_value=mock_config
            ):
                with patch(
                    "napt.cli.package.create_intunewin", return_value=mock_result
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
        with patch("napt.cli.package.load_effective_config", return_value=mock_config):
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
        with patch("napt.cli.package.load_effective_config", return_value=mock_config):
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
        with patch("napt.cli.package.load_effective_config", return_value=mock_config):
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
        with patch("napt.cli.package.load_effective_config", return_value=mock_config):
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
        with patch("napt.cli.package.load_effective_config", return_value=mock_config):
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
        with patch("napt.cli.package.load_effective_config", return_value=mock_config):
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
        with patch("napt.cli.package.load_effective_config", return_value=mock_config):
            result = _resolve_build_dir_from_recipe(recipe, builds_dir=custom_builds)
        assert result == app_ver_dir
