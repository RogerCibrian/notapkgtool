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

"""URL download discovery strategy for NAPT.

This is a FILE-FIRST strategy that downloads an installer from a fixed HTTP(S)
URL and extracts version information from the downloaded file. Uses HTTP ETag
conditional requests to avoid re-downloading unchanged files.

Key Advantages:

- Works with any fixed URL (version not required in URL)
- Extracts accurate version directly from installer metadata
- Uses ETag-based conditional requests for efficiency (~500ms vs full download)
- Simple and reliable for vendors with stable download URLs
- Fallback strategy when version not available via API/URL pattern

Supported Version Extraction:

- msi: Extract ProductVersion property from MSI files
- (Future) exe: Extract FileVersion from PE headers
- (Future) manual: Use a version specified in the recipe

Use Cases:

- Google Chrome: Fixed enterprise MSI URL, version embedded in MSI
- Mozilla Firefox: Fixed enterprise MSI URL, version embedded in MSI
- Vendors with stable download URLs and embedded version metadata
- When version not available via API, URL pattern, or GitHub tags

Recipe Configuration:

    source:
      strategy: url_download
      url: "https://vendor.com/installer.msi"          # Required: download URL
      version:
        type: msi                                      # Required: extraction method
        file: "installer.msi"  # Optional: defaults to URL filename

Configuration Fields:

- **url** (str, required): HTTP(S) URL to download the installer from. The URL
    should be stable and point to the latest version.
- **version.type** (str, required): Version extraction method. Currently
    supported: msi.
- **version.file** (str, optional): Specific filename to extract version from.
    Defaults to the downloaded filename derived from the URL or
    Content-Disposition header.

Error Handling:

- ConfigError: Missing or invalid configuration fields
- NetworkError: Download failures, version extraction errors
- Errors are chained with 'from err' for better debugging

Example:
    In a recipe YAML:
        ```yaml
        apps:
          - name: "My App"
            id: "my-app"
            source:
              strategy: url_download
              url: "https://example.com/myapp-setup.msi"
              version:
                type: msi
        ```

    From Python:
    ```python
    from pathlib import Path
    from notapkgtool.discovery.url_download import UrlDownloadStrategy

    strategy = UrlDownloadStrategy()
    app_config = {
        "source": {
            "url": "https://example.com/app.msi",
            "version": {"type": "msi"},
        }
    }

    # With cache for ETag optimization
    cache = {"etag": 'W/"abc123"', "sha256": "..."}
    discovered, file_path, sha256, headers = strategy.discover_version(
        app_config, Path("./downloads"), cache=cache
    )
    print(f"Version {discovered.version} at {file_path}")
    ```

From Python (using core orchestration):
    ```python
    from pathlib import Path
    from notapkgtool.core import discover_recipe

    # Automatically uses ETag optimization
    result = discover_recipe(Path("recipe.yaml"), Path("./downloads"))
    print(f"Version {result.version} at {result.file_path}")
    ```

Note:
    - Must download file to extract version (architectural constraint)
    - ETag optimization reduces bandwidth but still requires network round-trip
    - Core orchestration automatically provides cached ETag if available
    - Server must support ETag or Last-Modified headers for optimization
    - If server doesn't support conditional requests, full download occurs every time
    - Consider version-first strategies (web_scrape, api_github, api_json) for
      better performance when version available via web scraping or API

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from notapkgtool.exceptions import ConfigError, NetworkError
from notapkgtool.io import NotModifiedError, download_file
from notapkgtool.versioning.keys import DiscoveredVersion
from notapkgtool.versioning.msi import version_from_msi_product_version

from .base import register_strategy


class UrlDownloadStrategy:
    """Discovery strategy for static HTTP(S) URLs.

    Configuration example:
        source:
          strategy: url_download
          url: "https://example.com/installer.msi"
          version:
            type: msi
            file: "installer.msi"
    """

    def discover_version(
        self,
        app_config: dict[str, Any],
        output_dir: Path,
        cache: dict[str, Any] | None = None,
        verbose: bool = False,
        debug: bool = False,
    ) -> tuple[DiscoveredVersion, Path, str, dict]:
        """Download from static URL and extract version from the file.

        Args:
            app_config: App configuration containing source.url and
                source.version.
            output_dir: Directory to save the downloaded file.
            cache: Cached state with etag, last_modified,
                file_path, and sha256 for conditional requests. If provided
                and file is unchanged (HTTP 304), the cached file is returned.
            verbose: If True, print verbose logging messages.
                Default is False.
            debug: If True, print debug logging messages.
                Default is False.

        Returns:
            A tuple (version_info, file_path, sha256, headers), where
                version_info contains the discovered version information,
                file_path is the Path to the downloaded file, sha256 is the
                SHA-256 hash, and headers contains HTTP response headers.

        Raises:
            ConfigError: If required config fields are missing or invalid.
            NetworkError: If download or version extraction fails.

        """
        from notapkgtool.logging import get_global_logger

        logger = get_global_logger()
        source = app_config.get("source", {})
        url = source.get("url")
        if not url:
            raise ConfigError("url_download strategy requires 'source.url' in config")

        version_config = source.get("version", {})
        version_type = version_config.get("type")
        if not version_type:
            raise ConfigError(
                "url_download strategy requires 'source.version.type' in config"
            )

        logger.verbose("DISCOVERY", "Strategy: url_download (file-first)")
        logger.verbose("DISCOVERY", f"Source URL: {url}")
        logger.verbose("DISCOVERY", f"Version extraction: {version_type}")

        # Extract ETag/Last-Modified from cache if available
        etag = cache.get("etag") if cache else None
        last_modified = cache.get("last_modified") if cache else None

        if etag:
            logger.verbose("DISCOVERY", f"Using cached ETag: {etag}")
        if last_modified:
            logger.verbose("DISCOVERY", f"Using cached Last-Modified: {last_modified}")

        # Download the file (with conditional request if cache available)
        try:
            file_path, sha256, headers = download_file(
                url,
                output_dir,
                etag=etag,
                last_modified=last_modified,
                verbose=verbose,
                debug=debug,
            )
        except NotModifiedError:
            # File unchanged (HTTP 304), use cached version
            # Use convention-based path: derive filename from URL
            logger.verbose(
                "DISCOVERY", "File not modified (HTTP 304), using cached version"
            )

            if not cache or "sha256" not in cache:
                raise NetworkError(
                    "Cache indicates file not modified, but missing SHA-256. "
                    "Try running with --stateless to force re-download."
                ) from None

            # Derive file path from URL (convention-based, schema v2)
            from urllib.parse import urlparse

            filename = Path(urlparse(url).path).name
            cached_file = output_dir / filename

            if not cached_file.exists():
                raise NetworkError(
                    f"Cached file {cached_file} not found. "
                    f"File may have been deleted. Try running with --stateless."
                ) from None

            # Extract version from cached file
            if version_type == "msi":
                try:
                    discovered = version_from_msi_product_version(
                        cached_file, verbose=verbose, debug=debug
                    )
                except Exception as err:
                    raise NetworkError(
                        f"Failed to extract MSI ProductVersion from cached "
                        f"file {cached_file}: {err}"
                    ) from err
            else:
                raise ConfigError(
                    f"Unsupported version type: {version_type!r}. " f"Supported: msi"
                ) from None

            # Return cached info with preserved headers (prevents overwriting ETag)
            # When 304, no new headers received, so return cached values to
            # preserve them
            preserved_headers = {}
            if cache.get("etag"):
                preserved_headers["ETag"] = cache["etag"]
            if cache.get("last_modified"):
                preserved_headers["Last-Modified"] = cache["last_modified"]

            return discovered, cached_file, cache["sha256"], preserved_headers
        except Exception as err:
            if isinstance(err, (NetworkError, ConfigError)):
                raise
            raise NetworkError(f"Failed to download {url}: {err}") from err

        # File was downloaded (not cached), extract version from it
        if version_type == "msi":
            try:
                discovered = version_from_msi_product_version(
                    file_path, verbose=verbose, debug=debug
                )
            except Exception as err:
                raise NetworkError(
                    f"Failed to extract MSI ProductVersion from {file_path}: {err}"
                ) from err
        else:
            raise ConfigError(
                f"Unsupported version type: {version_type!r}. " f"Supported: msi"
            )

        return discovered, file_path, sha256, headers

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """Validate url_download strategy configuration.

        Checks for required fields and correct types without making network calls.

        Args:
            app_config: The app configuration from the recipe.

        Returns:
            List of error messages (empty if valid).

        """
        errors = []
        source = app_config.get("source", {})

        # Check required fields
        if "url" not in source:
            errors.append("Missing required field: source.url")
        elif not isinstance(source["url"], str):
            errors.append("source.url must be a string")
        elif not source["url"].strip():
            errors.append("source.url cannot be empty")

        # Check version configuration
        if "version" not in source:
            errors.append("Missing required field: source.version")
        elif not isinstance(source["version"], dict):
            errors.append("source.version must be a dictionary")
        else:
            version_config = source["version"]

            # Check version.type
            if "type" not in version_config:
                errors.append("Missing required field: source.version.type")
            elif not isinstance(version_config["type"], str):
                errors.append("source.version.type must be a string")
            else:
                version_type = version_config["type"]
                supported_types = ["msi"]
                if version_type not in supported_types:
                    errors.append(
                        f"Unsupported source.version.type: {version_type!r}. "
                        f"Supported: {', '.join(supported_types)}"
                    )

        return errors


# Register this strategy when the module is imported
register_strategy("url_download", UrlDownloadStrategy)
