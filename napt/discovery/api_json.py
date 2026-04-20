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
Both fields are extracted from the response using JSONPath expressions.

Recipe Example:
    ```yaml
    discovery:
      strategy: api_json
      api_url: "https://vendor.example.com/api/latest"  # required
      version_path: "version"                           # required, JSONPath
      download_url_path: "download_url"                 # required, JSONPath
      method: "GET"                                     # optional, GET or POST
      headers:                                          # optional
        Authorization: "Bearer ${API_TOKEN}"
        Accept: "application/json"
      body:                                             # optional, POST only
        platform: "windows"
        arch: "x64"
      timeout: 30                                       # optional, seconds
    ```

    Nested response, with auth header:
    ```yaml
    discovery:
      strategy: api_json
      api_url: "https://vendor.example.com/api/releases"
      version_path: "stable.version"
      download_url_path: "stable.platforms.windows.x64"
      headers:
        Authorization: "Bearer ${API_TOKEN}"
    ```

Configuration Fields:
    - **api_url** (required): JSON endpoint URL.
    - **version_path** (required): JSONPath expression locating the
        version string in the response (e.g. ``"version"``,
        ``"release.version"``).
    - **download_url_path** (required): JSONPath expression locating
        the installer download URL in the response.
    - **method** (optional, default ``"GET"``): ``"GET"`` or ``"POST"``.
    - **headers** (optional): HTTP headers to send. Values support
        ``${ENV_VAR}`` expansion.
    - **body** (optional): Dict sent as a JSON body. Only used when
        ``method: POST``.
    - **timeout** (optional, default 30): Request timeout in seconds.

Note:
    JSONPath uses the ``jsonpath-ng`` library. Environment-variable
    expansion (``${VAR}``) is applied to string values in ``headers``.
    POST bodies are always sent as ``application/json``.

"""

from __future__ import annotations

import json
import os
from typing import Any

from jsonpath_ng import parse as jsonpath_parse
import requests

from napt.discovery.base import RemoteVersion
from napt.exceptions import ConfigError, NetworkError

from .base import register_strategy

# Strategy-specific defaults for optional recipe fields.
_DEFAULT_METHOD = "GET"
_DEFAULT_TIMEOUT = 30


class ApiJsonStrategy:
    """Discovery strategy for JSON API endpoints."""

    def discover(self, app_config: dict[str, Any]) -> RemoteVersion:
        """Discovers version and download URL from a JSON API endpoint.

        Calls the configured ``api_url`` and extracts the version and
        download URL using JSONPath expressions. The HTTP method,
        headers, and body are configurable so the same strategy works
        for GET and POST endpoints.

        Args:
            app_config: Merged recipe configuration dict containing
                ``discovery.api_url``, ``discovery.version_path``, and
                ``discovery.download_url_path``, plus optional
                ``method``, ``headers``, and ``body`` fields.

        Returns:
            Discovered version, download URL, and ``"api_json"`` as
            the source identifier.

        Raises:
            ConfigError: On missing required configuration or when
                the JSONPath expressions do not match the response.
            NetworkError: On API request failure.

        """
        from napt.logging import get_global_logger

        logger = get_global_logger()
        # Validate configuration
        source = app_config.get("discovery", {})
        api_url = source.get("api_url")
        if not api_url:
            raise ConfigError(
                "api_json strategy requires 'discovery.api_url' in config"
            )

        version_path = source.get("version_path")
        if not version_path:
            raise ConfigError(
                "api_json strategy requires 'discovery.version_path' in config"
            )

        download_url_path = source.get("download_url_path")
        if not download_url_path:
            raise ConfigError(
                "api_json strategy requires 'discovery.download_url_path' in config"
            )

        # Optional configuration
        method = source.get("method", _DEFAULT_METHOD).upper()
        if method not in ("GET", "POST"):
            raise ConfigError(f"Invalid method: {method!r}. Must be 'GET' or 'POST'")

        headers = source.get("headers", {})
        body = source.get("body", {})
        timeout = source.get("timeout", _DEFAULT_TIMEOUT)

        logger.verbose("DISCOVERY", "Strategy: api_json (version-first)")
        logger.verbose("DISCOVERY", f"API URL: {api_url}")
        logger.verbose("DISCOVERY", f"Method: {method}")
        logger.verbose("DISCOVERY", f"Version path: {version_path}")
        logger.verbose("DISCOVERY", f"Download URL path: {download_url_path}")

        # Expand environment variables in headers
        expanded_headers = {}
        for key, value in headers.items():
            if (
                isinstance(value, str)
                and value.startswith("${")
                and value.endswith("}")
            ):
                env_var = value[2:-1]
                env_value = os.environ.get(env_var)
                if not env_value:
                    logger.verbose(
                        "DISCOVERY",
                        f"Warning: Environment variable {env_var} not set",
                    )
                else:
                    expanded_headers[key] = env_value
            else:
                expanded_headers[key] = value

        # Make API request
        logger.verbose("DISCOVERY", f"Calling API: {method} {api_url}")
        try:
            if method == "GET":
                response = requests.get(
                    api_url, headers=expanded_headers, timeout=timeout
                )
            else:  # POST
                response = requests.post(
                    api_url,
                    headers=expanded_headers,
                    json=body,
                    timeout=timeout,
                )
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            raise NetworkError(
                f"API request failed: {response.status_code} {response.reason}"
            ) from err
        except requests.exceptions.RequestException as err:
            raise NetworkError(f"Failed to call API: {err}") from err

        logger.verbose("DISCOVERY", f"API response: {response.status_code} OK")

        # Parse JSON response
        try:
            json_data = response.json()
        except json.JSONDecodeError as err:
            raise NetworkError(
                f"Invalid JSON response from API. Response: {response.text[:200]}"
            ) from err

        logger.debug("DISCOVERY", f"JSON response: {json.dumps(json_data, indent=2)}")

        # Extract version using JSONPath
        logger.verbose("DISCOVERY", f"Extracting version from path: {version_path}")
        try:
            version_expr = jsonpath_parse(version_path)
            version_matches = version_expr.find(json_data)

            if not version_matches:
                raise ConfigError(
                    f"Version path {version_path!r} did not match anything "
                    f"in API response"
                )

            version_str = str(version_matches[0].value)
        except Exception as err:
            if isinstance(err, ConfigError):
                raise
            raise ConfigError(
                f"Failed to extract version using path {version_path!r}: {err}"
            ) from err

        logger.verbose("DISCOVERY", f"Extracted version: {version_str}")

        # Extract download URL using JSONPath
        logger.verbose(
            "DISCOVERY", f"Extracting download URL from path: {download_url_path}"
        )
        try:
            url_expr = jsonpath_parse(download_url_path)
            url_matches = url_expr.find(json_data)

            if not url_matches:
                raise ConfigError(
                    f"Download URL path {download_url_path!r} did not match "
                    f"anything in API response"
                )

            download_url = str(url_matches[0].value)
        except Exception as err:
            if isinstance(err, ConfigError):
                raise
            raise ConfigError(
                f"Failed to extract download URL using path "
                f"{download_url_path!r}: {err}"
            ) from err

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
        errors = []
        source = app_config.get("discovery", {})

        # Check required fields
        if "api_url" not in source:
            errors.append("Missing required field: discovery.api_url")
        elif not isinstance(source["api_url"], str):
            errors.append("discovery.api_url must be a string")
        elif not source["api_url"].strip():
            errors.append("discovery.api_url cannot be empty")

        if "version_path" not in source:
            errors.append("Missing required field: discovery.version_path")
        elif not isinstance(source["version_path"], str):
            errors.append("discovery.version_path must be a string")
        elif not source["version_path"].strip():
            errors.append("discovery.version_path cannot be empty")
        else:
            # Validate JSONPath syntax
            from jsonpath_ng import parse as jsonpath_parse

            try:
                jsonpath_parse(source["version_path"])
            except Exception as err:
                errors.append(f"Invalid version_path JSONPath: {err}")

        if "download_url_path" not in source:
            errors.append("Missing required field: discovery.download_url_path")
        elif not isinstance(source["download_url_path"], str):
            errors.append("discovery.download_url_path must be a string")
        elif not source["download_url_path"].strip():
            errors.append("discovery.download_url_path cannot be empty")
        else:
            # Validate JSONPath syntax
            from jsonpath_ng import parse as jsonpath_parse

            try:
                jsonpath_parse(source["download_url_path"])
            except Exception as err:
                errors.append(f"Invalid download_url_path JSONPath: {err}")

        # Optional fields validation
        if "method" in source:
            method = source["method"]
            if not isinstance(method, str):
                errors.append("discovery.method must be a string")
            elif method.upper() not in ["GET", "POST"]:
                errors.append("discovery.method must be 'GET' or 'POST'")

        if "headers" in source and not isinstance(source["headers"], dict):
            errors.append("discovery.headers must be a dictionary")

        if "body" in source and not isinstance(source["body"], dict):
            errors.append("discovery.body must be a dictionary")

        return errors


# Register this strategy when the module is imported
register_strategy("api_json", ApiJsonStrategy)
