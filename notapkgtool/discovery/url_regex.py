"""
URL regex discovery strategy for NAPT.

This is a VERSION-FIRST strategy that extracts version information directly
from the download URL using regular expressions, WITHOUT downloading. This
enables instant version checks and efficient caching.

Key Advantages:
- Instant version discovery (regex only, zero network calls)
- Can skip downloads entirely when version unchanged
- Works with any file type (MSI, EXE, DMG, etc.)
- No file parsing overhead
- Ideal for CI/CD with scheduled checks

Supported Version Extraction:
- regex_in_url: Extract version from URL using a regex pattern
  - Supports named capture groups: (?P<version>...)
  - Falls back to full match if no named group

Use Cases:
- Vendors with version-encoded download URLs
  Example: https://vendor.com/app-v1.2.3-installer.msi
- API endpoints that return version-specific download links
  Example: https://api.vendor.com/download/2024.10.28/setup.exe
- URLs with predictable version patterns in the path
- CI/CD pipelines with frequent version checks

Recipe Configuration:
source:
  strategy: url_regex
  url: "https://vendor.com/downloads/app-v1.2.3-setup.msi"
  version:
    type: regex_in_url
    pattern: "app-v(?P<version>[0-9.]+)-setup"

The pattern supports full Python regex syntax. Use a named capture group
(?P<version>) to extract only the version portion, or let the entire match
be used as the version.

Workflow (Version-First):
    1. Extract version from URL using regex pattern (instant)
    2. Create VersionInfo with version and download URL
    3. Core orchestration compares version to cache
    4. If match and file exists -> skip download entirely
    5. If changed or missing -> download from URL

Error Handling:
    - ValueError: Missing or invalid configuration fields, pattern doesn't match
    - re.error: Invalid regex patterns (propagates from regex compilation)

Architecture (Version-First vs File-First):
    - **url_regex (VERSION-FIRST)**: Extracts version from URL before download
      - Method: get_version_info() -> VersionInfo
      - Pros: Instant checks, can skip downloads when unchanged
      - Cons: Requires predictable URL patterns
      - Best for: Version-encoded URLs, frequent update checks

    - **http_static (FILE-FIRST)**: Downloads file first, then extracts version
      - Method: discover_version() -> tuple with DiscoveredVersion
      - Pros: Works with any URL, accurate version from installer
      - Cons: Must download to know version
      - Best for: Fixed URLs with embedded version metadata

Example:
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

From Python (version-first approach):

    from notapkgtool.discovery.url_regex import UrlRegexStrategy
    from notapkgtool.io import download_file

    strategy = UrlRegexStrategy()
    app_config = {
        "source": {
            "url": "https://example.com/app-v1.2.3.msi",
            "version": {
                "type": "regex_in_url",
                "pattern": r"app-v(?P<version>[0-9.]+)\\.msi",
            },
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
- Version extraction happens WITHOUT download (instant)
- Core orchestration automatically skips download if version unchanged
- The URL pattern must be stable and predictable
- Pattern matching is case-sensitive by default (use (?i) for case-insensitive)
- Consider http_static if URLs don't contain version information
"""

from __future__ import annotations

from typing import Any

from notapkgtool.versioning.keys import VersionInfo
from notapkgtool.versioning.url_regex import version_from_regex_in_url

from .base import register_strategy


class UrlRegexStrategy:
    """Discovery strategy for extracting version from URL patterns.

    Configuration example:
        source:
          strategy: url_regex
          url: "https://vendor.com/app-v1.2.3-installer.msi"
          version:
            type: regex_in_url
            pattern: "app-v(?P<version>[0-9.]+)-installer"
    """

    def get_version_info(
        self,
        app_config: dict[str, Any],
        verbose: bool = False,
        debug: bool = False,
    ) -> VersionInfo:
        """Extract version from URL without downloading (version-first path).

        This method enables fast version checking by extracting the version
        directly from the URL pattern. If the version matches cached state,
        the download can be skipped entirely.

        Args:
            app_config: App configuration containing source.url,
                source.version.type, and source.version.pattern.
            verbose: If True, print verbose logging messages.
                Default is False.
            debug: If True, print debug logging messages.
                Default is False.

        Returns:
            Version info with version string, download URL, and
                source name.

        Raises:
            ValueError: If required config fields are missing, invalid, or if
                the regex pattern doesn't match the URL.

        Example:
            >>> strategy = UrlRegexStrategy()
            >>> config = {
            ...     "source": {
            ...         "url": "https://vendor.com/app-v1.0.0.msi",
            ...         "version": {
            ...             "type": "regex_in_url",
            ...             "pattern": "app-v(?P<version>[0-9.]+)\\\\.msi"
            ...         }
            ...     }
            ... }
            >>> version_info = strategy.get_version_info(config)
            >>> version_info.version
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

        print_verbose("DISCOVERY", "Strategy: url_regex (version-first)")
        print_verbose("DISCOVERY", f"Source URL: {url}")
        print_verbose("DISCOVERY", f"Regex pattern: {pattern}")

        # Extract version from URL (no download needed!)
        try:
            discovered = version_from_regex_in_url(
                url, pattern, verbose=verbose, debug=debug
            )
        except ValueError as err:
            raise ValueError(
                f"Failed to extract version from URL using regex: {err}"
            ) from err

        print_verbose("DISCOVERY", f"Discovered version: {discovered.version}")

        return VersionInfo(
            version=discovered.version,
            download_url=url,
            source="url_regex",
        )

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """Validate url_regex strategy configuration.

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

        if "pattern" not in source:
            errors.append("Missing required field: source.pattern")
        elif not isinstance(source["pattern"], str):
            errors.append("source.pattern must be a string")
        elif not source["pattern"].strip():
            errors.append("source.pattern cannot be empty")
        else:
            # Validate regex pattern syntax
            pattern = source["pattern"]
            if "(?P<version>" not in pattern:
                errors.append(
                    "source.pattern must contain named group (?P<version>...)"
                )
            else:
                # Try to compile the regex to check syntax
                import re

                try:
                    re.compile(pattern)
                except re.error as err:
                    errors.append(f"Invalid regex pattern: {err}")

        return errors


# Register this strategy when the module is imported
register_strategy("url_regex", UrlRegexStrategy)
