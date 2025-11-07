"""
URL regex version extraction for NAPT.

This module extracts version information from URLs using regular expressions.
It's useful when vendors encode version numbers in their download URLs, allowing
version discovery without downloading the entire file first.

Use Cases
---------
- Vendors with version-encoded URLs (e.g., app-v1.2.3-installer.msi)
- APIs that return version-specific download links
- URLs with semantic version patterns in the path

Functions
---------
version_from_regex_in_url : function
    Extract version string from a URL using a regex pattern.

Pattern Syntax
--------------
Patterns support full Python regex syntax. Two extraction modes:

1. Named capture group (recommended):
   pattern = r"app-v(?P<version>[0-9.]+)-installer"
   Extracts only the 'version' group from the match.

2. Full match (fallback):
   pattern = r"[0-9]+\\.[0-9]+\\.[0-9]+"
   Uses the entire regex match as the version.

Examples
--------
Extract version from URL with named group:

    >>> from notapkgtool.versioning.url_regex import version_from_regex_in_url
    >>> url = "https://vendor.com/downloads/myapp-v1.2.3-setup.msi"
    >>> pattern = r"myapp-v(?P<version>[0-9.]+)-setup"
    >>> discovered = version_from_regex_in_url(url, pattern)
    >>> print(f"{discovered.version} from {discovered.source}")
    1.2.3 from regex_in_url

Extract version with full match:

    >>> url = "https://vendor.com/app/2024.10.28/installer.exe"
    >>> pattern = "[0-9]{4}\\\\.[0-9]{2}\\\\.[0-9]{2}"
    >>> discovered = version_from_regex_in_url(url, pattern)
    >>> discovered.version
    '2024.10.28'

Error handling:

    >>> try:
    ...     url = "https://vendor.com/app.msi"
    ...     pattern = r"v(?P<version>[0-9.]+)"
    ...     discovered = version_from_regex_in_url(url, pattern)
    ... except ValueError as e:
    ...     print(f"Pattern did not match: {e}")

Notes
-----
- This is pure string extraction; no network calls are made
- The extracted version is not validated for format
- Empty version strings will raise ValueError
- Regex compilation errors propagate as-is
"""

from __future__ import annotations

import re

from notapkgtool.versioning.keys import DiscoveredVersion


def version_from_regex_in_url(
    url: str, pattern: str, verbose: bool = False, debug: bool = False
) -> DiscoveredVersion:
    """
    Extract a version from a URL using a regular expression.

    The function searches for the pattern in the URL and extracts the version
    based on capture groups. If a named group (?P<version>) exists, that group
    is used; otherwise, the entire match is used.

    Parameters
    ----------
    url : str
        The URL to extract the version from. Can be a full URL or just a path.
    pattern : str
        Regular expression pattern to match. Use (?P<version>...) for a named
        capture group to extract only the version portion.
    verbose : bool, optional
        If True, print verbose logging messages. Default is False.
    debug : bool, optional
        If True, print debug logging messages. Default is False.

    Returns
    -------
    DiscoveredVersion
        Container with the extracted version string and source='regex_in_url'.

    Raises
    ------
    ValueError
        If the pattern does not match the URL, or if the extracted version
        is empty.
    re.error
        If the regex pattern is invalid (propagates from re.search).

    Examples
    --------
    Extract with named capture group:

        >>> url = "https://vendor.com/app-v2.1.0-installer.msi"
        >>> pattern = r"app-v(?P<version>[0-9.]+)-installer"
        >>> discovered = version_from_regex_in_url(url, pattern)
        >>> discovered.version
        '2.1.0'

    Extract with full match:

        >>> url = "https://vendor.com/downloads/1.2.3/setup.exe"
        >>> pattern = r"[0-9]+\\.[0-9]+\\.[0-9]+"
        >>> discovered = version_from_regex_in_url(url, pattern)
        >>> discovered.version
        '1.2.3'
    """
    from notapkgtool.cli import print_debug, print_verbose

    print_verbose("VERSION", "Strategy: regex_in_url")
    print_verbose("VERSION", f"Pattern: {pattern}")
    print_debug("VERSION", f"URL: {url}")

    try:
        m = re.search(pattern, url)
    except re.error as err:
        raise ValueError(f"Invalid regex pattern: {pattern!r}") from err

    if not m:
        raise ValueError(
            f"Pattern did not match URL. Pattern: {pattern!r}, URL: {url!r}"
        )

    # Use named group 'version' if present, otherwise use full match
    ver = m.group("version") if "version" in (m.groupdict() or {}) else m.group(0)

    if not ver:
        raise ValueError(
            f"Extracted version is empty. Pattern: {pattern!r}, URL: {url!r}"
        )

    print_verbose("VERSION", f"Success! Extracted: {ver} (via regex)")
    print_debug("VERSION", f"Match details: {m.groups()}")

    return DiscoveredVersion(version=ver, source="regex_in_url")
