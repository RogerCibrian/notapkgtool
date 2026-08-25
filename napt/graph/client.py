# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Microsoft Graph HTTP transport shared by every Graph caller in NAPT.

Provides [graph_request][napt.graph.client.graph_request], the single
function through which Intune app management, assignment, and app
registration calls reach Graph, along with the header builders callers
pass to it. Endpoint-specific wrappers live in
[napt.graph.intune][] and [napt.auth.registration][].

Graph calls retry transient failures -- HTTP 429 (honoring Retry-After),
transient server errors, and connection drops -- with bounded exponential
backoff before raising. Resource-creating POSTs retry only unambiguous
throttling responses, so a lost reply to a processed create is never
resubmitted as a duplicate.

Example:
    Reading a resource:
        ```python
        from napt.auth.credentials import get_access_token
        from napt.graph.client import GRAPH_BASE, auth_headers, graph_request

        token = get_access_token()
        app = graph_request(
            "GET",
            f"{GRAPH_BASE}/deviceAppManagement/mobileApps/<id>",
            "get app",
            headers=auth_headers(token),
        )
        ```

"""

from __future__ import annotations

import time
import uuid

import requests

from napt.exceptions import AuthError, ConfigError, NetworkError

__all__ = [
    "GRAPH_BASE",
    "auth_headers",
    "graph_request",
    "json_headers",
]

# The Intune app management API (mobileApps, Win32LobApp) has never fully
# graduated to v1.0. Fields critical to Win32 app uploads — allowedArchitectures,
# maxRunTimeInMinutes, displayVersion, allowAvailableUninstall — are beta-only.
# The Intune portal, Intune PowerShell SDK, and Microsoft's own tooling all use
# the beta endpoint. Do not change this to v1.0.
GRAPH_BASE = "https://graph.microsoft.com/beta"


def auth_headers(access_token: str) -> dict[str, str]:
    """Returns the Authorization header for a bodiless Graph request.

    Args:
        access_token: Bearer token for Graph API.

    Returns:
        Headers carrying the bearer token.

    """
    return {"Authorization": f"Bearer {access_token}"}


def json_headers(access_token: str) -> dict[str, str]:
    """Returns the headers for a Graph request with a JSON body.

    Args:
        access_token: Bearer token for Graph API.

    Returns:
        Headers carrying the bearer token and a JSON content type.

    """
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _check_response(response: requests.Response, context: str) -> dict:
    """Checks an HTTP response and raises the appropriate NAPT exception.

    Args:
        response: The HTTP response to check.
        context: Short description of the operation for error messages.

    Returns:
        Parsed JSON body as a dict, or empty dict for 204 responses.

    Raises:
        AuthError: On 401 or 403.
        ConfigError: On 400 (bad request — likely a metadata problem).
        NetworkError: On 5xx or any other non-2xx status.

    """
    if response.status_code in (401, 403):
        raise AuthError(
            f"{context}: HTTP {response.status_code} — "
            f"check that the authenticated account has Intune device "
            f"administrator or app manager permissions.\n{response.text}"
        )
    if response.status_code == 400:
        raise ConfigError(
            f"{context}: HTTP 400 Bad Request — the app metadata may be "
            f"invalid.\n{response.text}"
        )
    if response.status_code >= 500:
        raise NetworkError(
            f"{context}: HTTP {response.status_code} — Graph API server error."
            f"\n{response.text}"
        )
    if not response.ok:
        raise NetworkError(f"{context}: HTTP {response.status_code}\n{response.text}")
    if response.status_code == 204 or not response.text:
        return {}
    return response.json()


# Microsoft Graph throttles the Intune endpoints (HTTP 429 with a
# Retry-After header, per app per tenant) and sheds load with transient
# server errors. Most Graph calls NAPT makes are idempotent — reads,
# full-set assignment writes, PATCHes and DELETEs by id — and retry the
# full transient set. Resource-creating POSTs are not: a connection
# drop or gateway error (500/502/504) can hide a create that actually
# succeeded, and resubmitting would duplicate the resource, so they
# retry only responses that guarantee the request was shed before
# processing (429/503/509 per the Graph error contract). A surfaced
# ambiguous failure converges on re-run through the upload flow's
# provenance-stamp adoption.
_GRAPH_RETRY_STATUS = (429, 500, 502, 503, 504, 509)
_GRAPH_RETRY_STATUS_UNAMBIGUOUS = (429, 503, 509)
_GRAPH_RETRY_ATTEMPTS = 5
_GRAPH_RETRY_INITIAL_DELAY = 2.0
# Ceiling for a wait taken from Retry-After; anything longer is served
# by the normal failure path rather than a stalled run.
_GRAPH_RETRY_MAX_WAIT = 300.0


def _retry_wait(response: requests.Response | None, fallback: float) -> float:
    """Returns the wait before the next retry attempt.

    Honors a numeric ``Retry-After`` header when the response carries one
    (Graph throttling responses do), capped at a ceiling; otherwise the
    exponential-backoff fallback applies.

    Args:
        response: The throttled or failed response, or None for a
            connection-level failure.
        fallback: Current exponential backoff delay in seconds.

    Returns:
        Seconds to wait before the next attempt.

    """
    if response is not None:
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.strip().isdigit():
            return min(float(retry_after), _GRAPH_RETRY_MAX_WAIT)
    return fallback


def graph_request(
    method: str,
    url: str,
    context: str,
    headers: dict[str, str],
    json: dict | None = None,
    ok_statuses: tuple[int, ...] = (),
    idempotent: bool = True,
    deadline: float | None = None,
) -> dict:
    """Issues a Graph API request, retrying transient failures.

    HTTP 429 (honoring ``Retry-After``) and transient server errors
    retry with exponential backoff, as do connection-level failures.
    Non-idempotent calls (resource-creating POSTs) retry only statuses
    that guarantee the request was shed before processing, and never
    connection failures — a lost reply to a processed create must not
    be resubmitted. Every other response is checked immediately, so
    permission and validation errors surface without retrying. The last
    attempt's failure is raised with full response detail. Each request
    carries a fresh ``client-request-id`` header for Microsoft support
    correlation.

    Args:
        method: HTTP method name.
        url: Full request URL.
        context: Short description of the operation for error messages.
        headers: Request headers, including authorization.
        json: Optional JSON body.
        ok_statuses: Statuses to treat as success with an empty body
            (e.g. 404 for an idempotent delete).
        idempotent: Whether resubmitting this request is always safe.
            False restricts retries to unambiguous throttling responses.
        deadline: Optional ``time.monotonic()`` budget; a retry wait
            that would run past it surfaces the failure instead.

    Returns:
        Parsed JSON body as a dict, or empty dict for empty responses
        and ``ok_statuses`` matches.

    Raises:
        AuthError: On 401 or 403.
        ConfigError: On 400.
        NetworkError: On any other non-2xx status once retries are
            exhausted, or on a connection failure.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    retry_statuses = (
        _GRAPH_RETRY_STATUS if idempotent else _GRAPH_RETRY_STATUS_UNAMBIGUOUS
    )
    delay = _GRAPH_RETRY_INITIAL_DELAY
    for attempt in range(1, _GRAPH_RETRY_ATTEMPTS + 1):
        err: Exception | None = None
        resp: requests.Response | None = None
        request_headers = {**headers, "client-request-id": str(uuid.uuid4())}
        try:
            resp = requests.request(
                method, url, headers=request_headers, json=json, timeout=30
            )
        except requests.RequestException as exc:
            if not idempotent:
                # The request may have been processed before the
                # connection died; resubmitting could duplicate the
                # resource. Surface it — re-running converges through
                # the flow-level stamp adoption.
                raise NetworkError(f"{context}: {exc}") from exc
            err = exc
            detail = str(exc)
        else:
            if resp.status_code in ok_statuses:
                return {}
            if resp.status_code not in retry_statuses:
                return _check_response(resp, context)
            detail = f"HTTP {resp.status_code}"

        if attempt == _GRAPH_RETRY_ATTEMPTS:
            if resp is not None:
                return _check_response(resp, context)
            raise NetworkError(
                f"{context} after {_GRAPH_RETRY_ATTEMPTS} attempts: {detail}"
            ) from err

        wait = _retry_wait(resp, delay)
        if deadline is not None and time.monotonic() + wait >= deadline:
            # No budget left for another attempt; surface this failure.
            if resp is not None:
                return _check_response(resp, context)
            raise NetworkError(f"{context}: {detail}") from err
        logger.warning(
            "HTTP",
            f"{context}: transient failure ({detail}); retrying in "
            f"{wait:.0f}s (attempt {attempt}/{_GRAPH_RETRY_ATTEMPTS})",
        )
        time.sleep(wait)
        delay *= 2

    raise NetworkError(f"{context}: retry attempts exhausted")  # pragma: no cover
