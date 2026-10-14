"""Tests for napt.graph.client."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
import requests
import requests_mock as req_mock

from napt.exceptions import AuthError, ConfigError, NetworkError
from napt.graph.client import (
    GRAPH_BASE,
    _check_response,
    auth_headers,
    graph_request,
    json_headers,
)

TOKEN = "fake-token"
APP_ID = "app-id-123"

_APPS_URL = f"{GRAPH_BASE}/deviceAppManagement/mobileApps"
_APP_URL = f"{_APPS_URL}/{APP_ID}"

_SLEEP = "napt.graph.client.time.sleep"


def _get() -> dict:
    return graph_request("GET", _APP_URL, "get app", headers=auth_headers(TOKEN))


def _create() -> dict:
    return graph_request(
        "POST",
        _APPS_URL,
        "create app",
        headers=json_headers(TOKEN),
        json={"displayName": "Test App"},
        idempotent=False,
    )


# --- headers ---


def test_auth_headers_carry_bearer_token() -> None:
    """Tests that auth_headers sets only the Authorization header."""
    assert auth_headers(TOKEN) == {"Authorization": f"Bearer {TOKEN}"}


def test_json_headers_add_content_type() -> None:
    """Tests that json_headers adds a JSON content type to the bearer token."""
    assert json_headers(TOKEN) == {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }


# --- response mapping ---


def test_graph_request_returns_parsed_body() -> None:
    """Tests that a 200 response body is returned as a dict."""
    body = {"id": APP_ID}
    with req_mock.Mocker() as m:
        m.get(_APP_URL, json=body)
        assert _get() == body


def test_graph_request_empty_body_returns_empty_dict() -> None:
    """Tests that a 204 response yields an empty dict."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=204)
        assert _get() == {}


def test_graph_request_ok_statuses_short_circuit() -> None:
    """Tests that a status listed in ok_statuses is treated as success."""
    with req_mock.Mocker() as m:
        m.delete(_APP_URL, status_code=404)
        with patch(_SLEEP) as sleep_mock:
            result = graph_request(
                "DELETE",
                _APP_URL,
                "delete app",
                headers=auth_headers(TOKEN),
                ok_statuses=(404,),
            )

    assert result == {}
    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_graph_request_401_raises_auth_error() -> None:
    """Tests that a 401 raises AuthError without retrying."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=401)
        with patch(_SLEEP) as sleep_mock:
            with pytest.raises(AuthError):
                _get()

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_graph_request_non_retryable_fails_fast() -> None:
    """Tests that a 400 raises ConfigError immediately without retrying."""
    with req_mock.Mocker() as m:
        m.post(_APPS_URL, json={"error": "bad"}, status_code=400)
        with patch(_SLEEP) as sleep_mock:
            with pytest.raises(ConfigError):
                _create()

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_graph_request_sends_client_request_id() -> None:
    """Tests that every request carries a client-request-id header."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, json={"id": APP_ID})
        _get()

    assert m.request_history[0].headers["client-request-id"]


# --- retry behavior ---


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
        with patch(_SLEEP) as sleep_mock:
            result = _get()

    assert result == body
    assert len(m.request_history) == 2
    assert sleep_mock.call_args.args[0] == 7.0


def test_graph_request_retries_transient_server_error() -> None:
    """Tests that a transient 503 retries with backoff and succeeds."""
    body = {"id": APP_ID}
    with req_mock.Mocker() as m:
        m.get(_APP_URL, [{"status_code": 503}, {"json": body, "status_code": 200}])
        with patch(_SLEEP) as sleep_mock:
            result = _get()

    assert result == body
    assert sleep_mock.call_args.args[0] == 2.0  # initial backoff, no Retry-After


def test_graph_request_exhausts_attempts() -> None:
    """Tests that persistent throttling raises after bounded attempts."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=429)
        with patch(_SLEEP):
            with pytest.raises(NetworkError):
                _get()

    assert len(m.request_history) == 5


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
        with patch(_SLEEP):
            result = _get()

    assert result == body


def test_graph_request_retries_509_bandwidth_throttle() -> None:
    """Tests that a 509 bandwidth throttle is retried."""
    body = {"id": APP_ID}
    with req_mock.Mocker() as m:
        m.get(_APP_URL, [{"status_code": 509}, {"json": body, "status_code": 200}])
        with patch(_SLEEP):
            result = _get()

    assert result == body


def test_create_connection_error_fails_fast() -> None:
    """Tests that a non-idempotent POST never retries a connection failure."""
    with req_mock.Mocker() as m:
        m.post(_APPS_URL, exc=requests.exceptions.ConnectionError)
        with patch(_SLEEP) as sleep_mock:
            with pytest.raises(NetworkError):
                _create()

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_create_ambiguous_gateway_error_fails_fast() -> None:
    """Tests that a non-idempotent POST never retries an ambiguous 502."""
    with req_mock.Mocker() as m:
        m.post(_APPS_URL, status_code=502)
        with patch(_SLEEP) as sleep_mock:
            with pytest.raises(NetworkError):
                _create()

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_create_retries_throttle() -> None:
    """Tests that a non-idempotent POST retries an unambiguous 429 throttle."""
    with req_mock.Mocker() as m:
        m.post(
            _APPS_URL,
            [
                {"status_code": 429, "headers": {"Retry-After": "3"}},
                {"json": {"id": APP_ID}, "status_code": 201},
            ],
        )
        with patch(_SLEEP) as sleep_mock:
            result = _create()

    assert result == {"id": APP_ID}
    assert sleep_mock.call_args.args[0] == 3.0


def test_graph_request_deadline_stops_retries() -> None:
    """Tests that an exhausted deadline surfaces the failure unslept."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=429, headers={"Retry-After": "60"})
        with patch(_SLEEP) as sleep_mock:
            with pytest.raises(NetworkError):
                graph_request(
                    "GET",
                    _APP_URL,
                    "deadline test",
                    headers=auth_headers(TOKEN),
                    deadline=time.monotonic() + 1.0,
                )

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_deadline_surfaces_a_connection_failure_unslept() -> None:
    """Tests that a transport failure with no budget left is raised at once."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, exc=requests.exceptions.ConnectionError("no route"))
        with patch(_SLEEP) as sleep_mock:
            with pytest.raises(NetworkError, match="no route"):
                graph_request(
                    "GET",
                    _APP_URL,
                    "deadline test",
                    headers=auth_headers(TOKEN),
                    deadline=time.monotonic() + 1.0,
                )

    assert len(m.request_history) == 1
    sleep_mock.assert_not_called()


def test_network_error_carries_the_status() -> None:
    """Tests that a failed status is readable from the error, not its text."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=404, text="not found")
        with pytest.raises(NetworkError) as excinfo:
            _get()

    assert excinfo.value.status_code == 404


def test_forbidden_message_does_not_guess_the_role() -> None:
    """Tests that a 403 names the call and the refusal, not an Intune role."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=403, reason="Forbidden", text="denied")
        with pytest.raises(AuthError) as excinfo:
            _get()

    message = str(excinfo.value)
    assert "get app: HTTP 403" in message
    assert "not allowed" in message
    assert "app manager" not in message


def test_bad_request_message_does_not_guess_a_cause() -> None:
    """Tests that a 400 reports Graph's refusal without blaming app metadata."""
    with req_mock.Mocker() as m:
        m.get(_APP_URL, status_code=400, text="bad filter")
        with pytest.raises(ConfigError) as excinfo:
            _get()

    message = str(excinfo.value)
    assert "rejected the request" in message
    assert "metadata" not in message


def test_session_is_shared() -> None:
    """Tests that every Graph caller gets the same pooled session."""
    from napt.graph.client import session

    assert session() is session()


@pytest.mark.parametrize(
    ("status", "error"), [(403, AuthError), (400, ConfigError), (503, NetworkError)]
)
def test_error_messages_print_on_a_cp437_console(status, error) -> None:
    """Tests that a Graph error can be reported on a plain cmd.exe console."""
    response = requests.Response()
    response.status_code = status
    response._content = b"details"

    with pytest.raises(error) as excinfo:
        _check_response(response, "upload")

    str(excinfo.value).encode("cp437")
