"""Tests for napt.upload.graph."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import requests_mock as req_mock

from napt.exceptions import ConfigError, NetworkError
from napt.upload.graph import (
    GRAPH_BASE,
    commit_content_version,
    commit_content_version_file,
    create_content_version,
    create_content_version_file,
    create_win32_app,
    upload_to_azure_blob,
)

TOKEN = "fake-token"
APP_ID = "app-id-123"
CV_ID = "cv-id-456"
FILE_ID = "file-id-789"
SAS_URI = "https://blob.example.com/test?sv=sig"

_APPS_URL = f"{GRAPH_BASE}/deviceAppManagement/mobileApps"
_CV_URL = (
    f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{APP_ID}"
    f"/microsoft.graph.win32LobApp/contentVersions"
)
_FILES_URL = f"{_CV_URL}/{CV_ID}/files"
_FILE_POLL_URL = f"{_FILES_URL}/{FILE_ID}"
_COMMIT_FILE_URL = f"{_FILE_POLL_URL}/commit"
_APP_URL = f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{APP_ID}"


# --- create_win32_app ---


def test_create_win32_app_returns_app_id() -> None:
    """Tests that create_win32_app returns the app ID from the API response."""
    with req_mock.Mocker() as m:
        m.post(_APPS_URL, json={"id": APP_ID}, status_code=201)
        result = create_win32_app(TOKEN, {"displayName": "Test App"})

    assert result == APP_ID


def test_create_win32_app_400_raises_config_error() -> None:
    """Tests that a 400 response raises ConfigError."""
    with req_mock.Mocker() as m:
        m.post(_APPS_URL, json={"error": "bad request"}, status_code=400)
        with pytest.raises(ConfigError):
            create_win32_app(TOKEN, {})


# --- create_content_version ---


def test_create_content_version_returns_cv_id() -> None:
    """Tests that create_content_version returns the content version ID."""
    with req_mock.Mocker() as m:
        m.post(_CV_URL, json={"id": CV_ID}, status_code=201)
        result = create_content_version(TOKEN, APP_ID)

    assert result == CV_ID


def test_create_content_version_500_raises_network_error() -> None:
    """Tests that a 500 response raises NetworkError."""
    with req_mock.Mocker() as m:
        m.post(_CV_URL, json={}, status_code=500)
        with pytest.raises(NetworkError):
            create_content_version(TOKEN, APP_ID)


# --- create_content_version_file ---


def test_create_content_version_file_returns_file_id_and_sas_uri(
    fake_metadata,
) -> None:
    """Tests that create_content_version_file returns (file_id, sas_uri) after polling."""
    with req_mock.Mocker() as m:
        m.post(_FILES_URL, json={"id": FILE_ID}, status_code=201)
        m.get(
            _FILE_POLL_URL,
            [
                {
                    "json": {"uploadState": "azureStorageUriRequestPending"},
                    "status_code": 200,
                },
                {
                    "json": {
                        "uploadState": "azureStorageUriRequestSuccess",
                        "azureStorageUri": SAS_URI,
                    },
                    "status_code": 200,
                },
            ],
        )
        with patch("napt.upload.graph.time.sleep"):
            file_id, sas_uri = create_content_version_file(
                TOKEN, APP_ID, CV_ID, fake_metadata
            )

    assert file_id == FILE_ID
    assert sas_uri == SAS_URI


def test_create_content_version_file_error_state_raises_network_error(
    fake_metadata,
) -> None:
    """Tests that an error uploadState during polling raises NetworkError."""
    with req_mock.Mocker() as m:
        m.post(_FILES_URL, json={"id": FILE_ID}, status_code=201)
        m.get(
            _FILE_POLL_URL,
            json={"uploadState": "azureStorageUriRequestError"},
            status_code=200,
        )
        with patch("napt.upload.graph.time.sleep"):
            with pytest.raises(NetworkError, match="error state"):
                create_content_version_file(TOKEN, APP_ID, CV_ID, fake_metadata)


# --- upload_to_azure_blob ---


def test_upload_to_azure_blob_uploads_blocks_and_commits(tmp_path: Path) -> None:
    """Tests that upload_to_azure_blob PUTs all blocks then commits the block list."""
    payload = tmp_path / "IntunePackage.intunewin"
    payload.write_bytes(b"fake payload data for block upload test")

    with req_mock.Mocker() as m:
        m.put(req_mock.ANY, status_code=201)
        upload_to_azure_blob(SAS_URI, payload)

    # At least one block PUT + one block list PUT
    assert m.call_count >= 2


def test_upload_to_azure_blob_block_failure_raises_network_error(
    tmp_path: Path,
) -> None:
    """Tests that a failed block PUT raises NetworkError."""
    payload = tmp_path / "payload.intunewin"
    payload.write_bytes(b"data")

    with req_mock.Mocker() as m:
        m.put(req_mock.ANY, status_code=500)
        with pytest.raises(NetworkError, match="block upload failed"):
            upload_to_azure_blob(SAS_URI, payload)


# --- commit_content_version_file ---


def test_commit_content_version_file_polls_until_committed(fake_metadata) -> None:
    """Tests that commit_content_version_file posts commit then polls for success."""
    with req_mock.Mocker() as m:
        m.post(_COMMIT_FILE_URL, json={}, status_code=200)
        m.get(
            _FILE_POLL_URL,
            json={"uploadState": "commitFileSuccess"},
            status_code=200,
        )
        with patch("napt.upload.graph.time.sleep"):
            commit_content_version_file(TOKEN, APP_ID, CV_ID, FILE_ID, fake_metadata)


def test_commit_content_version_file_error_state_raises_network_error(
    fake_metadata,
) -> None:
    """Tests that a failed commit uploadState raises NetworkError."""
    with req_mock.Mocker() as m:
        m.post(_COMMIT_FILE_URL, json={}, status_code=200)
        m.get(
            _FILE_POLL_URL,
            json={"uploadState": "commitFileFailed"},
            status_code=200,
        )
        with patch("napt.upload.graph.time.sleep"):
            with pytest.raises(NetworkError, match="error state"):
                commit_content_version_file(
                    TOKEN, APP_ID, CV_ID, FILE_ID, fake_metadata
                )


# --- commit_content_version ---


def test_commit_content_version_patches_app() -> None:
    """Tests that commit_content_version sends a PATCH to the app endpoint."""
    with req_mock.Mocker() as m:
        m.patch(_APP_URL, json={}, status_code=204)
        commit_content_version(TOKEN, APP_ID, CV_ID)


def test_commit_content_version_500_raises_network_error() -> None:
    """Tests that a 500 from commit_content_version raises NetworkError."""
    with req_mock.Mocker() as m:
        m.patch(_APP_URL, json={}, status_code=500)
        with pytest.raises(NetworkError):
            commit_content_version(TOKEN, APP_ID, CV_ID)
