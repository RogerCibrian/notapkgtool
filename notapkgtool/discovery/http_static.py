"""
HTTP static URL discovery strategy for NAPT.

This strategy downloads an installer from a fixed HTTP(S) URL and extracts
version information directly from the downloaded file. It's the simplest
discovery strategy and works well for vendors who publish installers at
stable URLs.

Supported Version Extraction
-----------------------------
- msi_product_version_from_file: Extract ProductVersion property from MSI
- (Future) exe_file_version: Extract FileVersion from PE headers
- (Future) manual_version: Use a version specified in the recipe

Use Cases
---------
- Google Chrome: Fixed enterprise MSI URL, version embedded in MSI
- Mozilla Firefox: Fixed enterprise MSI URL, version embedded in MSI
- Vendors with stable download URLs and embedded version metadata

Recipe Configuration
--------------------
source:
  strategy: http_static
  url: "https://vendor.com/installer.msi"
  version:
    type: msi_product_version_from_file
    file: "installer.msi"  # Optional, defaults to downloaded filename

Workflow
--------
1. Download the installer from source.url using io.download.download_file
2. Wait for atomic write to complete (.part -> final filename)
3. Extract version based on source.version.type
4. Return DiscoveredVersion, file path, and SHA-256 hash

Error Handling
--------------
- ValueError: Missing or invalid configuration fields
- RuntimeError: Download failures, version extraction errors
- Errors are chained with 'from err' for better debugging

Example
-------
In a recipe YAML:

    apps:
      - name: "My App"
        id: "my-app"
        source:
          strategy: http_static
          url: "https://example.com/myapp-setup.msi"
          version:
            type: msi_product_version_from_file

From Python:

    from pathlib import Path
    from notapkgtool.discovery.http_static import HttpStaticStrategy

    strategy = HttpStaticStrategy()
    app_config = {
        "source": {
            "url": "https://example.com/app.msi",
            "version": {"type": "msi_product_version_from_file"},
        }
    }

    discovered, file_path, sha256 = strategy.discover_version(
        app_config, Path("./downloads")
    )
    print(f"Version {discovered.version} downloaded to {file_path}")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from notapkgtool.io import NotModifiedError, download_file
from notapkgtool.versioning.keys import DiscoveredVersion
from notapkgtool.versioning.msi import version_from_msi_product_version

from .base import register_strategy


class HttpStaticStrategy:
    """
    Discovery strategy for static HTTP(S) URLs.

    Configuration example:
        source:
          strategy: http_static
          url: "https://example.com/installer.msi"
          version:
            type: msi_product_version_from_file
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
        """
        Download from static URL and extract version from the file.

        Parameters
        ----------
        app_config : dict
            App configuration containing source.url and source.version.
        output_dir : Path
            Directory to save the downloaded file.
        cache : dict, optional
            Cached state with etag, last_modified, file_path, and sha256
            for conditional requests. If provided and file is unchanged
            (HTTP 304), the cached file is returned.

        Returns
        -------
        tuple[DiscoveredVersion, Path, str, dict]
            Version info, file path, SHA-256 hash, and HTTP response headers.

        Raises
        ------
        ValueError
            If required config fields are missing or invalid.
        RuntimeError
            If download or version extraction fails.
        """
        from notapkgtool.cli import print_verbose

        source = app_config.get("source", {})
        url = source.get("url")
        if not url:
            raise ValueError("http_static strategy requires 'source.url' in config")

        version_config = source.get("version", {})
        version_type = version_config.get("type")
        if not version_type:
            raise ValueError(
                "http_static strategy requires 'source.version.type' in config"
            )

        print_verbose("DISCOVERY", "Strategy: http_static")
        print_verbose("DISCOVERY", f"Source URL: {url}")
        print_verbose("DISCOVERY", f"Version extraction: {version_type}")

        # Extract ETag/Last-Modified from cache if available
        etag = cache.get("etag") if cache else None
        last_modified = cache.get("last_modified") if cache else None

        if etag:
            print_verbose("DISCOVERY", f"Using cached ETag: {etag}")
        if last_modified:
            print_verbose("DISCOVERY", f"Using cached Last-Modified: {last_modified}")

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
            print_verbose("DISCOVERY", "File not modified (HTTP 304), using cached version")

            if not cache or "file_path" not in cache or "sha256" not in cache:
                raise RuntimeError(
                    "Cache indicates file not modified, but missing cached file info. "
                    "Try running with --stateless to force re-download."
                )

            cached_file = Path(cache["file_path"])
            if not cached_file.exists():
                raise RuntimeError(
                    f"Cached file {cached_file} not found. "
                    f"File may have been deleted. Try running with --stateless."
                )

            # Extract version from cached file
            if version_type == "msi_product_version_from_file":
                try:
                    discovered = version_from_msi_product_version(
                        cached_file, verbose=verbose, debug=debug
                    )
                except Exception as err:
                    raise RuntimeError(
                        f"Failed to extract MSI ProductVersion from cached file {cached_file}: {err}"
                    ) from err
            else:
                raise ValueError(
                    f"Unsupported version type: {version_type!r}. "
                    f"Supported: msi_product_version_from_file"
                )

            # Return cached info with empty headers (no new download occurred)
            return discovered, cached_file, cache["sha256"], {}
        except Exception as err:
            if isinstance(err, (RuntimeError, ValueError)):
                raise
            raise RuntimeError(f"Failed to download {url}: {err}") from err

        # File was downloaded (not cached), extract version from it
        if version_type == "msi_product_version_from_file":
            try:
                discovered = version_from_msi_product_version(
                    file_path, verbose=verbose, debug=debug
                )
            except Exception as err:
                raise RuntimeError(
                    f"Failed to extract MSI ProductVersion from {file_path}: {err}"
                ) from err
        else:
            raise ValueError(
                f"Unsupported version type: {version_type!r}. "
                f"Supported: msi_product_version_from_file"
            )

        return discovered, file_path, sha256, headers

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """
        Validate http_static strategy configuration.
        
        Checks for required fields and correct types without making network calls.
        
        Parameters
        ----------
        app_config : dict
            The app configuration from the recipe.
        
        Returns
        -------
        list[str]
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
                supported_types = ["msi_product_version_from_file"]
                if version_type not in supported_types:
                    errors.append(
                        f"Unsupported source.version.type: {version_type!r}. "
                        f"Supported: {', '.join(supported_types)}"
                    )
        
        return errors


# Register this strategy when the module is imported
register_strategy("http_static", HttpStaticStrategy)
