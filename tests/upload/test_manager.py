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
    app_id: str = "test-app", app_name: str = "Test App"
) -> dict[str, Any]:
    return {
        "id": app_id,
        "name": app_name,
        "intune": {},
    }


def test_upload_package_returns_upload_result(
    tmp_path: Path, monkeypatch, fake_metadata
) -> None:
    """Tests that upload_package orchestrates the full pipeline and returns UploadResult."""
    monkeypatch.chdir(tmp_path)
    make_package_dir(tmp_path)

    recipe_path = tmp_path / "recipes" / "Vendor" / "test-app.yaml"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.touch()

    with (
        patch(
            "napt.upload.manager.load_effective_config",
            return_value=_fake_config(),
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
    assert result.app_id == "test-app"
    assert result.app_name == "Test App"
    assert result.version == "1.0.0"
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
            return_value=_fake_config(),
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
