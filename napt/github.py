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

"""GitHub API access shared by discovery and the tool downloads.

Three parts of NAPT read GitHub: the ``api_github`` discovery strategy,
the PSADT toolkit download in ``napt build``, and the IntuneWinAppUtil
download in ``napt package``. All of them go through this module, so a
request carries the same headers, a failure reads the same, and a tag is
read the same way wherever it came from.

Tokens:
    Discovery sends the token the recipe names, which ``defaults/org.yaml``
    binds to ``api.github.com`` (see [napt.secrets][]). The tool downloads
    send ``GITHUB_TOKEN`` from the environment when it is set, since every
    unauthenticated call counts against one shared limit of 60 per hour.
    A token is only ever sent to ``api.github.com``: with a token present
    a redirect to any other host is refused.
"""

from __future__ import annotations

from collections.abc import Callable
import os
import re
from typing import Any
from urllib.parse import quote, urlencode

import requests

from napt.exceptions import ConfigError, NetworkError
from napt.logging import get_global_logger
from napt.paths import is_safe_path_component
from napt.secrets import guarded_get

API_HOST = "api.github.com"
API_BASE = f"https://{API_HOST}"

# Seconds allowed for an API call, and for downloading a release asset.
_API_TIMEOUT = 30
ASSET_TIMEOUT = 300

# A tag that is a version: digits separated by dots, with or without a
# leading v. The whole tag must match, so "4.1.7-rc1" is not 4.1.7.
_VERSION_TAG = re.compile(r"v?(\d+(?:\.\d+)+)")


def env_token() -> str | None:
    """Returns ``GITHUB_TOKEN`` from the environment, or None when unset."""
    return os.environ.get("GITHUB_TOKEN") or None


def api_headers(token: str | None) -> dict[str, str]:
    """Builds the headers for a GitHub API call.

    Args:
        token: A personal access or workflow token, or None for an
            unauthenticated call.

    Returns:
        The Accept and API-version headers, plus Authorization when a
        token is given.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_json(
    session: requests.Session,
    url: str,
    *,
    what: str,
    token: str | None = None,
    hosts: set[str] | None = None,
) -> dict[str, Any] | None:
    """Fetches a GitHub API resource and reads it as a JSON object.

    Every failure is a NetworkError that names what was asked for. An
    exhausted rate limit is named as such, from the response's own
    rate-limit header rather than the 403 status alone, since GitHub also
    answers 403 for a refused token.

    Args:
        session: The session to send with.
        url: The API URL.
        what: What is being fetched, for messages (``"the latest PSADT
            release"``).
        token: The token to send, or None.
        hosts: The hosts a redirect may go to, from
            [bound_hosts][napt.secrets.bound_hosts]; with a token and no
            hosts, only ``api.github.com``.

    Returns:
        The parsed object, or None when the resource does not exist (404).

    Raises:
        NetworkError: On transport failure, a refused or failed request,
            or a body that is not a JSON object.
    """
    if token and hosts is None:
        hosts = {API_HOST}
    try:
        response = guarded_get(
            session, url, api_headers(token), hosts=hosts, timeout=_API_TIMEOUT
        )
    except requests.RequestException as err:
        raise NetworkError(f"Failed to fetch {what}: {err}") from err

    if response.status_code == 404:
        return None
    if response.status_code == 403:
        if response.headers.get("X-RateLimit-Remaining") == "0":
            raise NetworkError(
                f"GitHub API rate limit exceeded while fetching {what}. "
                "Authenticate with a token to raise the limit."
            )
        raise NetworkError(
            f"GitHub refused the request for {what}: 403 {response.reason}"
        )
    if not response.ok:
        raise NetworkError(
            f"GitHub API request for {what} failed: {response.status_code} "
            f"{response.reason}"
        )

    try:
        data = response.json()
    except ValueError as err:
        raise NetworkError(
            f"Invalid JSON response from the GitHub API for {what}. Response: "
            f"{response.text[:200]}"
        ) from err
    if not isinstance(data, dict):
        raise NetworkError(
            f"Unexpected GitHub API response for {what}: {response.text[:200]}"
        )
    return data


def latest_release(
    session: requests.Session,
    repo: str,
    *,
    token: str | None = None,
    hosts: set[str] | None = None,
) -> dict[str, Any]:
    """Fetches a repository's latest release.

    GitHub's latest release is the most recent one that is neither a
    draft nor a pre-release.

    Args:
        session: The session to send with.
        repo: The repository as ``owner/name``.
        token: The token to send, or None.
        hosts: The hosts a redirect may go to, or None.

    Returns:
        The release object, with its ``tag_name`` and ``assets``.

    Raises:
        NetworkError: If the repository does not exist or has no releases,
            or on any failure [get_json][napt.github.get_json] reports.
    """
    logger = get_global_logger()
    url = f"{API_BASE}/repos/{repo}/releases/latest"
    logger.verbose("HTTP", f"Fetching release from: {url}")
    release = get_json(
        session, url, what=f"the latest release of {repo}", token=token, hosts=hosts
    )
    if release is None:
        raise NetworkError(f"Repository {repo!r} not found or has no releases")
    return release


def release_by_version(
    session: requests.Session,
    repo: str,
    version: str,
    *,
    token: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fetches the release of a version, however the repository tags it.

    Repositories differ on whether tags carry a ``v`` prefix, and some
    switched part-way, so both spellings are tried.

    Args:
        session: The session to send with.
        repo: The repository as ``owner/name``.
        version: The version without a prefix (``"4.1.7"``).
        token: The token to send, or None.

    Returns:
        The tag as the repository spells it, and the release object.

    Raises:
        NetworkError: If no release is tagged with either spelling, or on
            any failure [get_json][napt.github.get_json] reports.
    """
    logger = get_global_logger()
    for tag in (version, f"v{version}"):
        url = f"{API_BASE}/repos/{repo}/releases/tags/{quote(tag)}"
        logger.verbose("HTTP", f"Fetching release from: {url}")
        release = get_json(session, url, what=f"release {tag} of {repo}", token=token)
        if release is not None:
            return tag, release
    raise NetworkError(f"No release of {repo} is tagged {version} or v{version}")


def repo_file(
    session: requests.Session,
    repo: str,
    path: str,
    ref: str,
    *,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Looks a file up through the contents API at a tag or branch.

    The entry reports the file's size, its git blob hash, and a download
    URL, which is how a file that is committed to the repository rather
    than attached to a release is fetched and verified.

    Args:
        session: The session to send with.
        repo: The repository as ``owner/name``.
        path: The file's path in the repository.
        ref: The tag or branch to read it at.
        token: The token to send, or None.

    Returns:
        The contents entry, or None when the file or the ref does not exist.

    Raises:
        NetworkError: On any failure [get_json][napt.github.get_json]
            reports.
    """
    url = f"{API_BASE}/repos/{repo}/contents/{path}?{urlencode({'ref': ref})}"
    return get_json(session, url, what=f"{path} at {ref} in {repo}", token=token)


def release_tag(release: dict[str, Any]) -> str:
    """Reads a release's tag.

    Args:
        release: The release object.

    Returns:
        The tag name.

    Raises:
        NetworkError: If the release carries no tag.
    """
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise NetworkError("GitHub release response is missing 'tag_name'")
    return tag


def version_from_tag(tag: str) -> str:
    """Reads the version a tag names.

    Args:
        tag: The tag (``"4.1.7"`` or ``"v4.1.7"``).

    Returns:
        The version without the prefix.

    Raises:
        NetworkError: If the whole tag is not a version, so a suffix such
            as ``-rc1`` is never silently dropped.
    """
    match = _VERSION_TAG.fullmatch(tag)
    if not match:
        raise NetworkError(
            f"Could not extract version from tag {tag!r}: expected a version "
            "such as 1.2.3, with or without a v prefix"
        )
    return match.group(1)


def normalize_release_spec(spec: str, setting: str, example: str) -> str:
    """Turns a pinned release setting into the version it names.

    Args:
        spec: The configured value, a version with or without a ``v``
            prefix.
        setting: The setting's path, for the message (``"psadt.release"``).
        example: A valid value, for the message.

    Returns:
        The version, usable as a cache folder name.

    Raises:
        ConfigError: If the value is not a plain version.
    """
    version = spec.removeprefix("v")
    if not version or not is_safe_path_component(version):
        raise ConfigError(
            f"Invalid {setting} {spec!a}: use 'latest' or a version such as "
            f"{example!r}"
        )
    return version


def find_asset(
    release: dict[str, Any], predicate: Callable[[str], bool]
) -> dict[str, Any] | None:
    """Finds the first release asset whose name satisfies a predicate.

    Args:
        release: The release object.
        predicate: Called with each asset's name.

    Returns:
        The asset entry, or None when none matches.
    """
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and predicate(str(asset.get("name", ""))):
            return asset
    return None


def asset_names(release: dict[str, Any]) -> list[str]:
    """Lists a release's asset names, for messages."""
    return [str(a.get("name", "(unnamed)")) for a in release.get("assets") or []]


def asset_url(asset: dict[str, Any]) -> str:
    """Reads an asset's download URL.

    Args:
        asset: The asset entry.

    Returns:
        The browser download URL.

    Raises:
        NetworkError: If the entry carries none.
    """
    url = asset.get("browser_download_url")
    if not isinstance(url, str) or not url:
        raise NetworkError(f"Asset {asset.get('name')} has no download URL")
    return url


def download(
    session: requests.Session,
    url: str,
    *,
    what: str,
    timeout: int = ASSET_TIMEOUT,
) -> bytes:
    """Downloads a file and returns its bytes.

    No token is sent: the download hosts are not the API, and the bytes
    are checked by the caller against what the API reported for them.

    Args:
        session: The session to send with.
        url: The download URL.
        what: What is being downloaded, for messages.
        timeout: Seconds allowed for the download.

    Returns:
        The downloaded bytes.

    Raises:
        NetworkError: On transport failure or a failed request.
    """
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as err:
        raise NetworkError(f"Failed to download {what}: {err}") from err
    return response.content


def verify_size(what: str, content: bytes, size: object) -> None:
    """Checks downloaded bytes against the size the API reported.

    Args:
        what: What was downloaded, for the message.
        content: The downloaded bytes.
        size: The reported size; anything but an int is ignored.

    Raises:
        NetworkError: If the sizes differ.
    """
    if isinstance(size, int) and len(content) != size:
        raise NetworkError(
            f"Downloaded {what} is {len(content)} bytes; GitHub reports {size} "
            "bytes. The download was cut short; try again."
        )
