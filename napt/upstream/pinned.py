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

"""What the config loader does with a parent under ``upstream/``.

A parent is a pinned copy when the ``parent`` reference in the override, taken
relative to the override's directory, passes through a directory named
``upstream`` (any case). Only the segments between the override and the
parent count, so a project that itself lives under a folder called
``upstream`` is unaffected. A parent whose resolved path sits under a
tracked ``upstream/`` directory (one with ``upstream.yaml`` beside it) is
a pinned copy as well, so a symlink from elsewhere cannot present one as
local. A pinned parent must be listed in the
``upstream.yaml`` beside that directory with a matching hash, and only the
app-owned keys in
[ALLOWED_PARENT_KEYS][napt.upstream.pinned.ALLOWED_PARENT_KEYS]
reach the merge; everything else is tenant policy that ``defaults/org.yaml``
keeps owning without the override restating it.

A pinned copy under ``upstream/`` is never run directly; commands run the
override that names it as ``parent``. A "pinned parent" below is a parent
that is a pinned copy, as opposed to a local parent.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
from typing import Any

from napt.exceptions import ConfigError
from napt.upstream.lock import LOCKFILE_NAME, canonical_sha256, read_lockfile

UPSTREAM_DIR_NAME = "upstream"
"""The reserved directory name; compared case-insensitively."""

ALLOWED_PARENT_KEYS: dict[str, frozenset[str] | None] = {
    "apiVersion": None,
    "name": None,
    "id": None,
    "discovery": None,
    "psadt": frozenset(
        {
            "app_vars",
            "install",
            "uninstall",
            "override_msi_commands",
            "override_msix_commands",
        }
    ),
    "intune": frozenset(
        {
            "detection",
            "description",
            "publisher",
            "developer",
            "privacy_url",
            "info_url",
            "run_as_account",
            "run_as_32_bit",
            "device_restart_behavior",
            "max_run_time_minutes",
            "minimum_supported_windows_release",
        }
    ),
}
"""The keys a pinned parent may set.

A top-level key mapped to None is taken whole; one mapped to a set keeps
only the named sub-keys. Any key not listed is dropped, so a field this
version of NAPT does not know never reaches the merge. The rule for a new
recipe field: org-policy fields stay off the list; strategy-specific,
recipe-required, and absent-means-skip fields go on it.
"""


@dataclass(frozen=True)
class PinnedLocation:
    """Where a pinned copy sits relative to its ``upstream/`` directory.

    Attributes:
        upstream_dir: The ``upstream/`` directory the parent is under.
        relative: The parent's path below that directory, forward slashes,
            which is the key its lockfile entry is found by.
    """

    upstream_dir: Path
    relative: PurePosixPath

    @property
    def lockfile(self) -> Path:
        """The ``upstream.yaml`` beside the ``upstream/`` directory."""
        return self.upstream_dir.parent / LOCKFILE_NAME


def _is_upstream_segment(name: str) -> bool:
    """Reports whether a path segment is the reserved directory name."""
    return name.lower() == UPSTREAM_DIR_NAME


def pinned_location(recipe_dir: Path, parent_ref: str) -> PinnedLocation | None:
    """Decides whether a ``parent`` reference points under ``upstream/``.

    Only the path between the override's directory and the parent is
    examined: an absolute reference is first made relative to the
    override, and leading ``..`` segments are skipped. A reference on
    another drive cannot be made relative and is local.

    Args:
        recipe_dir: The directory of the override declaring ``parent``.
        parent_ref: The ``parent`` value as written in the override.

    Returns:
        The parent's location when it is a pinned copy, or None when it is
            a local parent.
    """
    target = os.path.normpath(os.path.join(recipe_dir, parent_ref))
    try:
        relative = os.path.relpath(target, recipe_dir)
    except ValueError:
        return None
    parts = Path(relative).parts
    for index, part in enumerate(parts[:-1]):
        if _is_upstream_segment(part):
            upstream_dir = Path(
                os.path.normpath(recipe_dir.joinpath(*parts[: index + 1]))
            )
            return PinnedLocation(
                upstream_dir=upstream_dir,
                relative=PurePosixPath(*parts[index + 1 :]),
            )
    return None


def tracked_location(path: Path) -> PinnedLocation | None:
    """Finds the tracked ``upstream/`` directory a file really sits under.

    The path is resolved, so a symlink or junction that points into
    ``upstream/`` from elsewhere is seen for what it is. A directory named
    ``upstream`` counts only with an ``upstream.yaml`` beside it, so a
    project that merely lives under a folder called ``upstream`` is not
    affected.

    Args:
        path: A recipe or parent file.

    Returns:
        The file's location under the tracked directory, or None.
    """
    resolved = path.resolve()
    for ancestor in resolved.parents:
        if (
            _is_upstream_segment(ancestor.name)
            and (ancestor.parent / LOCKFILE_NAME).is_file()
        ):
            return PinnedLocation(
                upstream_dir=ancestor,
                relative=PurePosixPath(*resolved.relative_to(ancestor).parts),
            )
    return None


def is_pinned_copy(recipe_path: Path) -> bool:
    """Reports whether a recipe file itself sits under a tracked ``upstream/``.

    Args:
        recipe_path: The recipe a command was asked to run.

    Returns:
        Whether the file is a pinned copy rather than an override.
    """
    return tracked_location(recipe_path) is not None


def verify_pinned_copy(
    parent_path: Path, location: PinnedLocation, data: bytes
) -> None:
    """Checks a pinned parent against its lockfile entry.

    Args:
        parent_path: The parent file, for messages.
        location: Where the parent sits, from
            [pinned_location][napt.upstream.pinned.pinned_location].
        data: The parent's bytes as read from disk.

    Raises:
        ConfigError: When there is no lockfile beside the ``upstream/``
            directory, the lockfile has no entry for the file, or the
            file's canonical hash differs from the recorded one.
    """
    lockfile = location.lockfile
    if not lockfile.is_file():
        raise ConfigError(
            f"{parent_path} is under {location.upstream_dir} but there is no "
            f"{lockfile} tracking it. Pinned copies are written by 'napt "
            f"upstream add'; import the recipe with it, or keep a local parent "
            f"outside a directory named '{UPSTREAM_DIR_NAME}'."
        )
    entry = read_lockfile(lockfile).find(location.relative)
    if entry is None:
        raise ConfigError(
            f"{parent_path} is not tracked in {lockfile}. Import it with 'napt "
            f"upstream add', or delete the file if it was copied in by hand."
        )
    actual = canonical_sha256(data)
    if actual != entry.sha256:
        raise ConfigError(
            f"Pinned copy {parent_path} differs from what {lockfile} "
            f"recorded (sha256 {actual[:12]}, expected {entry.sha256[:12]}). "
            f"Move local edits into the override, or run 'napt upstream update' "
            f"to refresh the pinned copy."
        )


def filter_pinned_parent(
    data: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Keeps only the keys a pinned parent may set.

    A section the allow list restricts is filtered key by key when it is a
    mapping; one of another shape (a list, null, a string) is dropped whole
    and named, since merging it would replace the tenant's section instead
    of adding to it.

    Args:
        data: The parsed parent recipe.

    Returns:
        The filtered copy and the dotted names of every dropped key, in the
            order the parent wrote them.
    """
    kept: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in data.items():
        if key not in ALLOWED_PARENT_KEYS:
            dropped.append(str(key))
            continue
        allowed = ALLOWED_PARENT_KEYS[key]
        if allowed is None:
            kept[key] = value
            continue
        if not isinstance(value, dict):
            dropped.append(str(key))
            continue
        section: dict[str, Any] = {}
        for sub_key, sub_value in value.items():
            if sub_key in allowed:
                section[sub_key] = sub_value
            else:
                dropped.append(f"{key}.{sub_key}")
        # A section left with nothing is left out, so a parent that set only
        # tenant keys in it does not present an empty section to the merge.
        if section:
            kept[key] = section
    return kept, tuple(dropped)
