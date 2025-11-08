# Versioning Module

The versioning module provides version comparison and extraction utilities.

This module defines two key dataclasses for version information:

- **DiscoveredVersion**: Used by file-first strategies (http_static) when version is extracted from downloaded files.
- **VersionInfo**: Used by version-first strategies (url_regex, github_release, http_json) when version is discovered without downloading.

## Version Comparison

::: notapkgtool.versioning.keys
    options:
      show_root_heading: true
      show_source: true

## MSI Version Extraction

::: notapkgtool.versioning.msi
    options:
      show_root_heading: true
      show_source: true

## URL Regex Extraction

::: notapkgtool.versioning.url_regex
    options:
      show_root_heading: true
      show_source: true

