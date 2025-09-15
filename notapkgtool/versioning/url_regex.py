"""
Discovery helper: extract a version from a URL using a regex.
Keeps concerns separate from comparison and from MSI/EXE parsing.
"""

from __future__ import annotations

import re

from notapkgtool.versioning.keys import DiscoveredVersion


def version_from_regex_in_url(url: str, pattern: str) -> DiscoveredVersion:
    """
    Extract a version from a URL using a regex.

    If the regex includes a named group (?P<version>), that group is used;
    otherwise, the whole match is returned.

    Raises ValueError if the pattern does not match.
    """
    m = re.search(pattern, url)
    if not m:
        raise ValueError(
            f"could not extract version from url with pattern: {pattern}; url={url}"
        )
    ver = m.group("version") if "version" in (m.groupdict() or {}) else m.group(0)
    return DiscoveredVersion(version=ver, source="regex_in_url")
