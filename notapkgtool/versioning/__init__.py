"""
Version comparison and extraction utilities for NAPT.

This package provides tools for comparing version strings and extracting
version information from binary files (MSI, EXE). It supports multiple
comparison strategies and handles various versioning schemes including
semantic versioning, numeric versions, and prerelease tags.

Modules
-------
keys : module
    Core version comparison logic with semver-like parsing and robust fallbacks.
msi : module
    MSI ProductVersion extraction using msilib, _msi, PowerShell, or msitools.
url_regex : module
    Extract versions from URLs using regex patterns.

Public API
----------
DiscoveredVersion : dataclass
    Container for discovered version information with source tracking.
SourceHint : Literal type
    Type hint for version source ("msi", "exe", or "string").
compare_any : function
    Compare two version strings, returning -1, 0, or 1.
is_newer_any : function
    Check if a remote version is newer than the current version.
version_key_any : function
    Generate a sortable key for any version string.

Version Comparison Strategies
------------------------------
The versioning system supports multiple comparison modes:

1. **Semantic Versioning (semver)**:
   - Parses X.Y.Z tuples with optional prerelease and build metadata
   - Handles prerelease tags: alpha, beta, rc, dev, etc.
   - Correctly orders: 1.0.0-alpha < 1.0.0-beta < 1.0.0-rc < 1.0.0

2. **Numeric (MSI/EXE)**:
   - Strict numeric-only parsing
   - MSI: 3-part versions (major.minor.patch)
   - EXE: 4-part versions (major.minor.patch.build)

3. **Lexicographic**:
   - Fallback string comparison for non-version-like strings
   - Useful for build IDs, timestamps, etc.

Examples
--------
Basic version comparison:

    >>> from notapkgtool.versioning import compare_any, is_newer_any
    >>> compare_any("1.2.0", "1.1.9")  # semver mode
    1
    >>> is_newer_any("1.2.0", "1.1.9")
    True

Prerelease handling:

    >>> compare_any("1.0.0-rc.1", "1.0.0-beta.5")
    1  # rc > beta
    >>> compare_any("1.0.0", "1.0.0-rc.1")
    1  # release > prerelease

MSI version extraction:

    >>> from notapkgtool.versioning.msi import version_from_msi_product_version
    >>> discovered = version_from_msi_product_version("installer.msi")
    >>> print(discovered.version)
    1.2.3

Notes
-----
- Version comparison is format-agnostic: no network or file I/O
- MSI extraction works cross-platform with appropriate backends
- Prerelease ordering follows common conventions but allows custom tags
"""

from .keys import (
    DiscoveredVersion,
    SourceHint,
    compare_any,
    is_newer_any,
    version_key_any,
)
