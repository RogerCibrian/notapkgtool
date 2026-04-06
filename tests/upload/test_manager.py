"""Tests for napt.upload.manager."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from napt.exceptions import NetworkError
from napt.upload.manager import upload_package
from tests.upload.conftest import make_package_dir


def _fake_config(
    app_id: str = "test-app",
    app_name: str = "Test App",
    build_types: str = "both",
) -> dict[str, Any]:
    return {
        "id": app_id,
        "name": app_name,
        "intune": {
            "build_types": build_types,
            "device_restart_behavior": "basedOnReturnCode",
        },
    }


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
