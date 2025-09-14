"""
Version checking and discovery helpers for NAPT.

Responsibilities
- Compare versions using either semantic versioning ("semver") or lexicographic ordering.
- Extract versions from URLs with regex.
- Extract MSI ProductVersion from .msi files (Windows-friendly; graceful fallback elsewhere).

Highlights
- SemVer comparator treats final releases as newer than prereleases (e.g., 1.2.0 > 1.2.0-rc.1).
- Fallback behavior keeps tuple types comparable even when a string is not valid semver.
- Docstrings and clear error messages for fast debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Literal

Comparator = Literal["semver", "lexicographic"]

# Strict SemVer pattern (build metadata is parsed but ignored in ordering).
SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<meta>[0-9A-Za-z.-]+))?$"
)


def _semver_key(v: str) -> tuple:
    """
    Turn a semver-like string into a consistent, comparable tuple.

    Ordering rules
    - Compare major, minor, patch numerically.
    - Final releases rank *after* prereleases with the same core version (i.e., are "greater").
    - Prerelease text ties break among prereleases (lexicographic as a pragmatic simplification).
    - Build metadata (+foo) does not affect ordering.

    Fallback
    - If not valid semver, return a tuple that stays comparable: (-1, -1, -1, -1, v)
      so that all non-semver values group consistently and compare lexicographically by the original string.
    """
    m = SEMVER_RE.match(v)
    if not m:
        return (-1, -1, -1, -1, v)  # keep type-stable tuple comparisons

    major = int(m.group("major"))
    minor = int(m.group("minor"))
    patch = int(m.group("patch"))
    prerelease = m.group("prerelease")

    # release_flag: 1 for final release (newer), 0 for prerelease (older)
    release_flag = 1 if prerelease is None else 0
    prerelease_str = prerelease or ""

    # comparable key: major, minor, patch, final-vs-pre, prerelease string
    return (major, minor, patch, release_flag, prerelease_str)


def is_newer(
    remote: str, current: str | None, comparator: Comparator = "semver"
) -> bool:
    """
    Decide if 'remote' should be considered newer than 'current'.

    - comparator="semver" uses the _semver_key ordering above.
    - comparator="lexicographic" falls back to simple string comparison.

    None behavior:
    - If current is None (no installed/known version), treat remote as newer.
    """
    if current is None:
        return True
    if comparator == "semver":
        return _semver_key(remote) > _semver_key(current)
    return remote > current


@dataclass(frozen=True)
class DiscoveredVersion:
    """
    Structured return for version discovery routines.

    Attributes
    - version: Discovered version string.
    - source: Where it came from (e.g., "regex_in_url", "msi_product_version_from_file").
    """

    version: str
    source: str


def version_from_regex_in_url(url: str, pattern: str) -> DiscoveredVersion:
    """
    Extract a version from a URL using a regex.

    'pattern' may include a named group (?P<version>) to capture the exact substring.
    If no group is provided, the entire match is used.

    Raises
    - ValueError if the pattern does not match the URL.

    Example
    - url='https://example.com/app-24.08-x64.exe', pattern=r'app-(?P<version>\d+\.\d+)-x64\.exe'
    """
    m = re.search(pattern, url)
    if not m:
        raise ValueError(
            f"could not extract version from url with pattern: {pattern}; url={url}"
        )
    ver = m.group("version") if "version" in m.groupdict() else m.group(0)
    return DiscoveredVersion(version=ver, source="regex_in_url")


def version_from_msi_product_version(file_path: str | Path) -> DiscoveredVersion:
    """
    Extract ProductVersion from an MSI file.

    Approaches
    1) Windows stdlib (_msi) when available (most reliable on Windows).
    2) 'msiinfo' (from msitools) if present in PATH (cross-platform option via subprocess).
    3) If neither is available, raises NotImplementedError with guidance.

    Returns
    - DiscoveredVersion(version=<ProductVersion>, source="msi_product_version_from_file")

    Raises
    - FileNotFoundError: if file does not exist.
    - RuntimeError: if parsing fails.
    - NotImplementedError: if no parsing backend is available on this host.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"MSI not found: {p}")

    # 1) Native Windows path using _msi (only available on Windows CPython)
    if sys.platform.startswith("win"):
        try:
            # _msi is a CPython Windows extension. Import lazily to avoid ImportError on non-Windows.
            import _msi  # type: ignore

            # OpenDatabase path, mode=0 for read-only
            db = _msi.OpenDatabase(str(p), 0)
            view = db.OpenView(
                "SELECT `Value` FROM `Property` WHERE `Property`='ProductVersion'"
            )
            view.Execute(None)
            rec = view.Fetch()
            if rec is None:
                raise RuntimeError("ProductVersion not found in MSI Property table.")
            version = rec.GetString(1)
            if version is None:
                raise RuntimeError("Empty ProductVersion in MSI Property table.")
            view.Close()
            db.Close()
            return DiscoveredVersion(
                version=version, source="msi_product_version_from_file"
            )
        except Exception as err:
            raise RuntimeError(
                f"failed to read MSI ProductVersion via _msi: {err}"
            ) from err

    # 2) Cross-platform fallback using msitools' 'msiinfo' if available
    msiinfo = shutil.which("msiinfo")
    if msiinfo:
        try:
            # 'msiinfo export <msi> Property -' prints the Property table to stdout (tab-separated).
            # We then parse the line for 'ProductVersion'.
            result = subprocess.run(
                [msiinfo, "export", str(p), "Property", "-"],
                check=True,
                capture_output=True,
                text=True,
            )
            version: str | None = None
            for line in result.stdout.splitlines():
                # Expect lines like: "Property\tValue"
                parts = line.strip().split("\t", 1)
                if len(parts) == 2 and parts[0] == "ProductVersion":
                    version = parts[1]
                    break
            if not version:
                raise RuntimeError("ProductVersion not found in MSI Property output.")
            return DiscoveredVersion(
                version=version, source="msi_product_version_from_file"
            )
        except subprocess.CalledProcessError as err:
            raise RuntimeError(f"msiinfo failed: {err}") from err

    # 3) No backend available
    raise NotImplementedError(
        "MSI version extraction is not available on this host. "
        "On Windows, CPython provides '_msi'. Elsewhere, install 'msitools' to get 'msiinfo'."
    )
