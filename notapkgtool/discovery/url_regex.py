"""
URL regex discovery strategy for NAPT.

This strategy extracts version information directly from the download URL using
regular expressions, then downloads the installer. It's ideal for vendors who
encode version numbers in their download URLs, allowing version discovery
without downloading the entire file first.

Key Advantages
--------------
- Fast version discovery (no download required for version check)
- Bandwidth-efficient (can decide whether to download before fetching)
- Works with any file type (MSI, EXE, DMG, etc.)
- No file parsing overhead

Supported Version Extraction
-----------------------------
- regex_in_url: Extract version from URL using a regex pattern
  - Supports named capture groups: (?P<version>...)
  - Falls back to full match if no named group

Use Cases
---------
- Vendors with version-encoded download URLs
  Example: https://vendor.com/app-v1.2.3-installer.msi
- API endpoints that return version-specific download links
  Example: https://api.vendor.com/download/2024.10.28/setup.exe
- URLs with predictable version patterns in the path

Recipe Configuration
--------------------
source:
  strategy: url_regex
  url: "https://vendor.com/downloads/app-v1.2.3-setup.msi"
  version:
    type: regex_in_url
    pattern: "app-v(?P<version>[0-9.]+)-setup"

The pattern supports full Python regex syntax. Use a named capture group
(?P<version>) to extract only the version portion, or let the entire match
be used as the version.

Workflow
--------
1. Extract version from URL using regex pattern
2. Create DiscoveredVersion with extracted version
3. Download the installer from source.url using io.download.download_file
4. Wait for atomic write to complete (.part -> final filename)
5. Return DiscoveredVersion, file path, and SHA-256 hash

Error Handling
--------------
- ValueError: Missing or invalid configuration fields, pattern doesn't match
- RuntimeError: Download failures (chained with 'from err')
- re.error: Invalid regex patterns (propagates from regex compilation)

Comparison with http_static
----------------------------
- url_regex: Extracts version from URL before download
  - Pros: Fast, bandwidth-efficient, file-format agnostic
  - Cons: Requires predictable URL patterns
  - Best for: Version-encoded URLs

- http_static: Downloads file first, then extracts version from file
  - Pros: Works with any URL, accurate version from installer
  - Cons: Must download file to get version
  - Best for: Fixed URLs with embedded version metadata

Example
-------
In a recipe YAML:

    apps:
      - name: "My App"
        id: "my-app"
        source:
          strategy: url_regex
          url: "https://example.com/myapp-v2.1.0-setup.msi"
          version:
            type: regex_in_url
            pattern: "myapp-v(?P<version>[0-9.]+)-setup"

From Python:

    from pathlib import Path
    from notapkgtool.discovery.url_regex import UrlRegexStrategy

    strategy = UrlRegexStrategy()
    app_config = {
        "source": {
            "url": "https://example.com/app-v1.2.3.msi",
            "version": {
                "type": "regex_in_url",
                "pattern": r"app-v(?P<version>[0-9.]+)\.msi",
            },
        }
    }

    discovered, file_path, sha256 = strategy.discover_version(
        app_config, Path("./downloads")
    )
    print(f"Version {discovered.version} downloaded to {file_path}")

Notes
-----
- Version extraction happens BEFORE download for efficiency
- The URL pattern must be stable and predictable
- Pattern matching is case-sensitive by default (use (?i) for case-insensitive)
- Consider http_static if URLs don't contain version information
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from notapkgtool.io.download import download_file
from notapkgtool.versioning.keys import DiscoveredVersion
from notapkgtool.versioning.url_regex import version_from_regex_in_url

from .base import register_strategy


class UrlRegexStrategy:
    """
    Discovery strategy for extracting version from URL patterns.

    Configuration example:
        source:
          strategy: url_regex
          url: "https://vendor.com/app-v1.2.3-installer.msi"
          version:
            type: regex_in_url
            pattern: "app-v(?P<version>[0-9.]+)-installer"
    """

    def discover_version(
        self,
        app_config: dict[str, Any],
        output_dir: Path,
        verbose: bool = False,
        debug: bool = False,
    ) -> tuple[DiscoveredVersion, Path, str]:
        """
        Extract version from URL using regex, then download the file.

        This method extracts the version from the URL BEFORE downloading,
        making it efficient for version checking. The file is then downloaded
        to the output directory.

        Parameters
        ----------
        app_config : dict
            App configuration containing source.url, source.version.type,
            and source.version.pattern.
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
            If required config fields are missing, invalid, or if the regex
            pattern doesn't match the URL.
        RuntimeError
            If download fails (chained with 'from err').

        Examples
        --------
        Basic usage:

            >>> from pathlib import Path
            >>> strategy = UrlRegexStrategy()
            >>> config = {
            ...     "source": {
            ...         "url": "https://vendor.com/app-v1.0.0.msi",
            ...         "version": {
            ...             "type": "regex_in_url",
            ...             "pattern": r"app-v(?P<version>[0-9.]+)\.msi"
            ...         }
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
        url = source.get("url")
        if not url:
            raise ValueError("url_regex strategy requires 'source.url' in config")

        version_config = source.get("version", {})
        version_type = version_config.get("type")
        if not version_type:
            raise ValueError(
                "url_regex strategy requires 'source.version.type' in config"
            )

        if version_type != "regex_in_url":
            raise ValueError(
                f"url_regex strategy requires version.type='regex_in_url', "
                f"got {version_type!r}"
            )

        pattern = version_config.get("pattern")
        if not pattern:
            raise ValueError(
                "url_regex strategy requires 'source.version.pattern' in config"
            )

        print_verbose("DISCOVERY", "Strategy: url_regex")
        print_verbose("DISCOVERY", f"Source URL: {url}")
        print_verbose("DISCOVERY", f"Version extraction: {version_type}")
        print_verbose("DISCOVERY", f"Regex pattern: {pattern}")

        # Extract version from URL (BEFORE download for efficiency)
        try:
            discovered = version_from_regex_in_url(
                url, pattern, verbose=verbose, debug=debug
            )
        except ValueError as err:
            raise ValueError(
                f"Failed to extract version from URL using regex: {err}"
            ) from err

        print_verbose("DISCOVERY", f"Discovered version: {discovered.version}")

        # Now download the file
        print_verbose("DISCOVERY", "Downloading installer...")
        try:
            file_path, sha256, _headers = download_file(
                url, output_dir, verbose=verbose, debug=debug
            )
        except Exception as err:
            raise RuntimeError(f"Failed to download {url}: {err}") from err

        print_verbose("DISCOVERY", f"Download complete: {file_path.name}")

        return discovered, file_path, sha256


# Register this strategy when the module is imported
register_strategy("url_regex", UrlRegexStrategy)

