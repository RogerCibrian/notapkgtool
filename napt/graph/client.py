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
function through which Intune app management, assignment, app
registration, and tenant lookup calls reach Graph, along with the header
builders callers pass to it and the retrying send loop that the Azure
Blob upload in [napt.graph.intune][] shares. Endpoint-specific wrappers
live in [napt.graph.intune][] and [napt.auth.registration][].

Every request goes through one pooled session, so a run that makes
hundreds of calls, or uploads a package in many blocks, reuses its
connections instead of opening a new one per call.

Graph calls retry transient failures (HTTP 429 honoring Retry-After,
transient server errors, and connection drops) with bounded exponential
backoff before raising. Resource-creating POSTs retry only unambiguous
throttling responses, so a lost reply to a processed create is never
resubmitted as a duplicate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import functools
import time
import uuid

import requests
from requests.adapters import HTTPAdapter

from napt.exceptions import AuthError, ConfigError, NetworkError
from napt.logging import get_global_logger

# The Intune app management API (mobileApps, Win32LobApp) has never fully
# graduated to v1.0. Fields critical to Win32 app uploads (allowedArchitectures,
# maxRunTimeInMinutes, displayVersion, allowAvailableUninstall) are beta-only.
# The Intune portal, Intune PowerShell SDK, and Microsoft's own tooling all use
# the beta endpoint. Do not change this to v1.0. The directory calls (app
# registrations, service principals, the tenant's organization record) share
# it, so every Graph URL in NAPT comes from one base; those resources have
# the same shape on both versions.
GRAPH_BASE = "https://graph.microsoft.com/beta"

# Seconds allowed for a Graph request.
_GRAPH_TIMEOUT = 30


@functools.cache
def session() -> requests.Session:
    """Returns the pooled session every Graph and blob request is sent with.

    The session keeps connections open between requests. It carries no
    retry configuration of its own: retrying is decided per call by a
    [RetryPolicy][napt.graph.client.RetryPolicy], since what is safe to
    resend differs between a read, a create, and a blob block.
    """
    pooled = requests.Session()
    adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8)
    pooled.mount("https://", adapter)
    pooled.mount("http://", adapter)
    return pooled


def auth_headers(access_token: str) -> dict[str, str]:
    """Returns the Authorization header for a bodiless Graph request.

    Args:
        access_token: Bearer token for Graph API.

    Returns:
        Headers carrying the bearer token.

    """
    return {"Authorization": f"Bearer {access_token}"}


def json_headers(access_token: str) -> dict[str, str]:
    """Returns the headers for a Graph request that carries a JSON body.

    Args:
        access_token: Bearer token for Graph API.

    Returns:
        Headers carrying the bearer token and the JSON content type.

    """
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _check_response(response: requests.Response, context: str) -> dict:
    """Checks an HTTP response and raises the appropriate NAPT exception.

    The message names the call and what Graph answered. Which permission
    the signed-in identity lacks depends on the call, so the message does
    not guess; a caller that knows the role adds it.

    Args:
        response: The HTTP response to check.
        context: Short description of the operation for error messages.

    Returns:
        Parsed JSON body as a dict, or empty dict for 204 responses.

    Raises:
        AuthError: On 401 or 403.
        ConfigError: On 400.
        NetworkError: On 5xx or any other non-2xx status, carrying the
            status code.

    """
    status = response.status_code
    if status in (401, 403):
        raise AuthError(
            f"{context}: HTTP {status} {response.reason}: the signed-in identity "
            f"is not allowed to make this call.\n{response.text}"
        )
    if status == 400:
        raise ConfigError(
            f"{context}: HTTP 400 Bad Request: Graph rejected the request."
            f"\n{response.text}"
        )
    if status >= 500:
        raise NetworkError(
            f"{context}: HTTP {status}: Graph API server error.\n{response.text}",
            status_code=status,
        )
    if not response.ok:
        raise NetworkError(
            f"{context}: HTTP {status}\n{response.text}", status_code=status
        )
    if status == 204 or not response.text:
        return {}
    return response.json()


@dataclass(frozen=True)
class RetryPolicy:
    """What a send loop retries, and how long it waits between attempts.

    Attributes:
        statuses: Response statuses that are retried.
        attempts: Attempts made before the last failure is surfaced.
        initial_delay: Backoff before the second attempt, in seconds;
            doubled after each retry.
        retry_connection_errors: Whether a transport failure is retried.
            False for a request whose reply may have been lost after the
            server processed it.
        redact: Applied to failure text before it is logged or raised,
            for URLs that carry a secret.
    """

    statuses: tuple[int, ...]
    attempts: int = 5
    initial_delay: float = 2.0
    retry_connection_errors: bool = True
    redact: Callable[[str], str] | None = None


# Microsoft Graph throttles the Intune endpoints (HTTP 429 with a
# Retry-After header, per app per tenant) and sheds load with transient
# server errors. Most Graph calls NAPT makes are idempotent (reads,
# full-set assignment writes, PATCHes and DELETEs by id) and retry the
# full transient set. Resource-creating POSTs are not: a connection
# drop or gateway error (500/502/504) can hide a create that actually
# succeeded, and resubmitting would duplicate the resource, so they
# retry only responses that guarantee the request was shed before
# processing (429/503/509 per the Graph error contract). A surfaced
# ambiguous failure converges on re-run through the upload flow's
# provenance-stamp adoption.
GRAPH_POLICY = RetryPolicy(statuses=(429, 500, 502, 503, 504, 509))
GRAPH_CREATE_POLICY = RetryPolicy(
    statuses=(429, 503, 509), retry_connection_errors=False
)

# Ceiling for a wait taken from Retry-After; anything longer is served
# by the normal failure path rather than a stalled run.
_RETRY_MAX_WAIT = 300.0


def _retry_wait(response: requests.Response | None, fallback: float) -> float:
    """Returns the wait before the next retry attempt.

    Honors a numeric ``Retry-After`` header when the response carries one
    (Graph and Azure Storage throttling responses do), capped at a
    ceiling; otherwise the exponential-backoff fallback applies.

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
            return min(float(retry_after), _RETRY_MAX_WAIT)
    return fallback


def send(
    method: str,
    url: str,
    *,
    context: str,
    headers: dict[str, str],
    policy: RetryPolicy,
    data: bytes | None = None,
    json: dict | None = None,
    timeout: int = _GRAPH_TIMEOUT,
    deadline: float | None = None,
) -> requests.Response:
    """Sends a request through the pooled session, retrying per the policy.

    A response outside the policy's retry statuses is returned as is, so
    the caller maps it. A retryable status or transport failure is retried
    after a wait, honoring ``Retry-After``; once attempts run out, the last
    response is returned, or the transport failure raised.

    Args:
        method: HTTP method name.
        url: Full request URL.
        context: Short description of the operation for log and error
            messages.
        headers: Request headers, including authorization.
        policy: What to retry and how to wait.
        data: Optional raw body.
        json: Optional JSON body.
        timeout: Seconds allowed for one attempt.
        deadline: Optional ``time.monotonic()`` budget; a retry wait that
            would run past it ends the retrying instead.

    Returns:
        The final response: a success, a status the policy does not retry,
        or the last retried failure.

    Raises:
        NetworkError: On a transport failure the policy does not retry, or
            one that persists through every attempt.

    """
    logger = get_global_logger()
    redact = policy.redact or (lambda text: text)

    def attempt() -> tuple[requests.Response | None, Exception | None, str]:
        """Sends once; returns the response, or the transport failure."""
        try:
            resp = session().request(
                method, url, headers=headers, data=data, json=json, timeout=timeout
            )
        except requests.RequestException as exc:
            detail = redact(str(exc))
            if not policy.retry_connection_errors:
                raise NetworkError(f"{context}: {detail}") from exc
            return None, exc, detail
        return resp, None, f"HTTP {resp.status_code}"

    delay = policy.initial_delay
    for number in range(1, policy.attempts):
        resp, err, detail = attempt()
        if resp is not None and resp.status_code not in policy.statuses:
            return resp
        wait = _retry_wait(resp, delay)
        if deadline is not None and time.monotonic() + wait >= deadline:
            # No budget left for another attempt; surface this failure.
            if resp is not None:
                return resp
            raise NetworkError(f"{context}: {detail}") from err
        logger.warning(
            "HTTP",
            f"{context}: transient failure ({detail}); retrying in "
            f"{wait:.0f}s (attempt {number}/{policy.attempts})",
        )
        time.sleep(wait)
        delay *= 2

    # The last attempt's outcome is the caller's, whatever it is.
    resp, err, detail = attempt()
    if resp is not None:
        return resp
    raise NetworkError(f"{context} after {policy.attempts} attempts: {detail}") from err


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
    connection failures: a lost reply to a processed create must not
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
    policy = GRAPH_POLICY if idempotent else GRAPH_CREATE_POLICY
    retried = tuple(s for s in policy.statuses if s not in ok_statuses)
    response = send(
        method,
        url,
        context=context,
        headers={**headers, "client-request-id": str(uuid.uuid4())},
        policy=RetryPolicy(
            statuses=retried,
            retry_connection_errors=policy.retry_connection_errors,
        ),
        json=json,
        deadline=deadline,
    )
    if response.status_code in ok_statuses:
        return {}
    return _check_response(response, context)
