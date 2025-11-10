"""
HTTP JSON API discovery strategy for NAPT.

This is a VERSION-FIRST strategy that queries JSON API endpoints to get version
and download URL WITHOUT downloading the installer. This enables fast version
checks and efficient caching.

Key Advantages:
- Fast version discovery (API call ~100ms)
- Can skip downloads entirely when version unchanged
- Direct API access for version and download URL
- Support for complex JSON structures with JSONPath
- Custom headers for authentication
- Support for GET and POST requests
- No file parsing required
- Ideal for CI/CD with scheduled checks

Supported Features:
- JSONPath navigation for nested structures
- Array indexing and filtering
- Custom HTTP headers (Authorization, etc.)
- POST requests with JSON body
- Environment variable expansion in values

Use Cases:
- Vendors with JSON APIs (Microsoft, Mozilla, etc.)
- Cloud services with version endpoints
- CDNs that provide metadata APIs
- Applications with update check APIs
- APIs requiring authentication or custom headers
- CI/CD pipelines with frequent version checks

Recipe Configuration:
source:
  strategy: http_json
  api_url: "https://vendor.com/api/latest"
  version_path: "version"                      # JSONPath to version
  download_url_path: "download_url"            # JSONPath to URL
  method: "GET"                                # Optional: GET or POST
  headers:                                     # Optional: custom headers
    Authorization: "Bearer ${API_TOKEN}"
    Accept: "application/json"
  body:                                        # Optional: POST body
    platform: "windows"
    arch: "x64"
  timeout: 30                                  # Optional: timeout in seconds

Configuration Fields:
    - **api_url** (str, required): API endpoint URL that returns JSON with version
      and download information.
    - **version_path** (str, required): JSONPath expression to extract version from
      the API response. Examples: "version", "release.version", "data.version"
    - **download_url_path** (str, required): JSONPath expression to extract download URL
      from the API response. Examples: "download_url", "assets.url", "platforms.windows.x64"
    - **method** (str, optional): HTTP method to use. Either "GET" or "POST". Default is "GET".
    - **headers** (dict, optional): Custom HTTP headers to send with the request. Useful
      for authentication or setting Accept headers. Values support environment variable
      expansion. Example: {"Authorization": "Bearer ${API_TOKEN}"}
    - **body** (dict, optional): Request body for POST requests. Sent as JSON. Only used
      when method="POST". Example: {"platform": "windows", "arch": "x64"}
    - **timeout** (int, optional): Request timeout in seconds. Default is 30.

JSONPath Syntax:
    Simple paths:
      - "version" → {"version": "1.2.3"}
      - "release.version" → {"release": {"version": "1.2.3"}}

    Array indexing:
      - "data.version" → Get from array index
      - "releases.version" → Last item in array

    Nested paths:
      - "data.latest.download.url"
      - "response.assets.browser_download_url"

Workflow (Version-First):
    1. Build HTTP request (GET or POST) with headers
    2. Call API endpoint and get JSON response (~100ms)
    3. Parse JSON and extract version using JSONPath
    4. Extract download URL using JSONPath
    5. Create VersionInfo with version and download URL
    6. Core orchestration compares version to cache
    7. If match and file exists -> skip download entirely
    8. If changed or missing -> download from URL

Error Handling:
    - ValueError: Missing or invalid configuration, invalid JSONPath, path not found
    - RuntimeError: API failures, invalid JSON response
    - Errors are chained with 'from err' for better debugging

Example:
In a recipe YAML (simple API):

    apps:
      - name: "My App"
        id: "my-app"
        source:
          strategy: http_json
          api_url: "https://api.vendor.com/latest"
          version_path: "version"
          download_url_path: "download_url"

In a recipe YAML (nested structure):

    apps:
      - name: "My App"
        id: "my-app"
        source:
          strategy: http_json
          api_url: "https://api.vendor.com/releases"
          version_path: "stable.version"
          download_url_path: "stable.platforms.windows.x64"
          headers:
            Authorization: "Bearer ${API_TOKEN}"

From Python (version-first approach):

    from notapkgtool.discovery.http_json import HttpJsonStrategy
    from notapkgtool.io import download_file

    strategy = HttpJsonStrategy()
    app_config = {
        "source": {
            "api_url": "https://api.vendor.com/latest",
            "version_path": "version",
            "download_url_path": "download_url",
        }
    }

    # Get version WITHOUT downloading
    version_info = strategy.get_version_info(app_config)
    print(f"Latest version: {version_info.version}")

    # Download only if needed
    if need_to_download:
        file_path, sha256, headers = download_file(
            version_info.download_url, Path("./downloads")
        )
        print(f"Downloaded to {file_path}")

From Python (using core orchestration):

    from pathlib import Path
    from notapkgtool.core import discover_recipe

    # Automatically uses version-first optimization
    result = discover_recipe(Path("recipe.yaml"), Path("./downloads"))
    print(f"Version {result['version']} at {result['file_path']}")

Notes:
- Version discovery via API only (no download required)
- Core orchestration automatically skips download if version unchanged
- JSONPath uses jsonpath-ng library for robust parsing
- Environment variable expansion works in headers and other string values
- POST body is sent as JSON (Content-Type: application/json)
- Timeout defaults to 30 seconds to prevent hanging on slow APIs
"""

from __future__ import annotations

import json
import os
from typing import Any

from jsonpath_ng import parse as jsonpath_parse
import requests

from notapkgtool.versioning.keys import VersionInfo

from .base import register_strategy


class HttpJsonStrategy:
    """Discovery strategy for JSON API endpoints.

    Configuration example:
        source:
          strategy: http_json
          api_url: "https://api.vendor.com/latest"
          version_path: "version"
          download_url_path: "download_url"
          method: "GET"
          headers:
            Authorization: "Bearer ${API_TOKEN}"
    """

    def get_version_info(
        self,
        app_config: dict[str, Any],
        verbose: bool = False,
        debug: bool = False,
    ) -> VersionInfo:
        """Query JSON API for version and download URL without downloading (version-first path).

        This method calls a JSON API, extracts version and download URL using
        JSONPath expressions. If the version matches cached state, the download
        can be skipped entirely.

        Args:
            app_config: App configuration containing source.api_url,
                source.version_path, and source.download_url_path.
            verbose: If True, print verbose logging messages.
                Default is False.
            debug: If True, print debug logging messages.
                Default is False.

        Returns:
            Version info with version string, download URL, and
                source name.

        Raises:
            ValueError: If required config fields are missing, invalid, or if
                JSONPath expressions don't match anything in the response.
            RuntimeError: If API call fails (chained with 'from err').

        Example:
            >>> strategy = HttpJsonStrategy()
            >>> config = {
            ...     "source": {
            ...         "api_url": "https://api.vendor.com/latest",
            ...         "version_path": "version",
            ...         "download_url_path": "download_url"
            ...     }
            ... }
            >>> version_info = strategy.get_version_info(config)
            >>> version_info.version
            '1.0.0'
        """
        from notapkgtool.cli import print_verbose

        # Validate configuration
        source = app_config.get("source", {})
        api_url = source.get("api_url")
        if not api_url:
            raise ValueError("http_json strategy requires 'source.api_url' in config")

        version_path = source.get("version_path")
        if not version_path:
            raise ValueError(
                "http_json strategy requires 'source.version_path' in config"
            )

        download_url_path = source.get("download_url_path")
        if not download_url_path:
            raise ValueError(
                "http_json strategy requires 'source.download_url_path' in config"
            )

        # Optional configuration
        method = source.get("method", "GET").upper()
        if method not in ("GET", "POST"):
            raise ValueError(f"Invalid method: {method!r}. Must be 'GET' or 'POST'")

        headers = source.get("headers", {})
        body = source.get("body", {})
        timeout = source.get("timeout", 30)

        print_verbose("DISCOVERY", "Strategy: http_json (version-first)")
        print_verbose("DISCOVERY", f"API URL: {api_url}")
        print_verbose("DISCOVERY", f"Method: {method}")
        print_verbose("DISCOVERY", f"Version path: {version_path}")
        print_verbose("DISCOVERY", f"Download URL path: {download_url_path}")

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
                    print_verbose(
                        "DISCOVERY",
                        f"Warning: Environment variable {env_var} not set",
                    )
                else:
                    expanded_headers[key] = env_value
            else:
                expanded_headers[key] = value

        # Make API request
        print_verbose("DISCOVERY", f"Calling API: {method} {api_url}")
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
            raise RuntimeError(
                f"API request failed: {response.status_code} {response.reason}"
            ) from err
        except requests.exceptions.RequestException as err:
            raise RuntimeError(f"Failed to call API: {err}") from err

        print_verbose("DISCOVERY", f"API response: {response.status_code} OK")

        # Parse JSON response
        try:
            json_data = response.json()
        except json.JSONDecodeError as err:
            raise RuntimeError(
                f"Invalid JSON response from API. Response: {response.text[:200]}"
            ) from err

        if debug:
            print_verbose(
                "DISCOVERY", f"JSON response: {json.dumps(json_data, indent=2)}"
            )

        # Extract version using JSONPath
        print_verbose("DISCOVERY", f"Extracting version from path: {version_path}")
        try:
            version_expr = jsonpath_parse(version_path)
            version_matches = version_expr.find(json_data)

            if not version_matches:
                raise ValueError(
                    f"Version path {version_path!r} did not match anything in API response"
                )

            version_str = str(version_matches[0].value)
        except Exception as err:
            if isinstance(err, ValueError):
                raise
            raise ValueError(
                f"Failed to extract version using path {version_path!r}: {err}"
            ) from err

        print_verbose("DISCOVERY", f"Extracted version: {version_str}")

        # Extract download URL using JSONPath
        print_verbose(
            "DISCOVERY", f"Extracting download URL from path: {download_url_path}"
        )
        try:
            url_expr = jsonpath_parse(download_url_path)
            url_matches = url_expr.find(json_data)

            if not url_matches:
                raise ValueError(
                    f"Download URL path {download_url_path!r} did not match anything in API response"
                )

            download_url = str(url_matches[0].value)
        except Exception as err:
            if isinstance(err, ValueError):
                raise
            raise ValueError(
                f"Failed to extract download URL using path {download_url_path!r}: {err}"
            ) from err

        print_verbose("DISCOVERY", f"Download URL: {download_url}")

        return VersionInfo(
            version=version_str,
            download_url=download_url,
            source="http_json",
        )

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """Validate http_json strategy configuration.

        Checks for required fields and correct types without making network calls.

        Args:
            app_config: The app configuration from the recipe.

        Returns:
            List of error messages (empty if valid).
        """
        errors = []
        source = app_config.get("source", {})

        # Check required fields
        if "api_url" not in source:
            errors.append("Missing required field: source.api_url")
        elif not isinstance(source["api_url"], str):
            errors.append("source.api_url must be a string")
        elif not source["api_url"].strip():
            errors.append("source.api_url cannot be empty")

        if "version_path" not in source:
            errors.append("Missing required field: source.version_path")
        elif not isinstance(source["version_path"], str):
            errors.append("source.version_path must be a string")
        elif not source["version_path"].strip():
            errors.append("source.version_path cannot be empty")
        else:
            # Validate JSONPath syntax
            from jsonpath_ng import parse as jsonpath_parse

            try:
                jsonpath_parse(source["version_path"])
            except Exception as err:
                errors.append(f"Invalid version_path JSONPath: {err}")

        if "download_url_path" not in source:
            errors.append("Missing required field: source.download_url_path")
        elif not isinstance(source["download_url_path"], str):
            errors.append("source.download_url_path must be a string")
        elif not source["download_url_path"].strip():
            errors.append("source.download_url_path cannot be empty")
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
                errors.append("source.method must be a string")
            elif method.upper() not in ["GET", "POST"]:
                errors.append("source.method must be 'GET' or 'POST'")

        if "headers" in source and not isinstance(source["headers"], dict):
            errors.append("source.headers must be a dictionary")

        if "body" in source and not isinstance(source["body"], dict):
            errors.append("source.body must be a dictionary")

        return errors


# Register this strategy when the module is imported
register_strategy("http_json", HttpJsonStrategy)
