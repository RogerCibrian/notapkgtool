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
It only parses and compares version strings consistently across sources.
"""

from __future__ import annotations

import re

# Known prerelease tag ordering (lower = older)
_PRERELEASE_TAG_RANK: dict[str, float] = {
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
_UNKNOWN_PRERELEASE_RANK = 2.5  # unknown prerelease tags sort between beta and rc
_POST_RELEASE_TAGS = {"post", "p", "rev", "r", "hotfix", "hf"}

_VERSION_SEPARATOR = re.compile(r"[._-]")


def _split_pre_tokens(prerelease_suffix: str) -> tuple[tuple[int, object], ...]:
    """Splits prerelease suffix into comparable tokens with numeric awareness.

    Each token is a (kind, value) pair where kind 0 (numeric) sorts before
    kind 1 (text). For example, "rc.10-x" becomes ((1, "rc"), (0, 10), (1, "x")).
    """
    tokens = re.split(r"[.\-]", prerelease_suffix)
    result: list[tuple[int, object]] = []
    for token in tokens:
        if not token:
            continue
        if token.isdigit():
            result.append((0, int(token)))
        else:
            result.append((1, token.lower()))
    return tuple(result)


def _find_pre_segment(
    suffix: str,
) -> tuple[float | None, tuple[tuple[int, object], ...]]:
    """Detects a prerelease tag in the given suffix string.

    Returns:
        A tuple (prerelease_rank, prerelease_tokens). Returns (None, ()) when
            no prerelease tag is found or the tag matches a post-release marker.

    """
    match = re.search(r"(?i)\b([A-Za-z]+)[._-]?([0-9A-Za-z.\-]*)", suffix)
    if not match:
        return None, ()
    tag = match.group(1).lower()
    tag_suffix = match.group(2) or ""
    if tag in _POST_RELEASE_TAGS:
        return None, ()
    prerelease_rank = _PRERELEASE_TAG_RANK.get(tag, _UNKNOWN_PRERELEASE_RANK)
    prerelease_tokens = _split_pre_tokens(tag_suffix) if tag_suffix else ()
    prerelease_tokens = ((1, tag),) + prerelease_tokens  # ensure "rc" < "rc.1" < "rc.2"
    return float(prerelease_rank), prerelease_tokens


def _find_post_segment(suffix: str) -> int:
    """Returns a positive number if a post-release tag is found; else 0."""
    match = re.search(r"(?i)\b(post|p|rev|r|hotfix|hf)[._-]?(\d+)?\b", suffix)
    if not match:
        return 0
    return int(match.group(2)) if match.group(2) else 1


def _strip_build_meta(version: str) -> str:
    """Drops '+build' metadata (ignored in ordering)."""
    plus_index = version.find("+")
    return version if plus_index == -1 else version[:plus_index]


def _leading_release_tuple(version: str) -> tuple[int, ...]:
    """Extracts the leading numeric "release" tuple from a version-like string.

    Behavior:
        - Trims whitespace, lowercases, and drops a leading "v"
            (e.g., "v1.2.3" -> "1.2.3").
        - Splits on [._-] and takes numeric tokens until the first non-numeric.
            If a token starts with digits ("2rc1"), takes the leading digits (2)
            and stops.
        - Returns (0,) as a sentinel when no digits are found at all,
            meaning "not version-like".

    """
    normalized = version.lstrip().lower()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    parts = _VERSION_SEPARATOR.split(normalized)

    components: list[int] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            components.append(int(part))
            continue
        match = re.match(r"(\d+)", part)
        if match:
            components.append(int(match.group(1)))
        break
    return tuple(components) if components else (0,)


def _semver_like_key_robust(
    version: str,
) -> tuple[tuple[int, ...], float, tuple[tuple[int, object], ...], int]:
    """Builds a semver-like sort key for a version string.

    Returns a tuple of (release_tuple, prerelease_rank, prerelease_tokens,
    post_release_number). Final releases use prerelease_rank=4.0 so they
    sort newer than any prerelease with the same core release tuple.
    """
    stripped = _strip_build_meta(version)
    release = _leading_release_tuple(stripped)

    # Only analyze suffix after the numeric core to avoid matching vendor names.
    suffix = stripped
    if release != (0,):
        release_pattern = r"^\s*v?" + r"\.".join(str(n) for n in release)
        match = re.match(release_pattern, stripped)
        if match:
            suffix = stripped[match.end() :]

    prerelease_rank, prerelease_tokens = _find_pre_segment(suffix)
    post_release_number = _find_post_segment(suffix)

    if prerelease_rank is None:
        return (release, 4.0, (), post_release_number)  # final release
    return (release, prerelease_rank, prerelease_tokens, post_release_number)


def version_key(version: str) -> tuple:
    """Computes a sortable comparison key for a version string.

    Uses semver-like parsing with prerelease ordering; falls back to
    lexicographic comparison when no numeric prefix is found.

    Args:
        version: Version string to convert.

    Returns:
        An opaque tuple suitable for use as a sort key.

    Note:
        Equal parsed keys (e.g., "v1.2.3" and "1.2.3") produce the same
        tuple, so the raw string is not included as a tiebreaker.

    """
    key = _semver_like_key_robust(version)
    release = key[0]
    if release != (0,):
        return ("semverish", key)

    return ("text", version)


def compare(
    version_a: str,
    version_b: str,
) -> int:
    """Compares two version strings and returns their ordering.

    Args:
        version_a: First version string.
        version_b: Second version string.

    Returns:
        -1 if version_a is older than version_b, 0 if equal, 1 if newer.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    left_key = version_key(version_a)
    right_key = version_key(version_b)
    result = (left_key > right_key) - (left_key < right_key)

    if result < 0:
        logger.verbose("VERSION", f"{version_a!r} is older than {version_b!r}")
    elif result > 0:
        logger.verbose("VERSION", f"{version_a!r} is newer than {version_b!r}")
    else:
        logger.verbose("VERSION", f"{version_a!r} is the same as {version_b!r}")
    return result


def is_newer(
    remote: str,
    current: str | None,
) -> bool:
    """Determines whether a remote version is newer than the current version.

    Args:
        remote: Version string to check (e.g., from the download source).
        current: Currently cached version string, or None if not yet downloaded.

    Returns:
        True if remote is newer than current. Always True when current is None.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()

    if current is None:
        logger.verbose(
            "VERSION",
            f"No current version. Treat {remote!r} as newer",
        )
        return True

    # compare() already logs the comparison result
    return compare(remote, current) > 0
