# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Core version comparison utilities for NAPT.

This module is format-agnostic: it does NOT download or read files.
It only parses and compares version strings consistently across sources
(MSI, EXE, generic strings).
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

# ----------------------------
# Shared DTO
# ----------------------------


@dataclass(frozen=True)
class DiscoveredVersion:
    """Container for a discovered version string.

    Attributes:
        version: Raw version string (e.g., "140.0.7339.128").
        source: Where it came from (e.g., "regex_in_url", "msi").

    """

    version: str
    source: str


@dataclass(frozen=True)
class VersionInfo:
    """Container for version information discovered without downloading.

    Used by version-first strategies (web_scrape, api_github, api_json)
    that can determine version and download URL without fetching the installer.

    Attributes:
        version: Raw version string (e.g., "140.0.7339.128").
        download_url: URL to download the installer.
        source: Strategy name for logging (e.g., "web_scrape", "api_github").

    """

    version: str
    download_url: str
    source: str


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
_UNKNOWN_PRE_RANK = 2.5  # unknown prerelease tags sort between beta and rc
_POST_TAGS = {"post", "p", "rev", "r", "hotfix", "hf"}

_NUM_SEP = re.compile(r"[._-]")


def _ints_from_text(text: str) -> tuple[int, ...]:
    """Parse numeric components only (for MSI/EXE).
    Raises ValueError if any non-numeric token is encountered to avoid
    silently mapping "1.2a" -> (1,2,0).
    """
    parts = [p for p in _NUM_SEP.split(text) if p]
    nums: list[int] = []
    for p in parts:
        if not p.isdigit():
            raise ValueError(f"non-numeric version component {p!r} in {text!r}")
        nums.append(int(p))
    return tuple(nums) if nums else (0,)


def _clip_for_source(nums: tuple[int, ...], source: SourceHint) -> tuple[int, ...]:
    """Trim version tuple by source semantics (MSI=3 parts, EXE=4 parts)."""
    if source == "msi":
        return nums[:3] or (0,)
    if source == "exe":
        return nums[:4] or (0,)
    return nums


def _pad_equal(
    a: tuple[int, ...], b: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Pad tuples with zeros so they align for element-wise comparison."""
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def _split_pre_tokens(pre: str) -> tuple[tuple[int, object], ...]:
    """Split prerelease suffix into tokens with numeric awareness.
    Example: "rc.10-x" -> [("rc"), 10, "x"] encoded as:
      (0, int) for numeric tokens (sort before text)
      (1, str) for text tokens (lowercased)
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
    """Detect a prerelease tag in the given suffix string.
    Returns (rank, tokens) or (None, ()) if not a prerelease.
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
    tokens = ((1, tag),) + tokens  # ensure "rc" < "rc.1" < "rc.2"
    return float(rank), tokens


def _find_post_segment(s: str) -> int:
    """Return a positive number if a post-release tag is found; else 0."""
    m = re.search(r"(?i)\b(post|p|rev|r|hotfix|hf)[._-]?(\d+)?\b", s)
    if not m:
        return 0
    return int(m.group(2)) if m.group(2) else 1


def _strip_build_meta(s: str) -> str:
    """Drop '+build' metadata (ignored in ordering)."""
    i = s.find("+")
    return s if i == -1 else s[:i]


def _leading_release_tuple(s: str) -> tuple[int, ...]:
    """Extract the leading numeric "release" tuple from a version-like string.

    Behavior:
    - Trim whitespace, lowercase, and drop a leading "v" (e.g., "v1.2.3" -> "1.2.3").
    - Split on [._-] and take numeric tokens until the first non-numeric.
      If a token starts with digits ("2rc1"), take the leading digits (2) and stop.
    - If no digits found at all, return (0,) as a sentinel meaning "not version-like".
    """
    s2 = s.lstrip().lower()
    if s2.startswith("v"):
        s2 = s2[1:]
    parts = _NUM_SEP.split(s2)

    nums: list[int] = []
    for p in parts:
        if not p:
            continue
        if p.isdigit():
            nums.append(int(p))
            continue
        m = re.match(r"(\d+)", p)
        if m:
            nums.append(int(m.group(1)))
        break
    return tuple(nums) if nums else (0,)


def _semver_like_key_robust(
    s: str,
) -> tuple[tuple[int, ...], float, tuple[tuple[int, object], ...], int]:
    """Build a semver-like key:
      (release_tuple, pre_rank_or_4.0, pre_tokens, post_num)

    Final releases use pre_rank=4.0 so they compare newer than any prerelease
    with the same core release tuple.
    """
    base = _strip_build_meta(s)
    release = _leading_release_tuple(base)

    # Only analyze suffix after the numeric core to avoid matching vendor names.
    suffix = base
    if release != (0,):
        core_re = r"^\s*v?" + r"\.".join(str(n) for n in release)
        m = re.match(core_re, base)
        if m:
            suffix = base[m.end() :]

    pre_rank, pre_tokens = _find_pre_segment(suffix)
    post_num = _find_post_segment(suffix)

    if pre_rank is None:
        return (release, 4.0, (), post_num)  # final release
    return (release, pre_rank, pre_tokens, post_num)


def version_key_any(s: str, *, source: SourceHint = "string") -> tuple:
    """Compute a comparable key for any version string.

    - MSI/EXE: purely numeric (truncated to 3/4 parts).
    - Generic string: semver-like robust key; if no numeric prefix,
        fallback to ("text", raw).
    """
    if source in ("msi", "exe"):
        nums = _clip_for_source(_ints_from_text(s), source)
        return ("num", nums)

    key = _semver_like_key_robust(s)
    release = key[0]
    if release != (0,):
        # IMPORTANT: We do NOT include the raw string as a tiebreaker.
        # This makes "v1.2.3" == "1.2.3" when the parsed keys are equal.
        return ("semverish", key)

    return ("text", s)


def compare_any(
    a: str,
    b: str,
    *,
    source: SourceHint = "string",
    verbose: bool = False,
) -> int:
    """Compare two versions with a source hint.
    Returns -1 if a < b, 0 if equal, 1 if a > b.
    """
    if source in ("msi", "exe"):
        try:
            aa = _clip_for_source(_ints_from_text(a), source)
            bb = _clip_for_source(_ints_from_text(b), source)
            aa, bb = _pad_equal(aa, bb)
            result = (aa > bb) - (aa < bb)
        except ValueError:
            # If vendor sneaks letters into numeric fields, fallback to generic parsing.
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
    """Decide if 'remote' should be considered newer than 'current'.
    Returns True iff remote > current under the given source semantics.
    """
    if current is None:
        if verbose:
            print(
                f"[is_newer_any] No current version. Treat {remote!r} "
                f"as newer (source={source})"
            )
        return True

    cmpv = compare_any(remote, current, source=source, verbose=verbose)
    if verbose:
        if cmpv > 0:
            print(
                f"[is_newer_any] Remote {remote!r} is newer than "
                f"current {current!r} (source={source})"
            )
        elif cmpv == 0:
            print(
                f"[is_newer_any] Remote {remote!r} is the same as "
                f"current {current!r} (source={source})"
            )
        else:
            print(
                f"[is_newer_any] Remote {remote!r} is older than "
                f"current {current!r} (source={source})"
            )
    return cmpv > 0
