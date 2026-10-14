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

"""Field checks and the request helper the discovery strategies share.

Every strategy's ``validate_config`` reports the same three things about a
field (missing, wrong type, empty) and compiles the same kinds of pattern,
and every version-first strategy fetches one URL the same way. Those live
here so each strategy holds only its own rules, and so a message about
``discovery.repo`` reads like the messages [napt.validation][] produces for
every other section.

Validation runs before any ``discover`` method is called: the config
loader validates the merged configuration and refuses to continue on any
error. A ``discover`` method therefore reads its fields directly and
checks only what the remote data turns out to be.
"""

from __future__ import annotations

import re
import string
from typing import Any

import requests

from napt.discovery.base import first_capture
from napt.download.download import make_session
from napt.exceptions import ConfigError, NetworkError
from napt.secrets import guarded_get

# Seconds allowed for a discovery request.
_REQUEST_TIMEOUT = 30


def require_str(source: dict[str, Any], key: str, errors: list[str]) -> str | None:
    """Checks that a required field is present and a non-empty string.

    Args:
        source: The ``discovery`` section.
        key: The field name.
        errors: List to append errors to.

    Returns:
        The value when it passes, otherwise None.
    """
    if key not in source:
        errors.append(f"discovery: Missing required field: {key}")
        return None
    return optional_str(source, key, errors)


def optional_str(source: dict[str, Any], key: str, errors: list[str]) -> str | None:
    """Checks that a field, when present, is a non-empty string.

    Args:
        source: The ``discovery`` section.
        key: The field name.
        errors: List to append errors to.

    Returns:
        The value when present and valid, otherwise None.
    """
    if key not in source:
        return None
    value = source[key]
    if not isinstance(value, str):
        errors.append(f"discovery.{key}: Must be a string")
        return None
    if not value.strip():
        errors.append(f"discovery.{key}: Must be a non-empty string")
        return None
    return value


def check_regex(value: str, key: str, errors: list[str]) -> None:
    """Checks that a field's value compiles as a regular expression.

    Args:
        value: The pattern text.
        key: The field name, for the message.
        errors: List to append errors to.
    """
    try:
        re.compile(value)
    except re.error as err:
        errors.append(f"discovery.{key}: Invalid regex: {err}")


def check_format(value: str, key: str, errors: list[str]) -> None:
    """Checks that a field's value is a format string over capture groups.

    The groups are passed by position, so every replacement field must be
    a number (``{0}``, ``{1}``) or empty (``{}``); a named field would
    fail at discovery time.

    Args:
        value: The format string.
        key: The field name, for the message.
        errors: List to append errors to.
    """
    try:
        fields = [
            name
            for _, name, _, _ in string.Formatter().parse(value)
            if name is not None
        ]
    except ValueError as err:
        errors.append(f"discovery.{key}: Invalid format string: {err}")
        return
    bad = [name for name in fields if name and not name.isdigit()]
    if bad:
        errors.append(
            f"discovery.{key}: Invalid format string: capture groups are "
            f"numbered, so use {{0}}, {{1}}, ... rather than {{{bad[0]}}}"
        )


def fetch(
    url: str,
    *,
    what: str,
    headers: dict[str, str] | None = None,
    hosts: set[str] | None = None,
) -> requests.Response:
    """Fetches a URL for a strategy and checks the response succeeded.

    Args:
        url: The URL to fetch.
        what: What is being fetched, for messages (``"page"``, ``"API"``).
        headers: Request headers, secrets already expanded.
        hosts: The hosts a redirect may go to when the headers carry a
            secret, from [bound_hosts][napt.secrets.bound_hosts]; None
            follows redirects freely.

    Returns:
        The successful response.

    Raises:
        NetworkError: On transport failure, a redirect off the bound hosts,
            or a status that is not success.
    """
    try:
        with make_session() as session:
            return _get(session, url, what, headers, hosts, stream=False)
    except requests.RequestException as err:
        raise NetworkError(f"Failed to fetch {what}: {err}") from err


def fetch_text(
    url: str,
    *,
    what: str,
    max_bytes: int,
    headers: dict[str, str] | None = None,
    hosts: set[str] | None = None,
) -> str:
    """Fetches a text document for a strategy, refusing one over a size cap.

    The body is read in pieces and the download stops as soon as it passes
    ``max_bytes``, so a URL that points at a large file is refused without
    downloading it. A Content-Length header over the cap is refused before
    any of the body is read.

    Args:
        url: The URL to fetch.
        what: What is being fetched, for messages (``"page"``).
        max_bytes: The largest body to accept.
        headers: Request headers, secrets already expanded.
        hosts: The hosts a redirect may go to when the headers carry a
            secret, from [bound_hosts][napt.secrets.bound_hosts]; None
            follows redirects freely.

    Returns:
        The document, decoded with the charset the response declares
            (UTF-8 when it declares none).

    Raises:
        NetworkError: On transport failure, a redirect off the bound hosts,
            a status that is not success, or a body over ``max_bytes``.
    """
    too_large = NetworkError(
        f"The {what} at {url} is larger than {max_bytes} bytes, more than NAPT "
        f"reads for a download {what}. Check that the URL is the HTML {what} "
        "itself and not an installer file."
    )
    try:
        with make_session() as session:
            response = _get(session, url, what, headers, hosts, stream=True)
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise too_large
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise too_large
    except requests.RequestException as err:
        raise NetworkError(f"Failed to fetch {what}: {err}") from err
    try:
        return body.decode(response.encoding or "utf-8", errors="replace")
    except LookupError:
        # The server named a charset Python does not know.
        return body.decode("utf-8", errors="replace")


def _get(
    session: requests.Session,
    url: str,
    what: str,
    headers: dict[str, str] | None,
    hosts: set[str] | None,
    *,
    stream: bool,
) -> requests.Response:
    """Sends the GET for a fetch and checks the status.

    Args:
        session: The session to send with.
        url: The URL to fetch.
        what: What is being fetched, for messages.
        headers: Request headers, secrets already expanded.
        hosts: The hosts a redirect may go to, or None.
        stream: Whether to leave the body unread for the caller.

    Returns:
        The successful response.

    Raises:
        NetworkError: On a redirect off the bound hosts or a status that is
            not success.
        requests.RequestException: On transport failure, for the caller to
            wrap with its own context.
    """
    response = guarded_get(
        session,
        url,
        headers or {},
        hosts=hosts,
        timeout=_REQUEST_TIMEOUT,
        stream=stream,
    )
    if not response.ok:
        raise NetworkError(
            f"Failed to fetch {what}: {response.status_code} {response.reason}"
        )
    return response


def extract_version(pattern_text: str, text: str, what: str) -> str:
    """Reads the version a recipe pattern captures from a remote string.

    Args:
        pattern_text: The recipe's ``version_pattern``, already validated.
        text: The string to search, already bounded.
        what: What the string is, for the message (``"tag 'v1.2'"``).

    Returns:
        Capture group 1 when the pattern has one, otherwise the whole
        match.

    Raises:
        ConfigError: If the pattern does not match, or a capture group took
            no part in the match.
    """
    captured = first_capture(re.compile(pattern_text), text)
    if captured is None:
        raise ConfigError(f"Version pattern {pattern_text!r} did not match {what}")
    return captured
