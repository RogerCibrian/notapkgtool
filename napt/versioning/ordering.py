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

"""Version ordering as managed devices see it.

Whether a release installs over another is decided on the device by
``Compare-VersionString`` in ``napt/build/templates/_shared_functions.ps1``,
which the detection and requirements scripts call. This module mirrors
that function, so that when NAPT calls a release a downgrade it means the
same thing the device will: devices on the other version will not take it.

The mirror is deliberately no smarter than the original. Each ``.`` or
``-`` separated segment contributes its leading digits, a segment without
leading digits counts as 0, and missing trailing segments count as 0. A
``v`` prefix or a prerelease tag is therefore not understood on either
side. ``tests/test_version_ordering.py`` runs one table of cases through
both implementations to keep them in step.
"""

from __future__ import annotations

import re

_SEGMENT_SEPARATORS = re.compile(r"[.\-]")
_LEADING_DIGITS = re.compile(r"\d+")


def version_parts(version: str) -> list[int]:
    """Parses a version string into the numbers a device compares.

    Args:
        version: Version string, for example ``"140.0.7339.128"``.

    Returns:
        One integer per segment: its leading digits, or 0 when it has none.

    """
    parts: list[int] = []
    for segment in _SEGMENT_SEPARATORS.split(version):
        match = _LEADING_DIGITS.match(segment)
        parts.append(int(match.group()) if match else 0)
    return parts


def compare_versions(left: str, right: str) -> int:
    """Compares two version strings the way a managed device does.

    Args:
        left: First version string.
        right: Second version string.

    Returns:
        -1 when ``left`` is lower, 0 when they are equal, and 1 when
            ``left`` is higher.

    """
    left_parts = version_parts(left)
    right_parts = version_parts(right)
    length = max(len(left_parts), len(right_parts))
    left_parts += [0] * (length - len(left_parts))
    right_parts += [0] * (length - len(right_parts))
    return (left_parts > right_parts) - (left_parts < right_parts)


def is_downgrade(candidate: str, current: str | None) -> bool:
    """Reports whether a release is lower than the one it would replace.

    Args:
        candidate: Version of the release being considered.
        current: Version it would replace, or None when there is none.

    Returns:
        True when devices on ``current`` would not take ``candidate``.

    """
    return current is not None and compare_versions(candidate, current) < 0
