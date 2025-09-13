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

# Strict SemVer: build metadata is parsed but ignored for ordering.
SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<meta>[0-9A-Za-z.-]+))?$"
)


def _semver_key(v: str) -> tuple:
    """
    Turn a semver-ish string into a key that sorts correctly:
    - Releases sort AFTER prereleases (i.e., greater).
    - Build metadata (+foo) is ignored for precedence.
    - If not valid semver, fall back to a tuple that preserves original string ordering.
    """
    m = SEMVER_RE.match(v)
    if not m:
        # Fallback: single-element tuple keeps lexicographic behavior when needed.
        return (v,)

    major = int(m.group("major"))
    minor = int(m.group("minor"))
    patch = int(m.group("patch"))
    prerelease = m.group("prerelease")

    # prerelease_flag: 0 = prerelease, 1 = final release (so finals sort higher)
    release_flag = 1 if prerelease is None else 0
    prerelease_str = prerelease or ""

    # Key ordering:
    #   major, minor, patch, release_flag (final > prerelease), prerelease string
    return (major, minor, patch, release_flag, prerelease_str)


def is_newer(
    remote: str, current: str | None, comparator: Comparator = "semver"
) -> bool:
    if current is None:
        return True
    if comparator == "semver":
        return _semver_key(remote) > _semver_key(current)
    return remote > current


@dataclass
class DiscoveredVersion:
    version: str
    source: str  # e.g., "regex_in_url", "msi_product_version_from_file"


def version_from_regex_in_url(url: str, pattern: str) -> DiscoveredVersion:
    m = re.search(pattern, url)
    if not m:
        raise ValueError(f"could not extract version from url with pattern: {pattern}")
    ver = m.group("version") if "version" in m.groupdict() else m.group(0)
    return DiscoveredVersion(version=ver, source="regex_in_url")


def version_from_msi_product_version(file_path: str) -> DiscoveredVersion:
    raise NotImplementedError("msi version extraction to be implemented")
