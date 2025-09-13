"""
Version checking processor for NAPT.

Responsibilities:
- Compare current vs. remote version.
- Support semver and lexicographic comparators.
- Provide helpers for extracting versions from URLs or files.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

Comparator = Literal["semver", "lexicographic"]

# Regex for strict semver parsing
SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<meta>[0-9A-Za-z.-]+))?$"
)


def _semver_key(v: str):
    """
    Parse a semver string into a tuple for comparison.
    Falls back to lexicographic if not valid semver.
    """
    m = SEMVER_RE.match(v)
    if not m:
        return (v,)  # fallback
    return (
        int(m.group("major")),
        int(m.group("minor")),
        int(m.group("patch")),
        m.group("prerelease") or "",
    )


def is_newer(
    remote: str, current: str | None, comparator: Comparator = "semver"
) -> bool:
    """
    Determine if remote version is newer than current.

    :param remote: Remote/discovered version string.
    :param current: Currently deployed version string (or None).
    :param comparator: "semver" or "lexicographic".
    :return: True if remote is newer.
    """
    if not current:
        return True
    if comparator == "semver":
        return _semver_key(remote) > _semver_key(current)
    return remote > current


@dataclass
class DiscoveredVersion:
    """
    Represents a discovered version value and its source.
    """

    version: str
    source: str  # e.g. "regex_in_url", "msi_product_version_from_file"


def version_from_regex_in_url(url: str, pattern: str) -> DiscoveredVersion:
    """
    Extract a version string from a URL using regex.

    :param url: Full URL string.
    :param pattern: Regex pattern with optional (?P<version>) group.
    :return: DiscoveredVersion
    """
    m = re.search(pattern, url)
    if not m:
        raise ValueError(f"could not extract version from url with pattern: {pattern}")
    ver = m.group("version") if "version" in m.groupdict() else m.group(0)
    return DiscoveredVersion(version=ver, source="regex_in_url")


def version_from_msi_product_version(file_path: str) -> DiscoveredVersion:
    """
    Placeholder: Extract ProductVersion from an MSI file.

    On Windows: can use 'msilib' or 'msiinfo' from msitools.
    For now: raises NotImplementedError.
    """
    raise NotImplementedError("msi version extraction to be implemented")
