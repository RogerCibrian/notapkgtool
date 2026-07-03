"""Tests for napt.upload.manager."""

from __future__ import annotations

import base64
import copy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from napt.config.defaults import DEFAULT_CONFIG
from napt.config.loader import _deep_merge_dicts
from napt.exceptions import NetworkError
from napt.upload.manager import _resolve_large_icon, upload_package
from tests.upload.conftest import make_package_dir


def _fake_config(
    app_id: str = "test-app",
    app_name: str = "Test App",
    build_types: str = "both",
) -> dict[str, Any]:
    return _deep_merge_dicts(
        copy.deepcopy(DEFAULT_CONFIG),
        {
            "id": app_id,
            "name": app_name,
            "intune": {"build_types": build_types},
        },
    )


def _patch_graph(
    install_app_id: str = "intune-app-123",
    update_app_id: str = "intune-update-456",
) -> dict:
    """Return patch kwargs for Graph API calls supporting one or two app uploads."""
    return {
        "create_win32_app": [install_app_id, update_app_id],
        "create_content_version": ["cv-1", "cv-2"],
        "create_content_version_file": [
            ("file-1", "https://sas1.example.com"),
            ("file-2", "https://sas2.example.com"),
        ],
    }


def test_upload_package_both_creates_two_apps(
    tmp_path: Path, monkeypatch, fake_metadata
) -> None:
    """Tests that build_types 'both' creates install and update app entries."""
    monkeypatch.chdir(tmp_path)
    make_package_dir(tmp_path)

    recipe_path = tmp_path / "recipes" / "Vendor" / "test-app.yaml"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.touch()

    patches = _patch_graph()

    with (
        patch(
            "napt.upload.manager.load_effective_config",
            return_value=_fake_config(build_types="both"),
        ),
        patch("napt.upload.manager.get_access_token", return_value="fake-token"),
        patch("napt.upload.manager.parse_intunewin", return_value=fake_metadata),
        patch(
            "napt.upload.manager.extract_encrypted_payload",
            return_value=tmp_path / "payload",
        ),
        patch(
            "napt.upload.manager.create_win32_app",
            side_effect=patches["create_win32_app"],
        ),
        patch(
            "napt.upload.manager.create_content_version",
            side_effect=patches["create_content_version"],
        ),
        patch(
            "napt.upload.manager.create_content_version_file",
            side_effect=patches["create_content_version_file"],
        ),
        patch("napt.upload.manager.upload_to_azure_blob"),
        patch("napt.upload.manager.commit_content_version_file"),
        patch("napt.upload.manager.commit_content_version"),
    ):
        result = upload_package(recipe_path)

    assert result.intune_app_id == "intune-app-123"
    assert result.intune_update_app_id == "intune-update-456"
    assert result.app_id == "test-app"
    assert result.app_name == "Test App"
    assert result.version == "1.0.0"
    assert result.status == "success"


def test_upload_package_app_only_creates_one_app(
    tmp_path: Path, monkeypatch, fake_metadata
) -> None:
    """Tests that build_types 'app_only' creates only the install app entry."""
    monkeypatch.chdir(tmp_path)
    make_package_dir(tmp_path)

    recipe_path = tmp_path / "recipes" / "Vendor" / "test-app.yaml"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.touch()

    with (
        patch(
            "napt.upload.manager.load_effective_config",
            return_value=_fake_config(build_types="app_only"),
        ),
        patch("napt.upload.manager.get_access_token", return_value="fake-token"),
        patch("napt.upload.manager.parse_intunewin", return_value=fake_metadata),
        patch(
            "napt.upload.manager.extract_encrypted_payload",
            return_value=tmp_path / "payload",
        ),
        patch("napt.upload.manager.create_win32_app", return_value="intune-app-123"),
        patch("napt.upload.manager.create_content_version", return_value="cv-1"),
        patch(
            "napt.upload.manager.create_content_version_file",
            return_value=("file-1", "https://sas.example.com"),
        ),
        patch("napt.upload.manager.upload_to_azure_blob"),
        patch("napt.upload.manager.commit_content_version_file"),
        patch("napt.upload.manager.commit_content_version"),
    ):
        result = upload_package(recipe_path)

    assert result.intune_app_id == "intune-app-123"
    assert result.intune_update_app_id is None
    assert result.status == "success"


def test_upload_package_update_only_creates_one_app(
    tmp_path: Path, monkeypatch, fake_metadata
) -> None:
    """Tests that build_types 'update_only' creates only the update app entry."""
    monkeypatch.chdir(tmp_path)
    make_package_dir(tmp_path)

    recipe_path = tmp_path / "recipes" / "Vendor" / "test-app.yaml"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.touch()

    with (
        patch(
            "napt.upload.manager.load_effective_config",
            return_value=_fake_config(build_types="update_only"),
        ),
        patch("napt.upload.manager.get_access_token", return_value="fake-token"),
        patch("napt.upload.manager.parse_intunewin", return_value=fake_metadata),
        patch(
            "napt.upload.manager.extract_encrypted_payload",
            return_value=tmp_path / "payload",
        ),
        patch("napt.upload.manager.create_win32_app", return_value="intune-update-456"),
        patch("napt.upload.manager.create_content_version", return_value="cv-1"),
        patch(
            "napt.upload.manager.create_content_version_file",
            return_value=("file-1", "https://sas.example.com"),
        ),
        patch("napt.upload.manager.upload_to_azure_blob"),
        patch("napt.upload.manager.commit_content_version_file"),
        patch("napt.upload.manager.commit_content_version"),
    ):
        result = upload_package(recipe_path)

    assert result.intune_app_id is None
    assert result.intune_update_app_id == "intune-update-456"
    assert result.status == "success"


def test_upload_package_propagates_network_error(
    tmp_path: Path, monkeypatch, fake_metadata
) -> None:
    """Tests that a NetworkError from the Graph API propagates out of upload_package."""
    monkeypatch.chdir(tmp_path)
    make_package_dir(tmp_path)

    recipe_path = tmp_path / "recipes" / "Vendor" / "test-app.yaml"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.touch()

    with (
        patch(
            "napt.upload.manager.load_effective_config",
            return_value=_fake_config(build_types="app_only"),
        ),
        patch("napt.upload.manager.get_access_token", return_value="fake-token"),
        patch("napt.upload.manager.parse_intunewin", return_value=fake_metadata),
        patch(
            "napt.upload.manager.create_win32_app",
            side_effect=NetworkError("Graph API down"),
        ),
    ):
        with pytest.raises(NetworkError, match="Graph API down"):
            upload_package(recipe_path)


class TestResolveLargeIcon:
    """Tests for _resolve_large_icon resolution order."""

    def test_logo_path_png(self, tmp_path, monkeypatch):
        """Tests that an existing logo_path PNG wins with the right MIME."""
        monkeypatch.chdir(tmp_path)
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"png data")
        config = _fake_config()
        config["intune"]["logo_path"] = str(logo)

        result = _resolve_large_icon(config)

        assert result == {
            "type": "image/png",
            "value": base64.b64encode(b"png data").decode(),
        }

    def test_logo_path_jpg_mime(self, tmp_path, monkeypatch):
        """Tests that a .jpg logo_path gets the image/jpeg MIME type."""
        monkeypatch.chdir(tmp_path)
        logo = tmp_path / "logo.jpg"
        logo.write_bytes(b"jpg data")
        config = _fake_config()
        config["intune"]["logo_path"] = str(logo)

        result = _resolve_large_icon(config)

        assert result is not None
        assert result["type"] == "image/jpeg"

    def test_missing_logo_path_falls_back_to_extracted(
        self, tmp_path, monkeypatch, capsys
    ):
        """Tests that a missing logo_path falls back to the extracted icon."""
        monkeypatch.chdir(tmp_path)
        icon_path = tmp_path / "icons" / "test-app.png"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_bytes(b"extracted png")
        config = _fake_config()
        config["intune"]["logo_path"] = str(tmp_path / "nope.png")

        result = _resolve_large_icon(config)

        assert result == {
            "type": "image/png",
            "value": base64.b64encode(b"extracted png").decode(),
        }
        assert "Logo file not found" in capsys.readouterr().out

    def test_unsupported_logo_type_falls_back(self, tmp_path, monkeypatch, capsys):
        """Tests that an unsupported logo_path file type warns and falls back."""
        monkeypatch.chdir(tmp_path)
        logo = tmp_path / "logo.gif"
        logo.write_bytes(b"gif data")
        icon_path = tmp_path / "icons" / "test-app.png"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_bytes(b"extracted png")
        config = _fake_config()
        config["intune"]["logo_path"] = str(logo)

        result = _resolve_large_icon(config)

        assert result is not None
        assert result["type"] == "image/png"
        assert "Unsupported logo file type" in capsys.readouterr().out

    def test_extracted_icon_used_when_no_logo_path(self, tmp_path, monkeypatch):
        """Tests that the extracted icon is used when logo_path is unset."""
        monkeypatch.chdir(tmp_path)
        icon_path = tmp_path / "icons" / "test-app.png"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_bytes(b"extracted png")

        result = _resolve_large_icon(_fake_config())

        assert result == {
            "type": "image/png",
            "value": base64.b64encode(b"extracted png").decode(),
        }

    def test_no_icon_warns_and_returns_none(self, tmp_path, monkeypatch, capsys):
        """Tests that no available icon warns once with actionable remedies."""
        monkeypatch.chdir(tmp_path)

        result = _resolve_large_icon(_fake_config())

        output = capsys.readouterr().out
        assert result is None
        assert "No app icon found for 'test-app'" in output
        assert "napt build" in output
        assert "intune.logo_path" in output

    def test_broken_logo_path_without_extracted_icon_warns_accurately(
        self, tmp_path, monkeypatch, capsys
    ):
        """Tests that a broken logo_path with no extracted icon says so."""
        monkeypatch.chdir(tmp_path)
        config = _fake_config()
        config["intune"]["logo_path"] = str(tmp_path / "nope.png")

        result = _resolve_large_icon(config)

        output = capsys.readouterr().out
        assert result is None
        assert "Logo file not found" in output
        assert "will have no logo" in output
        assert "fix intune.logo_path" in output
        # No misleading fallback claim and no duplicate generic warning
        assert "Falling back" not in output
        assert "No app icon found" not in output

    def test_oversized_logo_path_warns_and_skips(self, tmp_path, monkeypatch, capsys):
        """Tests that a logo_path file over the size limit is skipped."""
        from napt.build.icons import MAX_ICON_BYTES

        monkeypatch.chdir(tmp_path)
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"x" * (MAX_ICON_BYTES + 1))
        config = _fake_config()
        config["intune"]["logo_path"] = str(logo)

        result = _resolve_large_icon(config)

        output = capsys.readouterr().out
        assert result is None
        assert "icon size limit" in output

    def test_oversized_extracted_icon_warns_and_returns_none(
        self, tmp_path, monkeypatch, capsys
    ):
        """Tests that an oversized curated icon warns instead of uploading."""
        from napt.build.icons import MAX_ICON_BYTES

        monkeypatch.chdir(tmp_path)
        icon_path = tmp_path / "icons" / "test-app.png"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_bytes(b"x" * (MAX_ICON_BYTES + 1))

        result = _resolve_large_icon(_fake_config())

        output = capsys.readouterr().out
        assert result is None
        assert "icon size limit" in output

    def test_unreadable_extracted_icon_warns_and_returns_none(
        self, tmp_path, monkeypatch, capsys
    ):
        """Tests that an unreadable icon file warns instead of crashing."""
        monkeypatch.chdir(tmp_path)
        # A directory at the icon path passes exists() but fails read_bytes()
        (tmp_path / "icons" / "test-app.png").mkdir(parents=True)

        result = _resolve_large_icon(_fake_config())

        output = capsys.readouterr().out
        assert result is None
        assert "Could not read icon file" in output


def test_upload_package_both_shares_icon_across_entries(
    tmp_path: Path, monkeypatch, fake_metadata
) -> None:
    """Tests that both app entries get the same largeIcon payload."""
    monkeypatch.chdir(tmp_path)
    make_package_dir(tmp_path)
    icon_path = tmp_path / "icons" / "test-app.png"
    icon_path.parent.mkdir(parents=True)
    icon_path.write_bytes(b"extracted png")

    recipe_path = tmp_path / "recipes" / "Vendor" / "test-app.yaml"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.touch()

    patches = _patch_graph()
    create_app_mock = MagicMock(side_effect=patches["create_win32_app"])

    with (
        patch(
            "napt.upload.manager.load_effective_config",
            return_value=_fake_config(build_types="both"),
        ),
        patch("napt.upload.manager.get_access_token", return_value="fake-token"),
        patch("napt.upload.manager.parse_intunewin", return_value=fake_metadata),
        patch(
            "napt.upload.manager.extract_encrypted_payload",
            return_value=tmp_path / "payload",
        ),
        patch("napt.upload.manager.create_win32_app", create_app_mock),
        patch(
            "napt.upload.manager.create_content_version",
            side_effect=patches["create_content_version"],
        ),
        patch(
            "napt.upload.manager.create_content_version_file",
            side_effect=patches["create_content_version_file"],
        ),
        patch("napt.upload.manager.upload_to_azure_blob"),
        patch("napt.upload.manager.commit_content_version_file"),
        patch("napt.upload.manager.commit_content_version"),
    ):
        upload_package(recipe_path)

    expected_icon = {
        "type": "image/png",
        "value": base64.b64encode(b"extracted png").decode(),
    }
    assert create_app_mock.call_count == 2
    for call in create_app_mock.call_args_list:
        payload = call.args[1]
        assert payload["largeIcon"] == expected_icon
