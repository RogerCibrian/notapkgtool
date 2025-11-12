# versioning

The versioning module provides version comparison and extraction utilities.

This module defines two key dataclasses for version information:

- **DiscoveredVersion**: Used by file-first strategies (url_download) when version is extracted from downloaded files.
- **VersionInfo**: Used by version-first strategies (web_scrape, api_github, api_json) when version is discovered without downloading.

::: notapkgtool.versioning.keys

::: notapkgtool.versioning.msi

::: notapkgtool.versioning.url_regex

