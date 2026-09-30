"""Tests for napt.cli.package."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from napt.cli.package import _resolve_build, cmd_package
from napt.exceptions import ConfigError, PackagingError
from napt.state.deployment import (
    create_default_deployment_state,
    deployment_state_path,
    save_deployment_state,
)
from tests.cli.conftest import _args, _mock_result

_MOCK_CONFIG = {
    "directories": {"package": "packages"},
    "intunewin": {"release": "latest"},
}


def _package_args(recipe, **overrides):
    defaults = {
        "recipe": str(recipe),
        "version": None,
        "builds_dir": None,
        "output_dir": None,
        "state_dir": None,
    }
    defaults.update(overrides)
    return _args(**defaults)


class TestCmdPackage:
    """Tests for cmd_package handler."""

    def test_missing_recipe_returns_one(self, tmp_path, capsys):
        """Tests that a missing recipe file exits with code 1."""
        code = cmd_package(_package_args(tmp_path / "nonexistent.yaml"))
        assert code == 1

    def test_resolve_config_error_returns_one(self, tmp_path, capsys):
        """Tests that ConfigError from _resolve_build returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        with patch(
            "napt.cli.package._resolve_build",
            side_effect=ConfigError("no builds found"),
        ):
            code = cmd_package(_package_args(recipe))
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
        with (
            patch("napt.cli.package._resolve_build", return_value=(build_dir, None)),
            patch("napt.cli.package.load_effective_config", return_value=_MOCK_CONFIG),
            patch("napt.cli.package.create_intunewin", return_value=mock_result),
        ):
            code = cmd_package(_package_args(recipe))
        assert code == 0
        assert "[SUCCESS]" in capsys.readouterr().out

    def test_expected_hash_is_forwarded(self, tmp_path):
        """Tests that the hash of the recorded release reaches create_intunewin."""
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
        with (
            patch(
                "napt.cli.package._resolve_build", return_value=(build_dir, "c" * 64)
            ),
            patch("napt.cli.package.load_effective_config", return_value=_MOCK_CONFIG),
            patch(
                "napt.cli.package.create_intunewin", return_value=mock_result
            ) as mock_create,
        ):
            cmd_package(_package_args(recipe))
        assert mock_create.call_args.kwargs["expected_sha256"] == "c" * 64

    def test_packaging_error_returns_one(self, tmp_path, capsys):
        """Tests that PackagingError from create_intunewin returns 1."""
        recipe = tmp_path / "recipe.yaml"
        recipe.touch()
        build_dir = tmp_path / "build"
        with (
            patch("napt.cli.package._resolve_build", return_value=(build_dir, None)),
            patch("napt.cli.package.load_effective_config", return_value=_MOCK_CONFIG),
            patch(
                "napt.cli.package.create_intunewin",
                side_effect=PackagingError("pack fail"),
            ),
        ):
            code = cmd_package(_package_args(recipe))
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
        with (
            patch("napt.cli.package._resolve_build", return_value=(build_dir, None)),
            patch("napt.cli.package.load_effective_config", return_value=_MOCK_CONFIG),
            patch(
                "napt.cli.package.create_intunewin", return_value=mock_result
            ) as mock_create,
        ):
            cmd_package(_package_args(recipe, output_dir=str(custom_out)))
        _, kwargs = mock_create.call_args
        assert kwargs["output_dir"] == custom_out


def _build(builds_dir, version: str):
    """Creates a completed build folder for test-app."""
    version_dir = builds_dir / "test-app" / version
    (version_dir / "packagefiles").mkdir(parents=True)
    return version_dir


def _record(state_dir, **sections):
    """Writes test-app's deployment state with the given sections."""
    state = create_default_deployment_state()
    state.update(sections)
    save_deployment_state(
        state, deployment_state_path(state_dir / "deployment", "test-app")
    )


class TestResolveBuild:
    """Tests for choosing which build to package."""

    @pytest.fixture
    def config(self, tmp_path):
        mock_config = {
            "id": "test-app",
            "directories": {
                "build": str(tmp_path / "builds"),
                "state": str(tmp_path / "state"),
            },
        }
        with patch("napt.cli.package.load_effective_config", return_value=mock_config):
            yield mock_config

    def test_no_app_build_dir_raises(self, tmp_path, config):
        """Tests that missing app build directory raises ConfigError."""
        with pytest.raises(ConfigError, match="No builds found"):
            _resolve_build(tmp_path / "recipe.yaml")

    def test_specific_version_found(self, tmp_path, config):
        """Tests that a specific version directory is returned when it exists."""
        version_dir = _build(tmp_path / "builds", "1.2.3")

        build_dir, expected = _resolve_build(tmp_path / "recipe.yaml", version="1.2.3")

        assert build_dir == version_dir
        assert expected is None

    def test_specific_version_matching_state_carries_its_hash(self, tmp_path, config):
        """Tests that an explicit version that is the recorded release is
        still verified against it."""
        version_dir = _build(tmp_path / "builds", "1.2.3")
        _record(tmp_path / "state", pending={"version": "1.2.3", "sha256": "c" * 64})

        build_dir, expected = _resolve_build(tmp_path / "recipe.yaml", version="1.2.3")

        assert build_dir == version_dir
        assert expected == "c" * 64

    def test_specific_version_missing_raises(self, tmp_path, config):
        """Tests that a missing specific version raises ConfigError."""
        (tmp_path / "builds" / "test-app").mkdir(parents=True)

        with pytest.raises(ConfigError, match="not found"):
            _resolve_build(tmp_path / "recipe.yaml", version="9.9.9")

    def test_specific_version_without_packagefiles_raises(self, tmp_path, config):
        """Tests that a version dir without packagefiles/ raises ConfigError."""
        (tmp_path / "builds" / "test-app" / "1.2.3").mkdir(parents=True)

        with pytest.raises(ConfigError, match="not found"):
            _resolve_build(tmp_path / "recipe.yaml", version="1.2.3")

    def test_pending_release_selected_over_newer_folder(self, tmp_path, config):
        """Tests that the recorded pending release wins, not the folder that
        was modified last."""
        old_dir = _build(tmp_path / "builds", "1.0.0")
        new_dir = _build(tmp_path / "builds", "2.0.0")
        os.utime(old_dir, (time.time() - 100, time.time() - 100))
        os.utime(new_dir, (time.time(), time.time()))
        _record(tmp_path / "state", pending={"version": "1.0.0", "sha256": "a" * 64})

        build_dir, expected = _resolve_build(tmp_path / "recipe.yaml")

        assert build_dir == old_dir
        assert expected == "a" * 64

    def test_published_release_selected_when_nothing_pending(self, tmp_path, config):
        """Tests that a rebuild of the current release packages that release."""
        _build(tmp_path / "builds", "1.0.0")
        _build(tmp_path / "builds", "2.0.0")
        _record(tmp_path / "state", published={"version": "2.0.0", "sha256": "b" * 64})

        build_dir, expected = _resolve_build(tmp_path / "recipe.yaml")

        assert build_dir.name == "2.0.0"
        assert expected == "b" * 64

    def test_recorded_release_without_build_raises(self, tmp_path, config):
        """Tests that a recorded release that was never built says so."""
        _build(tmp_path / "builds", "1.0.0")
        _record(tmp_path / "state", pending={"version": "2.0.0", "sha256": "b" * 64})

        with pytest.raises(ConfigError, match="2.0.0") as info:
            _resolve_build(tmp_path / "recipe.yaml")
        assert "napt build" in str(info.value)

    def test_single_build_without_state_is_used(self, tmp_path, config):
        """Tests that with no recorded release the only build is unambiguous."""
        version_dir = _build(tmp_path / "builds", "1.0.0")

        build_dir, expected = _resolve_build(tmp_path / "recipe.yaml")

        assert build_dir == version_dir
        assert expected is None

    def test_several_builds_without_state_need_a_version(self, tmp_path, config):
        """Tests that several builds and no recorded release is an error
        naming the versions, never a guess by modification time."""
        _build(tmp_path / "builds", "1.0.0")
        _build(tmp_path / "builds", "2.0.0")

        with pytest.raises(ConfigError, match="--version") as info:
            _resolve_build(tmp_path / "recipe.yaml")
        assert "1.0.0" in str(info.value)
        assert "2.0.0" in str(info.value)

    def test_no_completed_builds_raises(self, tmp_path, config):
        """Tests that app dir with no packagefiles/ subdirs raises ConfigError."""
        (tmp_path / "builds" / "test-app" / "1.0.0").mkdir(parents=True)

        with pytest.raises(ConfigError, match="No completed builds"):
            _resolve_build(tmp_path / "recipe.yaml")

    def test_custom_builds_dir_overrides_config(self, tmp_path, config):
        """Tests that an explicit builds_dir overrides the config directory."""
        custom_builds = tmp_path / "custom_builds"
        version_dir = _build(custom_builds, "3.0.0")

        build_dir, _ = _resolve_build(
            tmp_path / "recipe.yaml", builds_dir=custom_builds
        )

        assert build_dir == version_dir

    def test_custom_state_dir_overrides_config(self, tmp_path, config):
        """Tests that --state-dir names the state root the release is read from."""
        old_dir = _build(tmp_path / "builds", "1.0.0")
        _build(tmp_path / "builds", "2.0.0")
        _record(tmp_path / "other", pending={"version": "1.0.0", "sha256": "a" * 64})

        build_dir, _ = _resolve_build(
            tmp_path / "recipe.yaml", state_dir=tmp_path / "other"
        )

        assert build_dir == old_dir
