"""Tests for napt.upload.graph."""

from __future__ import annotations

from pathlib import Path
import time
from unittest.mock import patch

import pytest
import requests
import requests_mock as req_mock

from napt.exceptions import ConfigError, NetworkError
from napt.upload.graph import (
    GRAPH_BASE,
    _auth_headers,
    _graph_request,
    assign_app,
    build_group_assignment,
    commit_content_version,
    commit_content_version_file,
    create_content_version,
    create_content_version_file,
    create_win32_app,
    delete_mobile_app,
    get_app_assignments,
    get_mobile_app,
    list_mobile_apps,
    resolve_group_id,
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
    """Tests that a persistent 500 raises NetworkError after retries."""
    with req_mock.Mocker() as m:
        m.post(_CV_URL, json={}, status_code=500)
        with patch("napt.upload.graph.time.sleep"):
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
    """Tests that a persistently failing block PUT raises NetworkError
    after exhausting retries."""
    payload = tmp_path / "payload.intunewin"
    payload.write_bytes(b"data")

    with req_mock.Mocker() as m:
        m.put(req_mock.ANY, status_code=500)
        with patch("napt.upload.graph.time.sleep"):
            with pytest.raises(NetworkError, match="block upload failed"):
                upload_to_azure_blob(SAS_URI, payload)

    assert m.call_count == 5


def test_upload_to_azure_blob_retries_transient_403(tmp_path: Path) -> None:
    """Tests that a transient 403 from a not-yet-propagated SAS URI is
    retried and the upload succeeds."""
    payload = tmp_path / "payload.intunewin"
    payload.write_bytes(b"data")

    with req_mock.Mocker() as m:
        m.put(
            req_mock.ANY,
            [
                {"text": "SAS identifier cannot be found", "status_code": 403},
                {"status_code": 201},
                {"status_code": 201},
            ],
        )
        with patch("napt.upload.graph.time.sleep"):
            upload_to_azure_blob(SAS_URI, payload)

    # One failed block PUT + its retry + the block list commit
    assert m.call_count == 3


def test_upload_to_azure_blob_non_retryable_status_fails_fast(
    tmp_path: Path,
) -> None:
    """Tests that a non-retryable HTTP status raises immediately without
    retrying."""
    payload = tmp_path / "payload.intunewin"
    payload.write_bytes(b"data")

    with req_mock.Mocker() as m:
        m.put(req_mock.ANY, status_code=400)
        with patch("napt.upload.graph.time.sleep"):
            with pytest.raises(NetworkError, match="block upload failed"):
                upload_to_azure_blob(SAS_URI, payload)

    assert m.call_count == 1


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
    """Tests that a persistent 500 raises NetworkError after retries."""
    with req_mock.Mocker() as m:
        m.patch(_APP_URL, json={}, status_code=500)
        with patch("napt.upload.graph.time.sleep"):
            with pytest.raises(NetworkError):
                commit_content_version(TOKEN, APP_ID, CV_ID)


# --- _graph_request retry behavior ---


def test_graph_request_retries_429_honoring_retry_after() -> None:
    """Tests that a throttled call waits per Retry-After and succeeds."""
    body = {"id": APP_ID}
    with req_mock.Mocker() as m:
        m.get(
            _APP_URL,
            [
                {"status_code": 429, "headers": {"Retry-After": "7"}},
                {"json": body, "status_code": 200},
            ],
        )
        with patch("napt.upload.graph.time.sleep") as sleep_mock:
            result = get_mobile_app(TOKEN, APP_ID)

    assert result == body
    assert len(m.request_history) == 2
    assert sleep_mock.call_args.args[0] == 7.0


def test_graph_request_retries_transient_500() -> None:
    """Tests that a transient 500 retries with backoff and succeeds."""
    body = {"id": APP_ID}
    with req_mock.Mocker() as m:
        m.get(_APP_URL, [{"status_code": 503}, {"json": body, "status_code": 200}])
        with patch("napt.upload.graph.time.sleep") as sleep_mock:
            result = get_mobile_app(TOKEN, APP_ID)

    assert result == body
    assert sleep_mock.call_args.args[0] == 2.0  # initial backoff, no Retry-After


def test_graph_request_exhausts_attempts() -> None:
    """Tests that persistent throttling raises after bounded attempts."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=429)
        with patch("napt.upload.graph.time.sleep"):
            with pytest.raises(NetworkError):
                get_mobile_app(TOKEN, APP_ID)

    assert len(m.request_history) == 5


def test_graph_request_non_retryable_fails_fast() -> None:
    """Tests that a 400 raises immediately without retrying."""
    with req_mock.Mocker() as m:
        m.post(_APPS_URL, json={"error": "bad"}, status_code=400)
        with patch("napt.upload.graph.time.sleep") as sleep_mock:
            with pytest.raises(ConfigError):
                create_win32_app(TOKEN, {})

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_graph_request_retries_connection_error() -> None:
    """Tests that a connection-level failure retries and succeeds."""
    body = {"id": APP_ID}
    with req_mock.Mocker() as m:
        m.get(
            _APP_URL,
            [
                {"exc": requests.exceptions.ConnectionError},
                {"json": body, "status_code": 200},
            ],
        )
        with patch("napt.upload.graph.time.sleep"):
            result = get_mobile_app(TOKEN, APP_ID)

    assert result == body


def test_graph_request_retries_509_bandwidth_throttle() -> None:
    """Tests that a 509 bandwidth throttle is retried."""
    body = {"id": APP_ID}
    with req_mock.Mocker() as m:
        m.get(_APP_URL, [{"status_code": 509}, {"json": body, "status_code": 200}])
        with patch("napt.upload.graph.time.sleep"):
            result = get_mobile_app(TOKEN, APP_ID)

    assert result == body


def test_graph_request_sends_client_request_id() -> None:
    """Tests that every request carries a client-request-id header."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, json={"id": APP_ID})
        get_mobile_app(TOKEN, APP_ID)

    assert m.request_history[0].headers["client-request-id"]


def test_delete_mobile_app_tolerates_404() -> None:
    """Tests that deleting an already-gone app is a no-op, not a retry."""
    with req_mock.Mocker() as m:
        m.delete(_APP_URL, status_code=404)
        with patch("napt.upload.graph.time.sleep") as sleep_mock:
            delete_mobile_app(TOKEN, APP_ID)

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_create_connection_error_fails_fast() -> None:
    """Tests that a create POST never retries a connection failure."""
    with req_mock.Mocker() as m:
        m.post(_APPS_URL, exc=requests.exceptions.ConnectionError)
        with patch("napt.upload.graph.time.sleep") as sleep_mock:
            with pytest.raises(NetworkError):
                create_win32_app(TOKEN, {"displayName": "Test App"})

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_create_ambiguous_gateway_error_fails_fast() -> None:
    """Tests that a create POST never retries an ambiguous 502."""
    with req_mock.Mocker() as m:
        m.post(_APPS_URL, status_code=502)
        with patch("napt.upload.graph.time.sleep") as sleep_mock:
            with pytest.raises(NetworkError):
                create_win32_app(TOKEN, {"displayName": "Test App"})

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_create_retries_throttle() -> None:
    """Tests that a create POST retries an unambiguous 429 throttle."""
    with req_mock.Mocker() as m:
        m.post(
            _APPS_URL,
            [
                {"status_code": 429, "headers": {"Retry-After": "3"}},
                {"json": {"id": APP_ID}, "status_code": 201},
            ],
        )
        with patch("napt.upload.graph.time.sleep") as sleep_mock:
            result = create_win32_app(TOKEN, {"displayName": "Test App"})

    assert result == APP_ID
    assert sleep_mock.call_args.args[0] == 3.0


def test_graph_request_deadline_stops_retries() -> None:
    """Tests that an exhausted deadline surfaces the failure unslept."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=429, headers={"Retry-After": "60"})
        with patch("napt.upload.graph.time.sleep") as sleep_mock:
            with pytest.raises(NetworkError):
                _graph_request(
                    "GET",
                    _APP_URL,
                    "deadline test",
                    headers=_auth_headers(TOKEN),
                    deadline=time.monotonic() + 1.0,
                )

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


# --- list_mobile_apps / get_mobile_app ---


def test_list_mobile_apps_single_page() -> None:
    """Tests that a single page of apps is returned."""
    apps = [{"id": "1", "displayName": "A", "notes": None}]
    with req_mock.Mocker() as m:
        m.get(_APPS_URL, json={"value": apps})
        result = list_mobile_apps(TOKEN)

    assert result == apps


def test_list_mobile_apps_follows_pagination() -> None:
    """Tests that @odata.nextLink pages are followed and merged."""
    page1 = {
        "value": [{"id": "1"}],
        "@odata.nextLink": f"{_APPS_URL}?$skiptoken=abc",
    }
    page2 = {"value": [{"id": "2"}]}
    with req_mock.Mocker() as m:
        m.get(_APPS_URL, [{"json": page1}, {"json": page2}])
        result = list_mobile_apps(TOKEN)

    assert [a["id"] for a in result] == ["1", "2"]


def test_get_mobile_app_returns_full_object() -> None:
    """Tests that get_mobile_app returns the app body."""
    body = {"id": APP_ID, "committedContentVersion": "1"}
    with req_mock.Mocker() as m:
        m.get(_APP_URL, json=body)
        result = get_mobile_app(TOKEN, APP_ID)

    assert result == body


# --- resolve_group_id / assignments ---

GROUP_ID = "12345678-abcd-4bed-b834-2a9ef5879619"
_GROUPS_URL = f"{GRAPH_BASE}/groups"
_ASSIGNMENTS_URL = f"{_APP_URL}/assignments"
_ASSIGN_URL = f"{_APP_URL}/assign"


def test_resolve_group_id_guid_passes_through() -> None:
    """Tests that an object ID is returned without a Graph call."""
    assert resolve_group_id(TOKEN, GROUP_ID) == GROUP_ID


def test_resolve_group_id_looks_up_name() -> None:
    """Tests that a single displayName match resolves to its object ID."""
    with req_mock.Mocker() as m:
        m.get(_GROUPS_URL, json={"value": [{"id": GROUP_ID, "displayName": "Pilot"}]})
        assert resolve_group_id(TOKEN, "Pilot") == GROUP_ID


def test_resolve_group_id_no_match_raises() -> None:
    """Tests that an unknown group name raises ConfigError."""
    with req_mock.Mocker() as m:
        m.get(_GROUPS_URL, json={"value": []})
        with pytest.raises(ConfigError, match="No Entra ID group found"):
            resolve_group_id(TOKEN, "Nope")


def test_resolve_group_id_ambiguous_raises() -> None:
    """Tests that multiple matches raise ConfigError."""
    with req_mock.Mocker() as m:
        m.get(
            _GROUPS_URL,
            json={"value": [{"id": "a"}, {"id": "b"}]},
        )
        with pytest.raises(ConfigError, match="Multiple Entra ID groups"):
            resolve_group_id(TOKEN, "Pilot")


def test_resolve_group_id_escapes_quotes() -> None:
    """Tests that single quotes in group names are escaped in the filter."""
    with req_mock.Mocker() as m:
        m.get(_GROUPS_URL, json={"value": [{"id": GROUP_ID}]})
        resolve_group_id(TOKEN, "O'Brien's Group")
        # OData escapes each ' as '' in the filter expression
        assert "O''Brien''s" in m.request_history[0].url


def test_get_app_assignments_returns_value() -> None:
    """Tests that assignments are returned from the value array."""
    assignments = [{"id": "a1", "intent": "required"}]
    with req_mock.Mocker() as m:
        m.get(_ASSIGNMENTS_URL, json={"value": assignments})
        assert get_app_assignments(TOKEN, APP_ID) == assignments


def test_assign_app_posts_full_set() -> None:
    """Tests that assign_app posts the complete assignment list."""
    assignments = [build_group_assignment(GROUP_ID, "required")]
    with req_mock.Mocker() as m:
        m.post(_ASSIGN_URL, status_code=200)
        assign_app(TOKEN, APP_ID, assignments)
        body = m.request_history[0].json()
    assert body == {"mobileAppAssignments": assignments}


def test_build_group_assignment_shape() -> None:
    """Tests the mobileAppAssignment payload structure."""
    result = build_group_assignment(GROUP_ID, "available")

    assert result == {
        "@odata.type": "#microsoft.graph.mobileAppAssignment",
        "intent": "available",
        "target": {
            "@odata.type": "#microsoft.graph.groupAssignmentTarget",
            "groupId": GROUP_ID,
        },
    }
