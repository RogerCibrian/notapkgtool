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

from notapkgtool.io.download import download_file
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
        verbose: bool = False,
        debug: bool = False,
    ) -> tuple[DiscoveredVersion, Path, str]:
        """
        Download from static URL and extract version from the file.

        Parameters
        ----------
        app_config : dict
            App configuration containing source.url and source.version.
        output_dir : Path
            Directory to save the downloaded file.

        Returns
        -------
        tuple[DiscoveredVersion, Path, str]
            Version info, file path, and SHA-256 hash.

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

        # Download the file
        try:
            file_path, sha256, _headers = download_file(
                url, output_dir, verbose=verbose, debug=debug
            )
        except Exception as err:
            raise RuntimeError(f"Failed to download {url}: {err}") from err

        # Extract version based on type
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

        return discovered, file_path, sha256


# Register this strategy when the module is imported
register_strategy("http_static", HttpStaticStrategy)
