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

"""JSON API discovery strategy.

Queries a JSON API endpoint for the latest version and download URL.
Both fields are read from the response with dotted paths.

Recipe Example:
    ```yaml
    discovery:
      strategy: api_json
      api_url: "https://vendor.example.com/api/latest"  # required
      version_path: "version"                           # required, dotted path
      download_url_path: "builds[0].url"                # required, dotted path
      version_pattern: "v?([0-9.]+)"                    # optional, regex
      headers:                                          # optional
        Authorization: "Bearer ${API_TOKEN}"            # declared in org.yaml
        Accept: "application/json"
    ```

The [recipe reference](../recipe-reference.md#api_json-strategy) defines
each field.

Note:
    A path is keys separated by dots, with ``[n]`` for a list index:
    ``data.version``, ``builds[0].url``. ``${VAR}`` anywhere in a header
    value is replaced with that environment variable, provided
    ``defaults/org.yaml`` declares it under ``secrets`` and binds it to the
    API host; see [napt.secrets][]. An undeclared or unset variable stops
    discovery before the request is sent.

"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from napt.discovery.base import RemoteVersion, bounded
from napt.discovery.fields import (
    check_regex,
    extract_version,
    fetch,
    optional_str,
    require_str,
)
from napt.exceptions import ConfigError, NetworkError
from napt.logging import get_global_logger
from napt.secrets import bound_hosts, check_secret_use, expand_secrets

# One path segment: a key, followed by any number of list indexes. A key
# cannot hold the characters that would make it a JSONPath operator.
_SEGMENT = r"[^.\[\]$*?@]+(?:\[\d+\])*"
_PATH = re.compile(rf"{_SEGMENT}(?:\.{_SEGMENT})*")
_INDEX = re.compile(r"\[(\d+)\]")


def _check_path(value: str, key: str, errors: list[str]) -> None:
    """Checks that a field's value is a dotted path.

    Args:
        value: The path text.
        key: The field name, for the message.
        errors: List to append errors to.
    """
    if not _PATH.fullmatch(value):
        errors.append(
            f"discovery.{key}: Must be a dotted path such as data.version or "
            f"builds[0].url"
        )


def _lookup(data: Any, path: str, key: str) -> Any:
    """Reads the value at a dotted path in a JSON response.

    Args:
        data: The parsed response.
        path: The path, already validated.
        key: The field the path came from, for the message.

    Returns:
        The value at the path.

    Raises:
        ConfigError: If a key is absent, an index is out of range, or the
            path descends into a value that is not an object or list.
    """
    current = data
    for segment in path.split("."):
        name, *indexes = re.split(r"(?=\[)", segment, maxsplit=1)
        steps: list[str | int] = [name]
        if indexes:
            steps.extend(int(n) for n in _INDEX.findall(indexes[0]))
        for step in steps:
            if isinstance(step, str) and isinstance(current, dict) and step in current:
                current = current[step]
            elif (
                isinstance(step, int)
                and isinstance(current, list)
                and 0 <= step < len(current)
            ):
                current = current[step]
            else:
                raise ConfigError(
                    f"discovery.{key} {path!r} did not match anything in the "
                    f"API response"
                )
    return current


class ApiJsonStrategy:
    """Discovery strategy for JSON API endpoints."""

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"api_url", "version_path", "download_url_path", "version_pattern", "headers"}
    )

    def discover(self, app_config: dict[str, Any]) -> RemoteVersion:
        """Discovers version and download URL from a JSON API endpoint.

        Sends a GET request to the configured ``api_url`` and reads the
        version and download URL at the configured paths.

        Args:
            app_config: Merged and validated recipe configuration dict
                containing ``discovery.api_url``, ``discovery.version_path``,
                and ``discovery.download_url_path``, plus optional
                ``version_pattern`` and ``headers`` fields.

        Returns:
            Discovered version, download URL, and ``"api_json"`` as
            the source identifier.

        Raises:
            ConfigError: On a header secret that org.yaml does not allow for
                the API host or that is not set, when a path does not match
                the response or finds the wrong kind of value, or when
                ``version_pattern`` does not match.
            NetworkError: On API request failure, a redirect that would
                carry a secret off its bound hosts, or a version value too
                long to match a pattern on.

        """
        logger = get_global_logger()
        source = app_config["discovery"]
        api_url: str = source["api_url"]
        version_path: str = source["version_path"]
        download_url_path: str = source["download_url_path"]
        headers = {str(k): str(v) for k, v in (source.get("headers") or {}).items()}

        logger.verbose("DISCOVERY", "Strategy: api_json (version-first)")
        logger.verbose("DISCOVERY", f"API URL: {api_url}")
        logger.verbose("DISCOVERY", f"Version path: {version_path}")
        logger.verbose("DISCOVERY", f"Download URL path: {download_url_path}")

        # Expand secrets in headers; a header org.yaml does not allow for
        # this host, or whose variable is unset, stops discovery here.
        expanded_headers = {
            name: expand_secrets(
                app_config, value, api_url, f"discovery.headers.{name}"
            )
            for name, value in headers.items()
        }
        hosts = bound_hosts(app_config, headers.values())

        logger.verbose("DISCOVERY", f"Calling API: GET {api_url}")
        response = fetch(api_url, what="API", headers=expanded_headers, hosts=hosts)
        logger.verbose("DISCOVERY", f"API response: {response.status_code} OK")

        try:
            json_data = response.json()
        except json.JSONDecodeError as err:
            raise NetworkError(
                f"Invalid JSON response from API. Response: {response.text[:200]}"
            ) from err

        logger.debug("DISCOVERY", f"JSON response: {json.dumps(json_data, indent=2)}")

        version_value = _lookup(json_data, version_path, "version_path")
        if not isinstance(version_value, (str, int, float)) or isinstance(
            version_value, bool
        ):
            raise ConfigError(
                f"discovery.version_path {version_path!r} found "
                f"{type(version_value).__name__} in the API response, not a "
                f"version"
            )
        version_str = bounded(str(version_value), "The API's version value")
        logger.verbose("DISCOVERY", f"Extracted version: {version_str}")

        version_pattern = source.get("version_pattern")
        if version_pattern is not None:
            logger.verbose("DISCOVERY", f"Version pattern: {version_pattern}")
            version_str = extract_version(
                version_pattern, version_str, f"the API's version value {version_str!r}"
            )
            logger.verbose("DISCOVERY", f"Version after pattern: {version_str}")

        download_url = _lookup(json_data, download_url_path, "download_url_path")
        if not isinstance(download_url, str) or not download_url:
            raise ConfigError(
                f"discovery.download_url_path {download_url_path!r} found "
                f"{type(download_url).__name__} in the API response, not a URL"
            )
        logger.verbose("DISCOVERY", f"Download URL: {download_url}")

        return RemoteVersion(
            version=version_str,
            download_url=download_url,
            source="api_json",
        )

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """Validate api_json strategy configuration.

        Checks for required fields and correct types without making network calls.

        Args:
            app_config: The app configuration from the recipe.

        Returns:
            List of error messages (empty if valid).

        """
        errors: list[str] = []
        source = app_config.get("discovery", {})

        api_url = require_str(source, "api_url", errors)
        for key in ("version_path", "download_url_path"):
            path = require_str(source, key, errors)
            if path is not None:
                _check_path(path, key, errors)

        headers = source.get("headers")
        if "headers" in source and not isinstance(headers, dict):
            errors.append("discovery.headers: Must be a dictionary")
        elif isinstance(headers, dict):
            for name, value in headers.items():
                field_path = f"discovery.headers.{name}"
                if not isinstance(value, str):
                    errors.append(f"{field_path}: Must be a string")
                    continue
                errors.extend(
                    check_secret_use(app_config, value, api_url or "", field_path)
                )

        version_pattern = optional_str(source, "version_pattern", errors)
        if version_pattern is not None:
            check_regex(version_pattern, "version_pattern", errors)

        return errors
