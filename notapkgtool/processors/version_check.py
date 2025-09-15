"""
Version checking and discovery helpers for NAPT.

This module provides:
- Routines to extract version strings (from URLs, MSI files).
- A robust comparator that handles versions from different sources (MSI, EXE, generic strings).
- Optional print-based logging to explain comparisons (controlled by verbose flags).

Why this exists:
Vendors use inconsistent version formats. Some follow SemVer, others use MSI 3-part
product versions, others use 4-part EXE file versions, and some append prerelease/post tags.
This code attempts to compare all of them in a consistent and predictable way.

Comparison policy:
- MSI: only the first 3 numeric parts matter (Windows Installer ignores the 4th).
- EXE: up to 4 numeric parts matter (Windows file-version convention).
- Generic strings:
    * Numeric-aware prerelease handling (rc.10 > rc.2).
    * Final releases are newer than prereleases with the same core.
    * Known prerelease tags ordered: dev < alpha/a/pre/preview/ea < beta/b < rc < final.
    * Unknown prerelease tags sort between beta and rc.
    * Post-release tags (post, p, rev, r, hotfix, hf) sort newer than the same base.
    * +build metadata is ignored for ordering.

Intended usage:
Use `is_newer_any(remote, current, source="msi|exe|string", verbose=False)` to check if an update is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Literal

# ----------------------------
# Discovery structures/helpers
# ----------------------------


@dataclass(frozen=True)
class DiscoveredVersion:
    """
    Container for a discovered version string.

    Attributes
    ----------
    version : str
        The raw version string discovered (e.g. "140.0.7339.128").
    source : str
        Where the version came from (e.g. "regex_in_url", "msi_product_version_from_file").
    """

    version: str
    source: str


def version_from_regex_in_url(url: str, pattern: str) -> DiscoveredVersion:
    """
    Extract a version from a URL using a regex.

    Parameters
    ----------
    url : str
        The URL to search.
    pattern : str
        A regex pattern. May include a named group (?P<version>) to capture the substring.

    Returns
    -------
    DiscoveredVersion
        With the version string and source marker.

    Raises
    ------
    ValueError
        If the regex does not match the URL.

    Example
    -------
    url='https://example.com/app-24.08-x64.exe'
    pattern=r'app-(?P<version>\\d+\\.\\d+)-x64\\.exe'
    -> version='24.08'
    """
    m = re.search(pattern, url)
    if not m:
        raise ValueError(
            f"could not extract version from url with pattern: {pattern}; url={url}"
        )
    ver = m.group("version") if "version" in (m.groupdict() or {}) else m.group(0)
    return DiscoveredVersion(version=ver, source="regex_in_url")


def version_from_msi_product_version(file_path: str | Path) -> DiscoveredVersion:
    """
    Extract ProductVersion from an MSI file.

    Notes:
    - On Windows, uses the built-in `_msi` extension.
    - On other platforms, uses `msiinfo` from `msitools` if available.
      (Command: `msiinfo export <msi> Property` -> stdout.)
    - Otherwise raises NotImplementedError.

    Windows Installer rules:
    - ProductVersion is at most three numbers (Major.Minor.Build).
    - A fourth number may exist but Windows ignores it for upgrade logic.

    Raises
    ------
    FileNotFoundError: if the file does not exist.
    RuntimeError: if parsing fails.
    NotImplementedError: if no parsing backend is available on this host.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"MSI not found: {p}")

    # 1) Native Windows path using _msi (only on Windows CPython).
    if sys.platform.startswith("win"):
        try:
            import _msi  # type: ignore

            db = _msi.OpenDatabase(str(p), 0)  # 0: read-only
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

    # 2) Cross-platform fallback using msitools' `msiinfo`, which prints to stdout.
    msiinfo = shutil.which("msiinfo")
    if msiinfo:
        try:
            # msiinfo export <package> <table> -> stdout (tab-separated)
            # We parse the Property table and pull 'ProductVersion'.
            result = subprocess.run(
                [msiinfo, "export", str(p), "Property"],
                check=True,
                capture_output=True,
                text=True,
            )
            version: str | None = None
            for line in result.stdout.splitlines():
                parts = line.strip().split("\t", 1)  # "Property<TAB>Value"
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
        "On Windows, CPython provides '_msi'. Elsewhere, install 'msitools'."
    )


# ----------------------------
# Comparison core (robust)
# ----------------------------

SourceHint = Literal["msi", "exe", "string"]

# Known prerelease tag ordering (lower = older)
_PRE_TAG_RANK: dict[str, float] = {
    "dev": 0,
    "d": 0,
    "alpha": 1,
    "a": 1,
    "pre": 1,
    "preview": 1,
    "ea": 1,
    "beta": 2,
    "b": 2,
    "rc": 3,
}
_UNKNOWN_PRE_RANK = 2.5  # Unknown prerelease tags land between beta and rc

# Post-release tags that indicate "newer than the same base"
_POST_TAGS = {"post", "p", "rev", "r", "hotfix", "hf"}

# Regex used for splitting into tokens
_NUM_SEP = re.compile(r"[._-]")


def _ints_from_text(text: str) -> tuple[int, ...]:
    """
    Split on separators and parse ints for MSI/EXE sources.

    Important:
    - We enforce numeric-only components; if a non-digit token appears,
      raise ValueError to avoid silently mapping '1.2a' to (1,2,0).
    """
    parts = [p for p in _NUM_SEP.split(text) if p != ""]
    nums: list[int] = []
    for p in parts:
        if not p.isdigit():
            raise ValueError(f"non-numeric version component {p!r} in {text!r}")
        nums.append(int(p))
    return tuple(nums) if nums else (0,)


def _clip_for_source(nums: tuple[int, ...], source: SourceHint) -> tuple[int, ...]:
    """Trim version tuple according to source rules."""
    if source == "msi":
        return nums[:3] or (0,)
    if source == "exe":
        return nums[:4] or (0,)
    return nums


def _pad_equal(
    a: tuple[int, ...], b: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Pad tuples with zeros so they can be compared element-wise."""
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def _split_pre_tokens(pre: str) -> tuple[tuple[int, object], ...]:
    """
    Split prerelease text into tokens with numeric awareness.

    rc.10-x -> [('rc'), 10, 'x'] encoded as tuples:
    - (0, int) for numeric tokens (sort before text)
    - (1, str) for text tokens (case-insensitive)
    """
    tokens = re.split(r"[.\-]", pre)
    out: list[tuple[int, object]] = []
    for t in tokens:
        if not t:
            continue
        if t.isdigit():
            out.append((0, int(t)))
        else:
            out.append((1, t.lower()))
    return tuple(out)


def _find_pre_segment(s: str) -> tuple[float | None, tuple[tuple[int, object], ...]]:
    """
    Detect a prerelease tag in the suffix of a version string.

    Returns (rank, tokens) if found, else (None, ()).
    Unknown tags get _UNKNOWN_PRE_RANK.
    """
    m = re.search(r"(?i)\b([A-Za-z]+)[._-]?([0-9A-Za-z.\-]*)", s)
    if not m:
        return None, ()
    tag = m.group(1).lower()
    rest = m.group(2) or ""
    if tag in _POST_TAGS:
        return None, ()
    rank = _PRE_TAG_RANK.get(tag, _UNKNOWN_PRE_RANK)
    tokens = _split_pre_tokens(rest) if rest else ()
    tokens = ((1, tag),) + tokens  # include the tag so rc < rc.1 < rc.2
    return float(rank), tokens


def _find_post_segment(s: str) -> int:
    """Detect a post-release tag (returns number if present, else 0)."""
    m = re.search(r"(?i)\b(post|p|rev|r|hotfix|hf)[._-]?(\d+)?\b", s)
    if not m:
        return 0
    return int(m.group(2)) if m.group(2) else 1


def _strip_build_meta(s: str) -> str:
    """Remove build metadata after '+' (ignored for ordering)."""
    i = s.find("+")
    return s if i == -1 else s[:i]


def _leading_release_tuple(s: str) -> tuple[int, ...]:
    """
    Extract the leading numeric "release tuple" from a version string.

    Purpose
    -------
    Many version strings start with a numeric core (e.g., "1.2.3", "2024.09-beta").
    This function pulls that numeric prefix out so we can sort versions
    by their numbers first, then worry about prerelease or postrelease tags.

    Behavior
    --------
    - Strips whitespace and lowercases the input.
    - Drops a leading "v" (common in tags like "v1.2.3").
    - Splits the string on common separators (., _, -).
    - Reads consecutive numeric components at the start and converts them to ints.
    - Stops parsing when it hits a non-numeric token.
      * Exception: if a token starts with digits followed by letters
        (like "2rc1"), it extracts the digits ("2") and then stops.
    - If no digits are found at all, returns (0,) as a sentinel.

    Examples
    --------
    "v1.2.3"        -> (1, 2, 3)
    "1.2rc1"        -> (1, 2)   # stops when hitting "rc1"
    "build-2024-09" -> (2024, 9)
    "alpha"         -> (0,)     # no leading numbers
    """
    # Normalize: strip whitespace and lowercase for consistency
    s2 = s.lstrip().lower()

    # Drop a leading "v" (common in tags like v1.2.3)
    if s2.startswith("v"):
        s2 = s2[1:]

    # Split the string into tokens on ., _, or -
    parts = _NUM_SEP.split(s2)

    nums: list[int] = []
    for p in parts:
        if not p:
            # Skip empty segments (e.g., double dots)
            continue
        if p.isdigit():
            # Entire token is numeric -> take it
            nums.append(int(p))
            continue
        # Token has some digits at the start, e.g. "123rc1"
        m = re.match(r"(\d+)", p)
        if m:
            nums.append(int(m.group(1)))
        # Stop parsing at the first non-pure-numeric token
        break

    # Return collected numbers as a tuple,
    # or (0,) if nothing numeric was found
    return tuple(nums) if nums else (0,)


def _semver_like_key_robust(
    s: str,
) -> tuple[tuple[int, ...], float, tuple[tuple[int, object], ...], int]:
    """
    Build a semver-like key:
    (release_tuple, pre_rank_or_4, pre_tokens, post_num)

    - release_tuple: core numeric version
    - pre_rank: dev < alpha < beta < rc < final
    - pre_tokens: numeric-aware breakdown of the prerelease tag
    - post_num: positive if post-release tag found
    """
    base = _strip_build_meta(s)
    release = _leading_release_tuple(base)

    # Only analyze suffix after the extracted numeric core to avoid matching vendor names.
    suffix = base
    if release != (0,):
        core_re = r"^\s*v?" + r"\.".join(str(n) for n in release)
        m = re.match(core_re, base)
        if m:
            suffix = base[m.end() :]

    pre_rank, pre_tokens = _find_pre_segment(suffix)
    post_num = _find_post_segment(suffix)

    if pre_rank is None:
        return (release, 4.0, (), post_num)  # 4.0 => final release
    return (release, pre_rank, pre_tokens, post_num)


def version_key_any(s: str, *, source: SourceHint = "string") -> tuple:
    """Return a sort key for a version string according to its source type."""
    if source in ("msi", "exe"):
        nums = _clip_for_source(_ints_from_text(s), source)
        return ("num", nums)

    key = _semver_like_key_robust(s)
    release = key[0]
    if release != (0,):
        return ("semverish", key)
    return ("text", s)


def compare_any(
    a: str,
    b: str,
    *,
    source: SourceHint = "string",
    verbose: bool = False,
) -> int:
    """
    Compare two versions with a source hint.
    Returns -1 if a < b, 0 if equal, 1 if a > b.
    When verbose, prints a message describing the relationship.
    """
    if source in ("msi", "exe"):
        try:
            aa = _clip_for_source(_ints_from_text(a), source)
            bb = _clip_for_source(_ints_from_text(b), source)
            aa, bb = _pad_equal(aa, bb)
            result = (aa > bb) - (aa < bb)
        except ValueError:
            # Fallback to generic string logic if vendor sneaks text into a numeric field.
            ka = version_key_any(a, source="string")
            kb = version_key_any(b, source="string")
            result = (ka > kb) - (ka < kb)
    else:
        ka = version_key_any(a, source="string")
        kb = version_key_any(b, source="string")
        result = (ka > kb) - (ka < kb)

    if verbose:
        if result < 0:
            print(f"[compare_any] {a!r} is older than {b!r} (source={source})")
        elif result > 0:
            print(f"[compare_any] {a!r} is newer than {b!r} (source={source})")
        else:
            print(f"[compare_any] {a!r} is the same as {b!r} (source={source})")
    return result


def is_newer_any(
    remote: str,
    current: str | None,
    *,
    source: SourceHint = "string",
    verbose: bool = False,
) -> bool:
    """
    Decide if 'remote' should be considered newer than 'current'.

    Returns True if remote is newer.
    When verbose, prints a message about the decision.
    """
    if current is None:
        if verbose:
            print(
                f"[is_newer_any] No current version. Treating {remote!r} as newer (source={source})"
            )
        return True

    cmpv = compare_any(remote, current, source=source, verbose=verbose)
    if verbose:
        if cmpv > 0:
            print(
                f"[is_newer_any] Remote {remote!r} is newer than current {current!r} (source={source})"
            )
        elif cmpv == 0:
            print(
                f"[is_newer_any] Remote {remote!r} is the same as current {current!r} (source={source})"
            )
        else:
            print(
                f"[is_newer_any] Remote {remote!r} is older than current {current!r} (source={source})"
            )
    return cmpv > 0


# ----------------------------
# Quick self-test / examples
# ----------------------------

if __name__ == "__main__":
    # MSI: only 3 parts matter
    compare_any("140.0.7339.128", "140.0.7339.1", source="msi", verbose=True)  # same
    compare_any("140.0.7340.0", "140.0.7339.999", source="msi", verbose=True)  # newer

    # EXE: up to 4 parts
    compare_any(
        "10.0.19041.3720", "10.0.19041.3448", source="exe", verbose=True
    )  # newer

    # Prerelease numeric ordering
    compare_any("1.2.0-rc.1", "1.2.0-rc.2", verbose=True)  # older
    compare_any("1.2.0-rc.10", "1.2.0-rc.2", verbose=True)  # newer
    compare_any("1.2.0-beta.11", "1.2.0-rc.1", verbose=True)  # older
    compare_any("1.2.0", "1.2.0-rc.7", verbose=True)  # newer (final > pre)

    # Unknown prerelease tag policy
    compare_any("1.2.0-zzz.1", "1.2.0-rc.1", verbose=True)  # older than rc
    compare_any("1.2.0-zzz.2", "1.2.0-beta.11", verbose=True)  # newer than beta

    # Post releases are newer than base
    compare_any("1.2.0", "1.2.0-post1", verbose=True)  # older
    compare_any("1.2.0-hotfix-2", "1.2.0", verbose=True)  # newer

    # Loose vendor forms
    compare_any("v1.2.3", "1.2.3", verbose=True)  # same
    compare_any("1.2rc1", "1.2", verbose=True)  # older

    # is_newer_any demos
    is_newer_any("1.2.0-rc.2", "1.2.0-rc.1", source="string", verbose=True)
    is_newer_any("140.0.7339.128", "140.0.7339.1", source="msi", verbose=True)
