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

All functions take an access_token as the first argument. Obtain one via
napt.upload.auth.get_access_token().

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
import time

import requests

from napt.exceptions import AuthError, ConfigError, NetworkError
from napt.upload.intunewin import IntunewinMetadata

__all__ = [
    "create_win32_app",
    "create_content_version",
    "create_content_version_file",
    "upload_to_azure_blob",
    "commit_content_version_file",
    "commit_content_version",
]

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
    """Check an HTTP response and raise the appropriate NAPT exception.

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


def _poll(
    access_token: str,
    poll_url: str,
    success_state: str,
    context: str,
) -> dict:
    """Poll a Graph API endpoint until the expected uploadState is reached.

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
        resp = requests.get(poll_url, headers=_auth_headers(access_token), timeout=30)
        data = _check_response(resp, context)
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


def create_win32_app(access_token: str, app_metadata: dict) -> str:
    """Create a new Win32 LOB app record in Intune.

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
    resp = requests.post(
        url, headers=_json_headers(access_token), json=app_metadata, timeout=30
    )
    body = _check_response(resp, "create_win32_app")
    return body["id"]


def create_content_version(access_token: str, app_id: str) -> str:
    """Create a new content version for a Win32 app.

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
    resp = requests.post(url, headers=_json_headers(access_token), json={}, timeout=30)
    body = _check_response(resp, "create_content_version")
    return body["id"]


def create_content_version_file(
    access_token: str,
    app_id: str,
    cv_id: str,
    metadata: IntunewinMetadata,
) -> tuple[str, str]:
    """Create a file entry for a content version and wait for the SAS URI.

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
    resp = requests.post(
        base_url, headers=_json_headers(access_token), json=body, timeout=30
    )
    file_body = _check_response(resp, "create_content_version_file")
    file_id: str = file_body["id"]

    poll_url = f"{base_url}/{file_id}"
    data = _poll(
        access_token,
        poll_url,
        success_state="azureStorageUriRequestSuccess",
        context="create_content_version_file (poll SAS URI)",
    )
    return file_id, data["azureStorageUri"]


def upload_to_azure_blob(
    sas_uri: str,
    encrypted_payload_path: Path,
) -> None:
    """Upload the encrypted payload to Azure Blob Storage using block blobs.

    Splits the file into CHUNK_SIZE chunks, uploads each as a block with a
    base64-encoded block ID, then commits the block list. Prints an inline
    progress percentage as each chunk completes (matching the download
    progress format used by napt.io.download).

    Args:
        sas_uri: Azure Blob Storage SAS URI from create_content_version_file.
        encrypted_payload_path: Path to the extracted encrypted payload file
            (IntunePackage.intunewin from inside the .intunewin ZIP).

    Raises:
        NetworkError: If any block upload or the block list commit fails.

    """
    block_ids: list[str] = []
    total_bytes = encrypted_payload_path.stat().st_size
    bytes_uploaded = 0
    last_percent = -1

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
            resp = requests.put(
                put_url,
                data=chunk,
                headers={
                    "x-ms-blob-type": "BlockBlob",
                    "Content-Length": str(len(chunk)),
                },
                timeout=300,
            )
            if not resp.ok:
                raise NetworkError(
                    f"Azure Blob block upload failed (block {block_index}): "
                    f"HTTP {resp.status_code}\n{resp.text}"
                )

            bytes_uploaded += len(chunk)
            if total_bytes:
                pct = int(bytes_uploaded * 100 / total_bytes)
                if pct != last_percent:
                    print(f"upload progress: {pct}%", end="\r")
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
    resp = requests.put(
        commit_url,
        data=block_list_xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
        timeout=60,
    )
    if not resp.ok:
        raise NetworkError(
            f"Azure Blob block list commit failed: HTTP {resp.status_code}\n{resp.text}"
        )


def commit_content_version_file(
    access_token: str,
    app_id: str,
    cv_id: str,
    file_id: str,
    metadata: IntunewinMetadata,
) -> None:
    """Commit the uploaded file with encryption metadata, then wait for confirmation.

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
    resp = requests.post(
        commit_url, headers=_json_headers(access_token), json=body, timeout=30
    )
    # Graph API returns 200 for this call
    _check_response(resp, "commit_content_version_file")

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
    """Set the committed content version on the Win32 app.

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
    resp = requests.patch(
        url, headers=_json_headers(access_token), json=body, timeout=30
    )
    _check_response(resp, "commit_content_version")
