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

"""Checking pinned copies against their upstream recipes, and refreshing them.

``napt upstream check`` and ``napt upstream update`` run the same scan.
Per repository in ``upstream.yaml``: one ``ls-remote``; when the branch
tip equals every selected recipe's ``commit`` and nothing needs rewriting,
the fetch is skipped and only the local hashes are verified. Otherwise the
ref is fetched trees-only once and each recipe's recorded blob id is
compared to the one at its path now. ``update`` then rewrites the pinned
copies that changed, each with its own new ``commit``, and leaves every
other entry alone, so a run can refresh one recipe at a time and CI can
open one pull request per recipe.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from napt.exceptions import ConfigError
from napt.files import write_bytes_atomic
from napt.logging import get_global_logger
from napt.upstream.git import FetchedRef, ls_remote
from napt.upstream.lock import (
    LOCKFILE_NAME,
    LockedRecipe,
    LockedRepo,
    Lockfile,
    canonical_sha256,
    read_lockfile,
    repo_directory,
    write_lockfile,
)
from napt.upstream.pinned import (
    UPSTREAM_DIR_NAME,
    filter_pinned_parent,
    pinned_copy_of_override,
    tracked_location,
)

UNCHANGED = "unchanged"
CHANGED = "changed"
MISSING = "missing"
MODIFIED_LOCALLY = "modified-locally"


@dataclass(frozen=True)
class RecipeStatus:
    """What the scan found for one pinned copy.

    Attributes:
        url: The repository's clone URL as the lockfile records it.
        path: The upstream recipe's path inside the repository.
        override: The override that runs it, relative to the project root.
        status: One of ``unchanged``, ``changed``, ``missing``, or
            ``modified-locally``.
        old_commit: The commit the pinned copy was taken from.
        new_commit: The commit the ref resolves to now, or None when the
            fetch was skipped.
        old_blob: The recorded blob id.
        new_blob: The blob id at the path now, or None when missing or when
            the fetch was skipped.
        updated: Whether ``update`` rewrote the pinned copy in this run.
        dropped: The keys the allow list removes from the new content; set
            only when the pinned copy was rewritten.
    """

    url: str
    path: str
    override: str
    status: str
    old_commit: str
    new_commit: str | None
    old_blob: str
    new_blob: str | None
    updated: bool = False
    dropped: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefreshResult:
    """What ``napt upstream check`` found, or ``update`` did.

    Attributes:
        recipes: One status per selected recipe, in lockfile order.
        wrote: Whether the run was allowed to rewrite pinned copies.
    """

    recipes: tuple[RecipeStatus, ...]
    wrote: bool

    @property
    def drifted(self) -> tuple[RecipeStatus, ...]:
        """The recipes whose upstream changed or disappeared."""
        return tuple(r for r in self.recipes if r.status in (CHANGED, MISSING))

    @property
    def refused(self) -> tuple[RecipeStatus, ...]:
        """The locally modified pinned copies an update left alone.

        Empty for a check, which refuses nothing because it writes nothing.
        """
        if not self.wrote:
            return ()
        return tuple(
            r for r in self.recipes if r.status == MODIFIED_LOCALLY and not r.updated
        )


def _pinned_path(project_root: Path, repo: LockedRepo, entry: LockedRecipe) -> Path:
    """Where a lockfile entry's pinned copy lives."""
    return (
        project_root
        / UPSTREAM_DIR_NAME
        / Path(*repo_directory(repo.url).parts, entry.path)
    )


def _select(
    project_root: Path, lock: Lockfile, paths: Iterable[Path]
) -> dict[str, set[str]]:
    """Maps each repository URL to the recipe paths a run covers.

    Args:
        project_root: The project the lockfile belongs to.
        lock: The parsed lockfile.
        paths: Overrides or pinned copies to limit the run to; none means
            every tracked recipe.

    Returns:
        Selected recipe paths keyed by repository URL.

    Raises:
        ConfigError: When a path is neither a tracked pinned copy nor an
            override naming one in this project.
    """
    wanted = list(paths)
    if not wanted:
        return {repo.url: {r.path for r in repo.recipes} for repo in lock.repos}
    own_upstream = (project_root / UPSTREAM_DIR_NAME).resolve()
    selected: dict[str, set[str]] = {}
    for given in wanted:
        resolved = given.resolve()
        location = tracked_location(resolved)
        if location is None:
            resolved = pinned_copy_of_override(resolved)
            location = tracked_location(resolved)
        if location is None or location.upstream_dir != own_upstream:
            raise ConfigError(
                f"{given} is not a pinned copy in this project's "
                f"{UPSTREAM_DIR_NAME}/ nor an override naming one"
            )
        located = lock.locate(location.relative)
        if located is None:
            raise ConfigError(f"{given} is not tracked in {LOCKFILE_NAME}")
        repo, entry = located
        selected.setdefault(repo.url, set()).add(entry.path)
    return selected


def refresh(
    project_root: Path,
    *,
    write: bool,
    paths: Iterable[Path] = (),
    force: bool = False,
    quiet: bool = False,
) -> RefreshResult:
    """Scans the tracked recipes against upstream and optionally refreshes them.

    Args:
        project_root: The directory holding ``upstream/`` and
            ``upstream.yaml``; the current directory for the CLI.
        write: Rewrite changed pinned copies and the lockfile (``update``),
            or only report (``check``).
        paths: Overrides or pinned copies to limit the run to.
        force: With ``write``, also rewrite pinned copies that were edited
            locally, from the upstream recipe at the tip.
        quiet: Print no progress or warning lines; the result carries the
            same facts (``dropped`` per recipe), for a caller that prints
            machine-readable output.

    Returns:
        One status per selected recipe.

    Raises:
        ConfigError: When there is no lockfile, a path is not tracked, or a
            repository's ref no longer exists.
        NetworkError: When a repository cannot be reached.
    """
    logger = get_global_logger()
    lockfile_path = project_root / LOCKFILE_NAME
    if not lockfile_path.is_file():
        raise ConfigError(
            f"{lockfile_path} does not exist; nothing has been imported with "
            f"'napt upstream add'"
        )
    lock = read_lockfile(lockfile_path)
    selected = _select(project_root, lock, paths)

    statuses: list[RecipeStatus] = []
    new_lock = lock
    for repo in lock.repos:
        wanted = selected.get(repo.url)
        if not wanted:
            continue
        entries = [e for e in repo.recipes if e.path in wanted]
        updated_entries = {e.path: e for e in repo.recipes}

        # Local drift first: it needs no network and decides what a forced
        # update has to rewrite.
        local_ok: dict[str, bool] = {}
        for entry in entries:
            pinned = _pinned_path(project_root, repo, entry)
            try:
                local_ok[entry.path] = (
                    canonical_sha256(pinned.read_bytes()) == entry.sha256
                )
            except OSError:
                local_ok[entry.path] = False

        if not quiet:
            logger.info("UPSTREAM", f"Checking {repo.url}")
        tip = ls_remote(repo.url).commit_for(repo.ref)
        if tip is None:
            raise ConfigError(
                f"{repo.url} no longer has a branch or tag named {repo.ref!r}"
            )
        needs_fetch = any(e.commit != tip for e in entries) or (
            write and force and not all(local_ok.values())
        )
        if not needs_fetch:
            for entry in entries:
                statuses.append(
                    RecipeStatus(
                        url=repo.url,
                        path=entry.path,
                        override=entry.override,
                        status=UNCHANGED if local_ok[entry.path] else MODIFIED_LOCALLY,
                        old_commit=entry.commit,
                        new_commit=None,
                        old_blob=entry.blob,
                        new_blob=None,
                    )
                )
            continue

        if not quiet:
            logger.info("UPSTREAM", f"Fetching {repo.ref} from {repo.url}")
        with FetchedRef(repo.url, repo.ref) as fetched:
            listed = {
                t.path: t.blob
                for t in fetched.list_recipe_files([e.path for e in entries])
            }
            for entry in entries:
                new_blob = listed.get(entry.path)
                if new_blob is None:
                    status = MISSING
                elif not local_ok[entry.path]:
                    status = MODIFIED_LOCALLY
                elif new_blob != entry.blob:
                    status = CHANGED
                else:
                    status = UNCHANGED
                record = RecipeStatus(
                    url=repo.url,
                    path=entry.path,
                    override=entry.override,
                    status=status,
                    old_commit=entry.commit,
                    new_commit=fetched.commit,
                    old_blob=entry.blob,
                    new_blob=new_blob,
                )
                rewrite = write and (
                    status == CHANGED or (status == MODIFIED_LOCALLY and force)
                )
                if rewrite and new_blob is not None:
                    data = fetched.read_file(entry.path)
                    dropped = _dropped_keys(data)
                    if dropped and not quiet:
                        logger.warning(
                            "UPSTREAM",
                            f"{entry.path}: ignoring keys not allowed from upstream "
                            f"recipes: " + ", ".join(dropped),
                        )
                    pinned = _pinned_path(project_root, repo, entry)
                    logger.verbose("UPSTREAM", f"Writing {pinned}")
                    write_bytes_atomic(pinned, data)
                    updated_entries[entry.path] = replace(
                        entry,
                        commit=fetched.commit,
                        blob=new_blob,
                        sha256=canonical_sha256(data),
                    )
                    record = replace(record, updated=True, dropped=dropped)
                statuses.append(record)
        new_lock = new_lock.replace_repo(
            LockedRepo(
                url=repo.url,
                ref=repo.ref,
                recipes=tuple(updated_entries[e.path] for e in repo.recipes),
            ),
            url=repo.url,
        )

    if write and new_lock != lock:
        write_lockfile(lockfile_path, new_lock)
        logger.verbose("UPSTREAM", f"Updated {lockfile_path.name}")
    return RefreshResult(recipes=tuple(statuses), wrote=write)


def _dropped_keys(data: bytes) -> tuple[str, ...]:
    """Names the keys the allow list will drop from new upstream content.

    Content that does not parse as a mapping is written anyway; the
    loader reports it when the override is next run.
    """
    try:
        parsed = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        return ()
    if not isinstance(parsed, dict):
        return ()
    return filter_pinned_parent(parsed)[1]
