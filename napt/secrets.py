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

"""Secrets a recipe may send with a discovery request.

A recipe references an environment variable as ``${NAME}`` inside a
``discovery.headers`` value (``api_json``) or the ``discovery.token``
(``api_github``). The variable must be declared under ``secrets:`` in
``defaults/org.yaml`` together with the hosts it may be sent to, the
request must go to one of those hosts, and the URL must use https:

    secrets:
      API_TOKEN:
        hosts: ["api.vendor.com"]

Variables the org file does not declare are unreachable from recipes, so a
recipe (including one imported from elsewhere) cannot pick up the runner's
other secrets such as ``AZURE_CLIENT_SECRET``. The config loader honors the
``secrets`` section from ``defaults/org.yaml`` alone; entries a vendor file,
parent recipe, or recipe adds never reach the merged configuration.

Violations are reported by ``napt validate`` and refused by ``napt
discover`` before any request is made. A request that carries a secret
follows redirects only to the bound hosts, because ``requests`` would
otherwise resend custom headers to whatever host a redirect names. The
host is read with the parser ``requests`` connects with, and a URL whose
host part two parsers could read differently is refused outright.
"""

from __future__ import annotations

from collections.abc import Iterable
import os
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from urllib3.exceptions import LocationParseError
from urllib3.util import parse_url

from napt.exceptions import ConfigError, NetworkError

# A ``${NAME}`` reference; NAME is an environment variable name.
SECRET_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Redirect hops a request carrying a secret may take before giving up.
_MAX_REDIRECTS = 5

# Characters that have no place in a URL's authority and mark the spots
# where URL parsers disagree about where the host ends.
_AMBIGUOUS_AUTHORITY = re.compile(r"[\\\s\x00-\x1f\x7f@]")


def secret_names(value: str) -> list[str]:
    """Lists the environment variables a value references, in order.

    Args:
        value: A header value or token from a recipe.

    Returns:
        Each referenced name once, in order of first appearance.
    """
    names: list[str] = []
    for match in SECRET_REF.finditer(value):
        if match.group(1) not in names:
            names.append(match.group(1))
    return names


def declared_hosts(config: dict[str, Any]) -> dict[str, set[str]]:
    """Reads the hosts each declared secret may be sent to.

    Entries that are not shaped as ``NAME: {hosts: [...]}`` are skipped
    here; validation reports them.

    Args:
        config: Effective configuration, whose ``secrets`` section comes
            from ``defaults/org.yaml`` alone.

    Returns:
        Lower-cased hostnames keyed by variable name.
    """
    section = config.get("secrets")
    if not isinstance(section, dict):
        return {}
    declared: dict[str, set[str]] = {}
    for name, entry in section.items():
        hosts = entry.get("hosts") if isinstance(entry, dict) else None
        if isinstance(hosts, list):
            declared[str(name)] = {
                host.strip().lower()
                for host in hosts
                if isinstance(host, str) and host.strip()
            }
    return declared


def _split(url: str) -> tuple[str, str, str | None]:
    r"""Reads the scheme and host a request for a URL would actually reach.

    The host comes from urllib3's parser, the one ``requests`` connects
    with, rather than from the standard library's, because the two cut the
    authority differently: for ``https://evil.com\@api.vendor.com/`` the
    standard library reports ``api.vendor.com`` while ``requests`` connects
    to ``evil.com``. Any URL whose authority carries user information, a
    backslash, whitespace, or a control character, or that the two parsers
    read differently, is reported as ambiguous so a host check never trusts
    it.

    Args:
        url: The URL to read.

    Returns:
        The lower-cased scheme and host, and a description of what makes
            the URL ambiguous, or None when it is not.
    """
    try:
        parsed = parse_url(url)
    except LocationParseError as err:
        return "", "", f"cannot be parsed ({err})"
    scheme = (parsed.scheme or "").lower()
    host = (parsed.host or "").lower()
    netloc = urlsplit(url).netloc
    if parsed.auth is not None or _AMBIGUOUS_AUTHORITY.search(netloc):
        return (
            scheme,
            host,
            "carries user information, a backslash, whitespace, or a control "
            "character in its host part",
        )
    if (urlsplit(url).hostname or "").lower() != host:
        return scheme, host, "names a host that URL parsers read differently"
    return scheme, host, None


def check_secret_use(
    config: dict[str, Any],
    value: str,
    url: str,
    field_path: str,
) -> list[str]:
    """Checks that a value's secrets may be sent to a URL.

    This is the static half of the rule, shared by ``napt validate`` and
    the discovery strategies: it needs no environment.

    Args:
        config: Effective configuration carrying the ``secrets`` section.
        value: The header value or token as written in the recipe.
        url: The URL the value would be sent to.
        field_path: Recipe field for error messages, such as
            ``discovery.headers.Authorization``.

    Returns:
        Error messages; empty when the value carries no secret or every
        secret is allowed to go to the URL.
    """
    names = secret_names(value)
    if not names:
        return []
    declared = declared_hosts(config)
    scheme, host, ambiguity = _split(url)
    if ambiguity:
        return [
            f"{field_path}: {url!r} {ambiguity}; a URL that carries a secret "
            f"must name its host plainly"
        ]
    errors: list[str] = []
    for name in names:
        hosts = declared.get(name)
        if hosts is None:
            errors.append(
                f"{field_path}: references ${{{name}}}, which defaults/org.yaml "
                f"does not declare under secrets; only declared secrets reach "
                f"a recipe"
            )
        elif host not in hosts:
            errors.append(
                f"{field_path}: Refusing to send secret {name} to "
                f"{host if host else repr(url)}; defaults/org.yaml binds it to "
                f"{', '.join(sorted(hosts))}"
            )
    if scheme != "https":
        errors.append(
            f"{field_path}: {url!r} must use https because the value carries "
            f"a secret"
        )
    return errors


def expand_secrets(
    config: dict[str, Any],
    value: str,
    url: str,
    field_path: str,
) -> str:
    """Replaces each ``${NAME}`` in a value with the environment variable.

    Args:
        config: Effective configuration carrying the ``secrets`` section.
        value: The header value or token as written in the recipe.
        url: The URL the value will be sent to.
        field_path: Recipe field for error messages.

    Returns:
        The value with every reference expanded; a value without
        references is returned unchanged.

    Raises:
        ConfigError: If a referenced variable is undeclared, bound to
            other hosts, would travel over plain http or to an ambiguous
            host, or is not set.
    """
    errors = check_secret_use(config, value, url, field_path)
    if errors:
        raise ConfigError("; ".join(errors))

    def _lookup(match: re.Match[str]) -> str:
        name = match.group(1)
        found = os.environ.get(name)
        if not found:
            raise ConfigError(
                f"{field_path}: secret {name} is declared in defaults/org.yaml "
                f"but not set in the environment"
            )
        return found

    return SECRET_REF.sub(_lookup, value)


def bound_hosts(config: dict[str, Any], values: Iterable[str]) -> set[str] | None:
    """Computes the hosts a request carrying these values may visit.

    Args:
        config: Effective configuration carrying the ``secrets`` section.
        values: The header values or token as written in the recipe.

    Returns:
        The hosts every referenced secret is bound to, or None when the
        values reference no secret and redirects need no guard. An
        undeclared reference, which
        [check_secret_use][napt.secrets.check_secret_use] rejects before
        any request, binds to no host at all.
    """
    names: list[str] = []
    for value in values:
        for name in secret_names(value):
            if name not in names:
                names.append(name)
    if not names:
        return None
    declared = declared_hosts(config)
    allowed: set[str] | None = None
    for name in names:
        hosts = declared.get(name, set())
        allowed = set(hosts) if allowed is None else allowed & hosts
    return allowed or set()


def guarded_get(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    *,
    hosts: set[str] | None,
    timeout: int,
    stream: bool = False,
) -> requests.Response:
    """Sends a GET whose headers may carry secrets.

    Without bound hosts the request follows redirects as ``requests``
    normally does. With them, each redirect is followed by hand and must
    stay on a bound host over https, so the headers never reach anywhere
    ``defaults/org.yaml`` did not allow.

    Args:
        session: The session to send with.
        url: The request URL.
        headers: Request headers, secrets already expanded.
        hosts: The bound hosts from
            [bound_hosts][napt.secrets.bound_hosts], or None.
        timeout: Per-request timeout in seconds.
        stream: Whether to leave the final response's body unread, for a
            caller that reads it in bounded pieces.

    Returns:
        The final response.

    Raises:
        NetworkError: If a redirect leaves the bound hosts, drops to plain
            http, names an ambiguous host, or does not end within a few
            hops.
        requests.RequestException: On transport failure, for the caller to
            wrap with its own context.
    """
    if hosts is None:
        return session.get(url, headers=headers, timeout=timeout, stream=stream)
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        response = session.get(
            current,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            stream=stream,
        )
        if not response.is_redirect:
            return response
        response.close()  # A redirect's body is never read.
        target = urljoin(current, response.headers["Location"])
        scheme, host, ambiguity = _split(target)
        if ambiguity or scheme != "https" or host not in hosts:
            why = (
                f"the target {ambiguity}"
                if ambiguity
                else "the request carries a secret that defaults/org.yaml binds "
                f"to {', '.join(sorted(hosts)) or 'no host'} over https"
            )
            raise NetworkError(
                f"Refusing to follow the redirect from {current} to {target}: " f"{why}"
            )
        current = target
    raise NetworkError(
        f"Too many redirects fetching {url}; gave up after {_MAX_REDIRECTS} hops"
    )
