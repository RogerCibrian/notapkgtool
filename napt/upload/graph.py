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

"""Microsoft Graph API and Azure Blob Storage client for Intune Win32 app upload.

Implements the full upload flow for a Win32 LOB app:

    1. Create Win32 app record in Intune (POST mobileApps)
    2. Create a content version (POST contentVersions)
    3. Create a file entry and wait for SAS URI (POST files + polling)
    4. Upload encrypted payload to Azure Blob Storage (PUT blocks + block list)
    5. Commit the uploaded file with encryption metadata (POST commit + polling)
    6. Set the committed content version on the app (PATCH mobileApps)

Also provides app queries used for reconciliation (list_mobile_apps,
get_mobile_app, update_win32_app) and group-based assignment plumbing
(resolve_group_id, get_app_assignments, build_group_assignment,
assign_app) used by deployment promotion.

All functions take an access_token as the first argument. Obtain one via
napt.upload.auth.get_access_token().

Graph calls retry transient failures — HTTP 429 (honoring Retry-After),
transient server errors, and connection drops — with bounded exponential
backoff before raising. Azure Blob PUTs carry their own retry tuned for
SAS-propagation 403s.

Example:
    Full upload flow:
        ```python
        from pathlib import Path
        from napt.upload.auth import get_access_token
        from napt.upload.graph import (
            create_win32_app, create_content_version,
            create_content_version_file, upload_to_azure_blob,
            commit_content_version_file, commit_content_version,
        )
        from napt.upload.intunewin import parse_intunewin

        token = get_access_token()
        metadata = parse_intunewin(Path("packages/napt-chrome/144.0.7559.110/Invoke-AppDeployToolkit.intunewin"))
        app_id = create_win32_app(token, app_metadata)
        cv_id = create_content_version(token, app_id)
        file_id, sas_uri = create_content_version_file(token, app_id, cv_id, metadata)
        upload_to_azure_blob(sas_uri, Path("/tmp/IntunePackage.intunewin"))
        commit_content_version_file(token, app_id, cv_id, file_id, metadata)
        commit_content_version(token, app_id, cv_id)
        ```

"""

from __future__ import annotations

import base64
from pathlib import Path
import re
import time

import requests

from napt.exceptions import AuthError, ConfigError, NetworkError
from napt.upload.intunewin import IntunewinMetadata

__all__ = [
    "VIRTUAL_TARGETS",
    "assign_app",
    "build_assignment",
    "build_group_assignment",
    "create_win32_app",
    "create_content_version",
    "create_content_version_file",
    "delete_mobile_app",
    "get_app_assignments",
    "get_mobile_app",
    "list_mobile_apps",
    "resolve_assignment_target",
    "resolve_group_id",
    "update_win32_app",
    "upload_to_azure_blob",
    "commit_content_version_file",
    "commit_content_version",
]

# The Intune app management API (mobileApps, Win32LobApp) has never fully
# graduated to v1.0. Fields critical to Win32 app uploads — allowedArchitectures,
# maxRunTimeInMinutes, displayVersion, allowAvailableUninstall — are beta-only.
# The Intune portal, Intune PowerShell SDK, and Microsoft's own tooling all use
# the beta endpoint. Do not change this to v1.0.
GRAPH_BASE = "https://graph.microsoft.com/beta"
WIN32_LOB_APP_TYPE = "#microsoft.graph.win32LobApp"

# Azure Block Blob: minimum recommended chunk size is 4 MiB; 6 MiB is a
# common choice that stays well below the 4000-block limit for large files.
CHUNK_SIZE = 6 * 1024 * 1024  # 6 MiB

POLL_INTERVAL_SECONDS = 2
POLL_MAX_SECONDS = 120


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _json_headers(access_token: str) -> dict[str, str]:
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
# server errors. Every Graph call NAPT makes is idempotent — reads,
# full-set assignment writes, PATCHes and DELETEs by id — so transient
# failures retry with backoff instead of surfacing immediately.
_GRAPH_RETRY_STATUS = (429, 500, 502, 503, 504)
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


def _graph_request(
    method: str,
    url: str,
    context: str,
    headers: dict[str, str],
    json: dict | None = None,
    ok_statuses: tuple[int, ...] = (),
) -> dict:
    """Issues a Graph API request, retrying transient failures.

    HTTP 429 (honoring ``Retry-After``) and transient server errors
    retry with exponential backoff, as do connection-level failures.
    Every other response goes straight to
    [_check_response][napt.upload.graph._check_response], so
    permission and validation errors surface immediately. The last
    attempt's failure is raised with full response detail.

    Args:
        method: HTTP method name.
        url: Full request URL.
        context: Short description of the operation for error messages.
        headers: Request headers, including authorization.
        json: Optional JSON body.
        ok_statuses: Statuses to treat as success with an empty body
            (e.g. 404 for an idempotent delete).

    Returns:
        Parsed JSON body as a dict, or empty dict for empty responses
            and ``ok_statuses`` matches.

    Raises:
        AuthError: On 401 or 403.
        ConfigError: On 400.
        NetworkError: On any other non-2xx status once retries are
            exhausted, or on a connection failure that outlasts them.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    delay = _GRAPH_RETRY_INITIAL_DELAY
    for attempt in range(1, _GRAPH_RETRY_ATTEMPTS + 1):
        err: Exception | None = None
        resp: requests.Response | None = None
        try:
            resp = requests.request(method, url, headers=headers, json=json, timeout=30)
        except requests.RequestException as exc:
            err = exc
            detail = str(exc)
        else:
            if resp.status_code in ok_statuses:
                return {}
            if resp.status_code not in _GRAPH_RETRY_STATUS:
                return _check_response(resp, context)
            detail = f"HTTP {resp.status_code}"

        if attempt == _GRAPH_RETRY_ATTEMPTS:
            if resp is not None:
                return _check_response(resp, context)
            raise NetworkError(
                f"{context} after {_GRAPH_RETRY_ATTEMPTS} attempts: {detail}"
            ) from err

        wait = _retry_wait(resp, delay)
        logger.warning(
            "GRAPH",
            f"{context}: transient failure ({detail}); retrying in "
            f"{wait:.0f}s (attempt {attempt}/{_GRAPH_RETRY_ATTEMPTS})",
        )
        time.sleep(wait)
        delay *= 2

    raise NetworkError(f"{context}: retry attempts exhausted")  # pragma: no cover


def _poll(
    access_token: str,
    poll_url: str,
    success_state: str,
    context: str,
) -> dict:
    """Polls a Graph API endpoint until the expected uploadState is reached.

    Args:
        access_token: Bearer token for Authorization header.
        poll_url: URL to GET on each iteration.
        success_state: The uploadState value that indicates success.
        context: Short description for error messages.

    Returns:
        The response body dict from the successful poll.

    Raises:
        NetworkError: If the state transitions to an error state, or if the
            poll times out after POLL_MAX_SECONDS.

    """
    deadline = time.monotonic() + POLL_MAX_SECONDS
    while time.monotonic() < deadline:
        data = _graph_request(
            "GET", poll_url, context, headers=_auth_headers(access_token)
        )
        state: str = data.get("uploadState", "")
        if state == success_state:
            return data
        if "error" in state.lower() or "fail" in state.lower():
            raise NetworkError(
                f"{context}: upload transitioned to error state '{state}'"
            )
        time.sleep(POLL_INTERVAL_SECONDS)

    raise NetworkError(
        f"{context}: timed out after {POLL_MAX_SECONDS}s "
        f"waiting for state '{success_state}'"
    )


_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}" r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def resolve_group_id(access_token: str, group: str) -> str:
    """Resolves an Entra ID group name or object ID to an object ID.

    Values that already look like object IDs (GUIDs) pass through without
    a Graph call. Names are looked up by exact displayName match, which
    requires the Group.Read.All application permission.

    Args:
        access_token: Bearer token for Graph API.
        group: Group displayName or object ID (GUID).

    Returns:
        The group's object ID.

    Raises:
        AuthError: On 401 or 403 (check Group.Read.All permission).
        ConfigError: If no group or more than one group matches the name.
        NetworkError: On 5xx or connection error.

    """
    if _GUID_RE.match(group):
        return group

    escaped = group.replace("'", "''")
    url = (
        f"{GRAPH_BASE}/groups"
        f"?$filter=displayName eq '{escaped}'&$select=id,displayName"
    )
    body = _graph_request(
        "GET", url, "resolve_group_id", headers=_auth_headers(access_token)
    )
    matches: list[dict] = body.get("value", [])

    if not matches:
        raise ConfigError(
            f"No Entra ID group found with displayName '{group}'. "
            "Check the name, or use the group's object ID instead."
        )
    if len(matches) > 1:
        ids = ", ".join(m["id"] for m in matches)
        raise ConfigError(
            f"Multiple Entra ID groups share the displayName '{group}' "
            f"({ids}). Use the object ID of the intended group instead."
        )
    return matches[0]["id"]


def resolve_assignment_target(
    access_token: str,
    group: str,
    group_id_cache: dict[str, str] | None = None,
) -> dict:
    """Resolves a deployment group entry to an assignment target dict.

    The reserved names "All Users" and "All Devices" map to Intune's
    built-in virtual targets; anything else resolves to an Entra ID
    group target via resolve_group_id.

    Args:
        access_token: Bearer token for Graph API.
        group: Group displayName, object ID, or reserved virtual name.
        group_id_cache: Optional cache of name to object ID, shared
            across calls to avoid repeated lookups.

    Returns:
        An assignment target dict for use with build_assignment.

    Raises:
        AuthError: On 401 or 403 (check Group.Read.All permission).
        ConfigError: If no group or more than one group matches a name.
        NetworkError: On 5xx or connection error.

    """
    if group in VIRTUAL_TARGETS:
        return dict(VIRTUAL_TARGETS[group])
    if group_id_cache is None:
        group_id_cache = {}
    if group not in group_id_cache:
        group_id_cache[group] = resolve_group_id(access_token, group)
    return {
        "@odata.type": "#microsoft.graph.groupAssignmentTarget",
        "groupId": group_id_cache[group],
    }


def get_app_assignments(access_token: str, app_id: str) -> list[dict]:
    """Gets the current assignments of a mobile app.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the app.

    Returns:
        A list of mobileAppAssignment dicts (empty when unassigned).

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On 5xx or connection error.

    """
    url = f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}/assignments"
    body = _graph_request(
        "GET", url, "get_app_assignments", headers=_auth_headers(access_token)
    )
    return body.get("value", [])


# Intune's built-in virtual assignment targets, reserved by these exact
# names in deployment group lists. A real Entra ID group that happens to
# share one of these display names must be referenced by object ID.
VIRTUAL_TARGETS: dict[str, dict] = {
    "All Users": {"@odata.type": "#microsoft.graph.allLicensedUsersAssignmentTarget"},
    "All Devices": {"@odata.type": "#microsoft.graph.allDevicesAssignmentTarget"},
}


def build_assignment(target: dict, intent: str) -> dict:
    """Builds a mobileAppAssignment payload for a resolved target.

    Args:
        target: An assignment target dict (group or virtual target).
        intent: Assignment intent, "available" or "required".

    Returns:
        A mobileAppAssignment dict for use with assign_app.

    """
    return {
        "@odata.type": "#microsoft.graph.mobileAppAssignment",
        "intent": intent,
        "target": target,
    }


def build_group_assignment(group_id: str, intent: str) -> dict:
    """Builds a mobileAppAssignment payload targeting one Entra ID group.

    Args:
        group_id: Object ID of the target group.
        intent: Assignment intent, "available" or "required".

    Returns:
        A mobileAppAssignment dict for use with assign_app.

    """
    return build_assignment(
        {
            "@odata.type": "#microsoft.graph.groupAssignmentTarget",
            "groupId": group_id,
        },
        intent,
    )


def assign_app(access_token: str, app_id: str, assignments: list[dict]) -> None:
    """Sets a mobile app's assignments.

    The assign action replaces the app's entire assignment set. Callers
    that intend to preserve existing assignments must read them first with
    get_app_assignments and include them in the new list.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the app.
        assignments: Complete list of mobileAppAssignment dicts to apply.

    Raises:
        AuthError: On 401 or 403.
        ConfigError: On 400 (invalid assignment payload).
        NetworkError: On 5xx or connection error.

    """
    url = f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}/assign"
    body = {"mobileAppAssignments": assignments}
    _graph_request(
        "POST", url, "assign_app", headers=_json_headers(access_token), json=body
    )


def list_mobile_apps(access_token: str) -> list[dict]:
    """Lists all mobile apps in the tenant with id, displayName, and notes.

    Follows @odata.nextLink pagination until the collection is exhausted.

    Args:
        access_token: Bearer token for Graph API.

    Returns:
        A list of app dicts, each with at least "id", "displayName", and
            "notes" keys.

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On 5xx or connection error.

    """
    url: str | None = (
        f"{GRAPH_BASE}/deviceAppManagement/mobileApps" "?$select=id,displayName,notes"
    )
    apps: list[dict] = []
    while url:
        body = _graph_request(
            "GET", url, "list_mobile_apps", headers=_auth_headers(access_token)
        )
        apps.extend(body.get("value", []))
        url = body.get("@odata.nextLink")
    return apps


def delete_mobile_app(access_token: str, app_id: str) -> None:
    """Deletes a mobile app from Intune.

    A 404 is tolerated — the app being already gone is the desired end
    state, so retried deletions stay idempotent.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the app to delete.

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On 5xx or connection error.

    """
    url = f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}"
    _graph_request(
        "DELETE",
        url,
        "delete_mobile_app",
        headers=_auth_headers(access_token),
        ok_statuses=(404,),
    )


def get_mobile_app(access_token: str, app_id: str) -> dict:
    """Gets one mobile app's full object by Graph API ID.

    Used to read subtype fields that $select on the collection cannot
    reliably return, such as win32LobApp.committedContentVersion.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the app.

    Returns:
        The full app object dict.

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On 5xx or connection error.

    """
    url = f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}"
    return _graph_request(
        "GET", url, "get_mobile_app", headers=_auth_headers(access_token)
    )


def create_win32_app(access_token: str, app_metadata: dict) -> str:
    """Creates a new Win32 LOB app record in Intune.

    Args:
        access_token: Bearer token for Graph API.
        app_metadata: Win32LobApp JSON payload (display name, install
            commands, detection rules, etc.).

    Returns:
        The Graph API object ID of the newly created app.

    Raises:
        AuthError: On 401 or 403.
        ConfigError: On 400 (invalid metadata).
        NetworkError: On 5xx or connection error.

    """
    url = f"{GRAPH_BASE}/deviceAppManagement/mobileApps"
    body = _graph_request(
        "POST",
        url,
        "create_win32_app",
        headers=_json_headers(access_token),
        json=app_metadata,
    )
    return body["id"]


def update_win32_app(access_token: str, app_id: str, app_metadata: dict) -> None:
    """Updates an existing Win32 LOB app record's metadata in Intune.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the app to update.
        app_metadata: Win32LobApp JSON payload to apply.

    Raises:
        AuthError: On 401 or 403.
        ConfigError: On 400 (invalid metadata).
        NetworkError: On 5xx or connection error.

    """
    url = f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}"
    _graph_request(
        "PATCH",
        url,
        "update_win32_app",
        headers=_json_headers(access_token),
        json=app_metadata,
    )


def create_content_version(access_token: str, app_id: str) -> str:
    """Creates a new content version for a Win32 app.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the Win32 app.

    Returns:
        The content version ID string.

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On 5xx or connection error.

    """
    url = (
        f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}"
        f"/microsoft.graph.win32LobApp/contentVersions"
    )
    body = _graph_request(
        "POST", url, "create_content_version", headers=_json_headers(access_token), json={}
    )
    return body["id"]


def create_content_version_file(
    access_token: str,
    app_id: str,
    cv_id: str,
    metadata: IntunewinMetadata,
) -> tuple[str, str]:
    """Creates a file entry for a content version and waits for the SAS URI.

    Posts the file size information to Graph API, then polls until Azure
    Storage has provisioned a SAS URI for the upload.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the Win32 app.
        cv_id: Content version ID from create_content_version.
        metadata: Parsed .intunewin metadata (provides file sizes).

    Returns:
        A tuple of (file_id, sas_uri) where sas_uri is the Azure Blob
            Storage SAS URI to upload the encrypted payload to.

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On 5xx, connection error, or upload state error.

    """
    base_url = (
        f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}"
        f"/microsoft.graph.win32LobApp/contentVersions/{cv_id}/files"
    )
    body = {
        "@odata.type": "#microsoft.graph.mobileAppContentFile",
        "name": metadata.encrypted_file_name,
        "size": metadata.unencrypted_content_size,
        "sizeEncrypted": metadata.encrypted_file_size,
        "manifest": None,
        "isDependency": False,
    }
    file_body = _graph_request(
        "POST",
        base_url,
        "create_content_version_file",
        headers=_json_headers(access_token),
        json=body,
    )
    file_id: str = file_body["id"]

    poll_url = f"{base_url}/{file_id}"
    data = _poll(
        access_token,
        poll_url,
        success_state="azureStorageUriRequestSuccess",
        context="create_content_version_file (poll SAS URI)",
    )
    return file_id, data["azureStorageUri"]


_BLOB_RETRY_STATUS = (403, 408, 429, 500, 502, 503, 504)
_BLOB_RETRY_ATTEMPTS = 5
_BLOB_RETRY_INITIAL_DELAY = 2.0


def _blob_put_with_retry(
    url: str,
    data: bytes,
    headers: dict[str, str],
    context: str,
    timeout: int = 300,
) -> None:
    """PUTs a payload to Azure Blob Storage, retrying transient failures.

    A freshly provisioned SAS URI can be rejected with HTTP 403 ("SAS
    identifier cannot be found") for a few seconds until the signature
    propagates to the storage front end, so 403 is retryable here —
    unlike Graph API calls, where it means missing permissions. Retries
    use exponential backoff starting at 2 seconds.

    Args:
        url: Blob endpoint including the SAS query string.
        data: Request body.
        headers: Request headers.
        context: Failure description used in log and error messages.
        timeout: Per-request timeout in seconds.

    Raises:
        NetworkError: On a non-retryable HTTP status, or once retries
            are exhausted.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    delay = _BLOB_RETRY_INITIAL_DELAY
    for attempt in range(1, _BLOB_RETRY_ATTEMPTS + 1):
        err: Exception | None = None
        try:
            resp = requests.put(url, data=data, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            err = exc
            detail = str(exc)
        else:
            if resp.ok:
                return
            detail = f"HTTP {resp.status_code}\n{resp.text}"
            if resp.status_code not in _BLOB_RETRY_STATUS:
                raise NetworkError(f"{context}: {detail}")

        if attempt == _BLOB_RETRY_ATTEMPTS:
            raise NetworkError(
                f"{context} after {_BLOB_RETRY_ATTEMPTS} attempts: {detail}"
            ) from err

        logger.warning(
            "UPLOAD",
            f"{context} ({detail.splitlines()[0]}); "
            f"retrying in {delay:.0f}s (attempt {attempt}/{_BLOB_RETRY_ATTEMPTS})",
        )
        time.sleep(delay)
        delay *= 2


def upload_to_azure_blob(
    sas_uri: str,
    encrypted_payload_path: Path,
) -> None:
    """Uploads the encrypted payload to Azure Blob Storage using block blobs.

    Splits the file into CHUNK_SIZE chunks, uploads each as a block with a
    base64-encoded block ID, then commits the block list. Prints an inline
    progress percentage as each chunk completes. Transient per-request
    failures (including 403 from a not-yet-propagated SAS URI) are retried
    with backoff.

    Args:
        sas_uri: Azure Blob Storage SAS URI from create_content_version_file.
        encrypted_payload_path: Path to the extracted encrypted payload file
            (IntunePackage.intunewin from inside the .intunewin ZIP).

    Raises:
        NetworkError: If any block upload or the block list commit fails
            after retries.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    block_ids: list[str] = []
    total_bytes = encrypted_payload_path.stat().st_size
    bytes_uploaded = 0
    last_percent = -1

    started_at = time.time()
    with open(encrypted_payload_path, "rb") as fh:
        block_index = 0
        while True:
            chunk = fh.read(CHUNK_SIZE)
            if not chunk:
                break

            # Block ID: base64(zero-padded 5-digit decimal index)
            block_id = base64.b64encode(str(block_index).zfill(5).encode()).decode()
            block_ids.append(block_id)

            put_url = f"{sas_uri}&comp=block&blockid={block_id}"
            _blob_put_with_retry(
                put_url,
                chunk,
                headers={
                    "x-ms-blob-type": "BlockBlob",
                    "Content-Length": str(len(chunk)),
                },
                context=f"Azure Blob block upload failed (block {block_index})",
            )

            bytes_uploaded += len(chunk)
            if total_bytes:
                pct = int(bytes_uploaded * 100 / total_bytes)
                if pct != last_percent:
                    logger.progress("UPLOAD", f"{pct}%")
                    last_percent = pct

            block_index += 1

    # Commit all blocks by submitting the block list
    block_list_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<BlockList>\n"
        + "".join(f"  <Latest>{bid}</Latest>\n" for bid in block_ids)
        + "</BlockList>"
    )
    commit_url = f"{sas_uri}&comp=blocklist"
    _blob_put_with_retry(
        commit_url,
        block_list_xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
        context="Azure Blob block list commit failed",
        timeout=60,
    )

    elapsed = time.time() - started_at
    speed_mb = (bytes_uploaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
    size_mb = bytes_uploaded / (1024 * 1024)
    logger.info(
        "UPLOAD",
        f"Complete: {encrypted_payload_path.name} ({size_mb:.1f} MB) "
        f"in {elapsed:.1f}s at {speed_mb:.1f} MB/s",
    )


def commit_content_version_file(
    access_token: str,
    app_id: str,
    cv_id: str,
    file_id: str,
    metadata: IntunewinMetadata,
) -> None:
    """Commits the uploaded file with encryption metadata, then waits for confirmation.

    Sends the encryption key, MAC, IV, and digest to Graph API, then polls
    until Intune confirms the file is committed.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the Win32 app.
        cv_id: Content version ID.
        file_id: File entry ID from create_content_version_file.
        metadata: Parsed .intunewin metadata (provides all encryption fields).

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On 5xx, connection error, or if commit times out.

    """
    commit_url = (
        f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}"
        f"/microsoft.graph.win32LobApp/contentVersions/{cv_id}"
        f"/files/{file_id}/commit"
    )
    body = {
        "fileEncryptionInfo": {
            "encryptionKey": metadata.encryption_key,
            "macKey": metadata.mac_key,
            "initializationVector": metadata.init_vector,
            "mac": metadata.mac,
            "profileIdentifier": metadata.profile_identifier,
            "fileDigest": metadata.file_digest,
            "fileDigestAlgorithm": metadata.file_digest_algorithm,
        }
    }
    _graph_request(
        "POST",
        commit_url,
        "commit_content_version_file",
        headers=_json_headers(access_token),
        json=body,
    )

    poll_url = (
        f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}"
        f"/microsoft.graph.win32LobApp/contentVersions/{cv_id}/files/{file_id}"
    )
    _poll(
        access_token,
        poll_url,
        success_state="commitFileSuccess",
        context="commit_content_version_file (poll commit)",
    )


def commit_content_version(access_token: str, app_id: str, cv_id: str) -> None:
    """Sets the committed content version on the Win32 app.

    This is the final step — after calling this, the app is fully published
    in Intune and available for assignment.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the Win32 app.
        cv_id: Content version ID to mark as committed.

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On 5xx or connection error.

    """
    url = f"{GRAPH_BASE}/deviceAppManagement/mobileApps/{app_id}"
    body = {
        "@odata.type": WIN32_LOB_APP_TYPE,
        "committedContentVersion": cv_id,
    }
    _graph_request(
        "PATCH",
        url,
        "commit_content_version",
        headers=_json_headers(access_token),
        json=body,
    )
