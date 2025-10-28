"""
HTTP JSON API discovery strategy for NAPT.

This strategy queries JSON API endpoints to fetch version information and
download URLs dynamically. It's ideal for vendors who provide programmatic
APIs for their latest releases.

Key Advantages
--------------
- Direct API access for version and download URL
- Support for complex JSON structures with JSONPath
- Custom headers for authentication
- Support for GET and POST requests
- No file parsing required before knowing version

Supported Features
------------------
- JSONPath navigation for nested structures
- Array indexing and filtering
- Custom HTTP headers (Authorization, etc.)
- POST requests with JSON body
- Environment variable expansion in values

Use Cases
---------
- Vendors with JSON APIs (Microsoft, Mozilla, etc.)
- Cloud services with version endpoints
- CDNs that provide metadata APIs
- Applications with update check APIs
- APIs requiring authentication or custom headers

Recipe Configuration
--------------------
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

Configuration Fields
--------------------
api_url : str
    API endpoint URL that returns JSON with version and download information.
    This is a required field.

version_path : str
    JSONPath expression to extract version from the API response.
    Examples: "version", "release.version", "[0].version"
    This is a required field.

download_url_path : str
    JSONPath expression to extract download URL from the API response.
    Examples: "download_url", "assets[0].url", "platforms.windows.x64"
    This is a required field.

method : str, optional
    HTTP method to use. Either "GET" or "POST". Default is "GET".

headers : dict, optional
    Custom HTTP headers to send with the request. Useful for authentication
    or setting Accept headers. Values support environment variable expansion.
    Example: {"Authorization": "Bearer ${API_TOKEN}"}

body : dict, optional
    Request body for POST requests. Sent as JSON. Only used when method="POST".
    Example: {"platform": "windows", "arch": "x64"}

timeout : int, optional
    Request timeout in seconds. Default is 30.

JSONPath Syntax
---------------
Simple paths:
  - "version" → {"version": "1.2.3"}
  - "release.version" → {"release": {"version": "1.2.3"}}

Array indexing:
  - "[0].version" → [{"version": "1.2.3"}]
  - "releases[-1].version" → Last item in array

Nested paths:
  - "data.latest.download.url"
  - "response.assets[0].browser_download_url"

Workflow
--------
1. Build HTTP request (GET or POST) with headers
2. Call API endpoint and get JSON response
3. Parse JSON and extract version using JSONPath
4. Extract download URL using JSONPath
5. Download installer using io.download.download_file
6. Return DiscoveredVersion, file path, and SHA-256 hash

Error Handling
--------------
- ValueError: Missing or invalid configuration, invalid JSONPath, path not found
- RuntimeError: API failures, download failures, invalid JSON response
- Errors are chained with 'from err' for better debugging

Example
-------
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

From Python:

    from pathlib import Path
    from notapkgtool.discovery.http_json import HttpJsonStrategy

    strategy = HttpJsonStrategy()
    app_config = {
        "source": {
            "api_url": "https://api.vendor.com/latest",
            "version_path": "version",
            "download_url_path": "download_url",
        }
    }

    discovered, file_path, sha256 = strategy.discover_version(
        app_config, Path("./downloads")
    )
    print(f"Version {discovered.version} downloaded to {file_path}")

Notes
-----
- JSONPath uses jsonpath-ng library for robust parsing
- Environment variable expansion works in headers and other string values
- POST body is sent as JSON (Content-Type: application/json)
- Timeout defaults to 30 seconds to prevent hanging on slow APIs
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from jsonpath_ng import parse as jsonpath_parse

from notapkgtool.io.download import download_file
from notapkgtool.versioning.keys import DiscoveredVersion

from .base import register_strategy


class HttpJsonStrategy:
    """
    Discovery strategy for JSON API endpoints.

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

    def discover_version(
        self,
        app_config: dict[str, Any],
        output_dir: Path,
        verbose: bool = False,
        debug: bool = False,
    ) -> tuple[DiscoveredVersion, Path, str]:
        """
        Query JSON API and download installer from extracted URL.

        This method calls a JSON API, extracts version and download URL using
        JSONPath expressions, then downloads the installer.

        Parameters
        ----------
        app_config : dict
            App configuration containing source.api_url, source.version_path,
            and source.download_url_path.
        output_dir : Path
            Directory to save the downloaded file.
        verbose : bool, optional
            If True, print verbose logging messages. Default is False.
        debug : bool, optional
            If True, print debug logging messages. Default is False.

        Returns
        -------
        tuple[DiscoveredVersion, Path, str]
            Version info, file path to downloaded installer, and SHA-256 hash.

        Raises
        ------
        ValueError
            If required config fields are missing, invalid, or if JSONPath
            expressions don't match anything in the response.
        RuntimeError
            If API call fails or download fails (chained with 'from err').

        Examples
        --------
        Basic usage:

            >>> from pathlib import Path
            >>> strategy = HttpJsonStrategy()
            >>> config = {
            ...     "source": {
            ...         "api_url": "https://api.vendor.com/latest",
            ...         "version_path": "version",
            ...         "download_url_path": "download_url"
            ...     }
            ... }
            >>> discovered, path, sha256 = strategy.discover_version(
            ...     config, Path("./downloads")
            ... )
            >>> discovered.version
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

        print_verbose("DISCOVERY", "Strategy: http_json")
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

        discovered = DiscoveredVersion(version=version_str, source="http_json")

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

        # Download the installer
        print_verbose("DISCOVERY", "Downloading installer...")
        try:
            file_path, sha256, _headers = download_file(
                download_url, output_dir, verbose=verbose, debug=debug
            )
        except Exception as err:
            raise RuntimeError(
                f"Failed to download from {download_url}: {err}"
            ) from err

        print_verbose("DISCOVERY", f"Download complete: {file_path.name}")

        return discovered, file_path, sha256


# Register this strategy when the module is imported
register_strategy("http_json", HttpJsonStrategy)
