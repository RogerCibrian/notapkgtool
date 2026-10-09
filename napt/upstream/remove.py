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

"""Removing an imported recipe: the engine behind ``napt upstream remove``.

Removal deletes the pinned copy and its lockfile entry, the repository's
entry and emptied directories under ``upstream/`` once nothing of it
remains, and the lockfile itself once no repository remains. The override
is the user's file, so it is left alone unless asked; it is reported with
its now-dangling ``parent`` so the user can inline it or delete it.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath

from napt.exceptions import ConfigError
from napt.logging import get_global_logger
from napt.upstream.git import check_upstream_path
from napt.upstream.lock import (
    LOCKFILE_NAME,
    LockedRepo,
    Lockfile,
    read_lockfile,
    repo_directory,
    write_lockfile,
)
from napt.upstream.pinned import (
    UPSTREAM_DIR_NAME,
    pinned_copy_of_override,
    tracked_location,
)


@dataclass(frozen=True)
class RemoveResult:
    """What ``napt upstream remove`` did.

    Attributes:
        path: The pinned copy that was deleted, relative to the project
            root.
        override: The override that named it, relative to the project
            root, or None when the lockfile recorded none that exists.
        override_deleted: Whether the override was deleted too.
        repo_removed: Whether this was the repository's last recipe, so
            its lockfile entry and directory went with it.
    """

    path: str
    override: str | None
    override_deleted: bool
    repo_removed: bool


def _recorded_override(project_root: Path, recorded: str, pinned: Path) -> Path | None:
    """Finds the override the lockfile names, only if it really is one.

    The lockfile is a repository file anyone with write access can edit,
    and this path is about to be deleted on request, so it is trusted no
    further than ``add`` trusts what it writes: relative, with safe
    segments, inside the project, outside ``upstream/``, and declaring the
    pinned copy as its ``parent``.

    Args:
        project_root: The project the lockfile belongs to.
        recorded: The entry's ``override`` field.
        pinned: The pinned copy being removed, resolved.

    Returns:
        The override, or None when none exists at the recorded path.

    Raises:
        ConfigError: When the recorded path is not a safe project-relative
            path, or the file there does not name the pinned copy.
    """
    check_upstream_path(recorded)
    candidate = (project_root / recorded).resolve()
    root = project_root.resolve()
    if root not in candidate.parents or (root / UPSTREAM_DIR_NAME) in candidate.parents:
        raise ConfigError(
            f"{LOCKFILE_NAME} records {recorded!r} as the override, which is not "
            f"a recipe path inside this project; fix the entry by hand"
        )
    if not candidate.is_file():
        return None
    if pinned_copy_of_override(candidate) != pinned:
        raise ConfigError(
            f"{candidate} does not name {pinned} as its parent, although "
            f"{LOCKFILE_NAME} records it as the override; fix the entry by hand"
        )
    return candidate


def _prune_empty_dirs(start: Path, stop: Path) -> None:
    """Removes empty directories from ``start`` up to, not including, ``stop``."""
    current = start
    while current != stop and current.is_dir() and not any(current.iterdir()):
        current.rmdir()
        current = current.parent


def remove_recipe(
    project_root: Path, path: Path, *, delete_override: bool = False
) -> RemoveResult:
    """Removes one imported recipe from the project.

    Args:
        project_root: The directory holding ``upstream/`` and
            ``upstream.yaml``; the current directory for the CLI.
        path: The pinned copy under ``upstream/``, or the override that
            names it as ``parent``.
        delete_override: Delete the override as well.

    Returns:
        What was removed.

    Raises:
        ConfigError: When the path is neither a tracked pinned copy nor
            an override naming one, the pinned copy belongs to another
            project's ``upstream/``, the lockfile is missing or malformed,
            or the override the lockfile records is not a project recipe
            naming the pinned copy.
    """
    logger = get_global_logger()
    lockfile_path = project_root / LOCKFILE_NAME
    given = path.resolve()
    location = tracked_location(given)
    override_path: Path | None = None
    if location is None:
        override_path = given
        pinned = pinned_copy_of_override(given)
        location = tracked_location(pinned)
        if location is None:
            raise ConfigError(
                f"{given} names {pinned} as parent, which is not under a "
                f"tracked {UPSTREAM_DIR_NAME}/ directory"
            )
    else:
        pinned = given

    # The pinned copy must belong to this project. tracked_location accepts
    # any upstream/ with a lockfile beside it, so a parent pointing into
    # another checkout would otherwise be deleted against this lockfile.
    own_upstream = (project_root / UPSTREAM_DIR_NAME).resolve()
    if location.upstream_dir != own_upstream:
        raise ConfigError(
            f"{pinned} is under {location.upstream_dir}, not this project's "
            f"{own_upstream}; run napt upstream remove from that project"
        )

    lock = read_lockfile(lockfile_path)
    located = lock.locate(location.relative)
    if located is None:
        raise ConfigError(
            f"{pinned} is not tracked in {lockfile_path}; delete the file by hand "
            f"if it was copied in"
        )
    repo, entry = located
    directory = repo_directory(repo.url).parts

    if override_path is None:
        override_path = _recorded_override(project_root, entry.override, pinned)

    logger.info("UPSTREAM", f"Removing {entry.path} from {repo.url}")
    try:
        pinned.unlink(missing_ok=True)
    except OSError as err:
        raise ConfigError(f"Cannot delete {pinned}: {err}") from err
    _prune_empty_dirs(pinned.parent, location.upstream_dir)

    remaining = tuple(r for r in repo.recipes if r is not entry)
    repo_removed = not remaining
    new_lock: Lockfile = lock.replace_repo(
        (None if repo_removed else LockedRepo(repo.url, repo.ref, remaining)),
        url=repo.url,
    )
    if new_lock.repos:
        write_lockfile(lockfile_path, new_lock)
    else:
        # Nothing imported remains, so the lockfile goes too; the next add
        # recreates it.
        lockfile_path.unlink()
    if repo_removed:
        _prune_empty_dirs(
            location.upstream_dir / Path(*directory), location.upstream_dir
        )
        if location.upstream_dir.is_dir() and not any(location.upstream_dir.iterdir()):
            location.upstream_dir.rmdir()

    override_deleted = False
    override_rel: str | None = None
    if override_path is not None:
        override_rel = os.path.relpath(override_path, project_root).replace(os.sep, "/")
        if delete_override:
            try:
                override_path.unlink()
            except OSError as err:
                raise ConfigError(f"Cannot delete {override_path}: {err}") from err
            override_deleted = True
        else:
            logger.warning(
                "UPSTREAM",
                f"{override_rel} still names the removed file as parent; inline "
                f"the recipe there or delete it (napt upstream remove "
                f"--delete-override)",
            )
    return RemoveResult(
        path=PurePosixPath(UPSTREAM_DIR_NAME, *location.relative.parts).as_posix(),
        override=override_rel,
        override_deleted=override_deleted,
        repo_removed=repo_removed,
    )
