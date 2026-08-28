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

"""Intune app management calls: Win32 app upload, queries, and assignments.

Implements the full upload flow for a Win32 LOB app:

    1. Create Win32 app record in Intune (POST mobileApps)
    2. Create a content version (POST contentVersions)
    3. Create a file entry and wait for SAS URI (POST files + polling)
    4. Upload encrypted payload to Azure Blob Storage (PUT blocks + block list)
    5. Commit the uploaded file with encryption metadata (POST commit + polling)
    6. Set the committed content version on the app (PATCH mobileApps)

Also provides app queries used for reconciliation (list_mobile_apps,
get_mobile_app, update_win32_app) and group-based assignment plumbing
(resolve_group_id, resolve_assignment_target, get_app_assignments,
build_assignment, assign_app) used by deployment promotion.

All functions take an access_token as the first argument. Obtain one via
[get_access_token][napt.auth.credentials.get_access_token]. Graph calls go
through [graph_request][napt.graph.client.graph_request] and inherit its
retry behavior; Azure Blob PUTs carry their own retry tuned for
SAS-propagation 403s.
"""

from __future__ import annotations

import base64
from pathlib import Path
import re
import time
from typing import TYPE_CHECKING

import requests

from napt.exceptions import ConfigError, NetworkError
from napt.graph.client import GRAPH_BASE, auth_headers, graph_request, json_headers

if TYPE_CHECKING:
    from napt.upload.intunewin import IntunewinMetadata

WIN32_LOB_APP_TYPE = "#microsoft.graph.win32LobApp"

# Azure Block Blob: minimum recommended chunk size is 4 MiB; 6 MiB is a
# common choice that stays well below the 4000-block limit for large files.
CHUNK_SIZE = 6 * 1024 * 1024  # 6 MiB

POLL_INTERVAL_SECONDS = 2
POLL_MAX_SECONDS = 120


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
            poll times out after POLL_MAX_SECONDS. The deadline covers
            transient-failure retry waits too, so throttling during the
            poll cannot stretch it indefinitely.

    """
    deadline = time.monotonic() + POLL_MAX_SECONDS
    while time.monotonic() < deadline:
        data = graph_request(
            "GET",
            poll_url,
            context,
            headers=auth_headers(access_token),
            deadline=deadline,
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
    body = graph_request(
        "GET", url, "resolve_group_id", headers=auth_headers(access_token)
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
    body = graph_request(
        "GET", url, "get_app_assignments", headers=auth_headers(access_token)
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
    graph_request(
        "POST", url, "assign_app", headers=json_headers(access_token), json=body
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
        f"{GRAPH_BASE}/deviceAppManagement/mobileApps?$select=id,displayName,notes"
    )
    apps: list[dict] = []
    while url:
        body = graph_request(
            "GET", url, "list_mobile_apps", headers=auth_headers(access_token)
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
    graph_request(
        "DELETE",
        url,
        "delete_mobile_app",
        headers=auth_headers(access_token),
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
    return graph_request(
        "GET", url, "get_mobile_app", headers=auth_headers(access_token)
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
    body = graph_request(
        "POST",
        url,
        "create_win32_app",
        headers=json_headers(access_token),
        json=app_metadata,
        idempotent=False,
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
    graph_request(
        "PATCH",
        url,
        "update_win32_app",
        headers=json_headers(access_token),
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
    body = graph_request(
        "POST",
        url,
        "create_content_version",
        headers=json_headers(access_token),
        json={},
        idempotent=False,
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
    file_body = graph_request(
        "POST",
        base_url,
        "create_content_version_file",
        headers=json_headers(access_token),
        json=body,
        idempotent=False,
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
            "HTTP",
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

    Note:
        Graph returns 200 (not 201) for the commit POST.

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
    graph_request(
        "POST",
        commit_url,
        "commit_content_version_file",
        headers=json_headers(access_token),
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
    graph_request(
        "PATCH",
        url,
        "commit_content_version",
        headers=json_headers(access_token),
        json=body,
    )
