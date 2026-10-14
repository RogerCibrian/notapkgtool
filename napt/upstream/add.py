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

"""Importing recipes from a git repository: the engine behind ``napt upstream add``.

An import writes each selected upstream recipe byte-identical as a pinned
copy under ``upstream/<host>/<repo path>/<path>``, writes an override in
``recipes/`` that names the pinned copy as its ``parent`` and carries the
recipe's ``name`` and ``id``, and records each recipe's commit and hashes in
``upstream.yaml``.
Nothing is written until every selected recipe has been fetched and the
configuration each override will produce has passed validation, so a bad
recipe aborts the whole import with the project untouched.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from napt.config.loader import LoadedParent, collect_recipe_paths, merge_config_layers
from napt.exceptions import ConfigError
from napt.files import write_bytes_atomic, write_text_atomic
from napt.logging import get_global_logger
from napt.upstream.git import FetchedRef, TreeEntry, check_upstream_path, ls_remote
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
from napt.upstream.pinned import UPSTREAM_DIR_NAME, filter_pinned_parent
from napt.validation import validate_config

OVERRIDE_SUFFIX = ".override.yaml"
"""What an override file is named: ``<app>.override.yaml``."""

# The upstream directory segment whose descendants mirror into recipes/.
_RECIPES_SEGMENT = "recipes"


@dataclass(frozen=True)
class PlannedRecipe:
    """One recipe the import will write, or did write.

    Attributes:
        path: The recipe's path inside the repository.
        pinned: Where the pinned copy lands, relative to the project
            root.
        override: The override that runs it, relative to the project root.
        app_id: The ``id`` the override carries.
        dropped: The keys the allow list removes from the pinned copy.
        duplicate_of: Another recipe in the project that already uses the
            same ``id``, or None.
    """

    path: str
    pinned: str
    override: str
    app_id: str
    dropped: tuple[str, ...]
    duplicate_of: str | None = None


@dataclass(frozen=True)
class AddResult:
    """What ``napt upstream add`` imported.

    Attributes:
        url: The clone URL as given.
        ref: The branch or tag imported from.
        commit: The commit fetched, recorded on each imported recipe.
        recipes: Each recipe written, in repository order.
        skipped: Recipes selected through a directory that were already
            imported, left at their own pins.
        dry_run: Whether nothing was written.
    """

    url: str
    ref: str
    commit: str
    recipes: tuple[PlannedRecipe, ...]
    skipped: tuple[str, ...]
    dry_run: bool


def override_path_for(
    upstream_path: str, imported_from: str, dest: str | None
) -> PurePosixPath:
    """Decides where the override for an upstream recipe lives.

    One rule for files and directories: everything after the last
    ``recipes/`` segment of the upstream path is mirrored under the
    project's ``recipes/`` (or under ``dest``), so ``recipes/Google/
    chrome.yaml`` lands at ``recipes/Google/chrome.override.yaml`` however
    it was selected. Without such a segment, ``dest`` is required and the
    file lands under it at its path relative to the imported directory,
    which for a single file is its name.

    Args:
        upstream_path: The recipe's path inside the repository.
        imported_from: The ``--path`` it was selected through.
        dest: The ``--dest`` directory, relative to the project root, or
            None.

    Returns:
        The override's path relative to the project root.

    Raises:
        ConfigError: When the path has no ``recipes/`` segment and no
            ``dest`` was given.
    """
    parts = PurePosixPath(upstream_path).parts
    directories = parts[:-1]
    name = PurePosixPath(parts[-1]).stem + OVERRIDE_SUFFIX
    if _RECIPES_SEGMENT in directories:
        last = len(directories) - 1 - directories[::-1].index(_RECIPES_SEGMENT)
        below = directories[last + 1 :]
        root = PurePosixPath(dest) if dest else PurePosixPath(_RECIPES_SEGMENT)
        return root.joinpath(*below, name)
    if dest is None:
        raise ConfigError(
            f"{upstream_path!r} has no 'recipes/' segment to mirror; pass "
            f"--dest <directory> to say where its override goes"
        )
    base = PurePosixPath(imported_from)
    if PurePosixPath(upstream_path) == base:
        return PurePosixPath(dest, name)
    relative = PurePosixPath(upstream_path).relative_to(base)
    return PurePosixPath(dest).joinpath(*relative.parts[:-1], name)


def _select_entries(
    fetched: FetchedRef, paths: Iterable[str], excludes: Iterable[str]
) -> list[tuple[str, TreeEntry]]:
    """Lists the recipe files under each path, minus the exclude globs.

    Returns:
        ``(imported_from, entry)`` pairs in tree order; a file under two
            paths is listed once.
    """
    patterns = list(excludes)
    seen: set[str] = set()
    selected: list[tuple[str, TreeEntry]] = []
    for path in paths:
        entries = fetched.list_recipe_files([path])
        if not entries:
            raise ConfigError(
                f"No recipe files (.yaml or .yml) under {path!r} at the fetched ref"
            )
        for entry in entries:
            relative = (
                str(PurePosixPath(entry.path).relative_to(path))
                if entry.path != path
                else PurePosixPath(entry.path).name
            )
            if any(fnmatch.fnmatchcase(relative, p) for p in patterns):
                continue
            if entry.path in seen:
                continue
            seen.add(entry.path)
            selected.append((path, entry))
    return selected


def _project_ids(project_root: Path) -> dict[str, str]:
    """Maps each ``id`` declared under ``recipes/`` to the file declaring it."""
    recipes_dir = project_root / _RECIPES_SEGMENT
    if not recipes_dir.is_dir():
        return {}
    try:
        paths = collect_recipe_paths(recipes_dir)
    except ConfigError:  # An empty recipes/ holds no ids.
        return {}
    found: dict[str, str] = {}
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        app_id = data.get("id") if isinstance(data, dict) else None
        if isinstance(app_id, str) and app_id not in found:
            found[app_id] = path.relative_to(project_root).as_posix()
    return found


def _override_text(
    url: str, ref: str, upstream_path: str, pinned: str, obj: dict[str, Any]
) -> str:
    """Renders the override file: a header comment, then its four fields."""
    body = yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)
    return (
        f"# Imported by napt upstream from\n"
        f"# {url} (ref {ref})\n"
        f"# path {upstream_path}\n"
        f"# Pinned copy: {pinned}\n"
        f"# Customize this file. Never edit the pinned copy.\n" + body
    )


def add_recipes(
    project_root: Path,
    url: str,
    paths: Iterable[str],
    *,
    ref: str | None = None,
    dest: str | None = None,
    app_id: str | None = None,
    excludes: Iterable[str] = (),
    dry_run: bool = False,
) -> AddResult:
    """Imports recipes from a repository into the project.

    Args:
        project_root: The directory holding ``recipes/``, ``upstream/``,
            and ``upstream.yaml``; the current directory for the CLI.
        url: The clone URL.
        paths: Files or directories inside the repository to import. A
            directory skips recipes already tracked, so re-running it picks
            up what the publisher added since; a file already tracked is an
            error pointing at ``update``.
        ref: A branch or tag; the default branch when None. A repository
            already in the lockfile keeps its recorded ref, and a
            different one is an error.
        dest: Where the overrides go instead of mirroring under
            ``recipes/``, relative to the project root.
        app_id: An ``id`` for the override instead of the upstream one;
            single-file imports only.
        excludes: Globs matched against each file's path relative to the
            directory it was selected through.
        dry_run: Report what would be written and write nothing.

    Returns:
        What was imported, or would be.

    Raises:
        ConfigError: When a selection, path, override, or the configuration
            an override would produce is invalid; nothing is written.
        NetworkError: When the repository cannot be reached.
    """
    logger = get_global_logger()
    paths = list(paths)
    if not paths:
        raise ConfigError("At least one --path is required")
    lockfile_path = project_root / LOCKFILE_NAME
    lock = read_lockfile(lockfile_path) if lockfile_path.is_file() else Lockfile(())
    existing = lock.find_repo(url)
    if existing is not None and ref is not None and ref != existing.ref:
        raise ConfigError(
            f"{url} is already imported from ref {existing.ref!r}; a second ref "
            f"({ref!r}) for one repository is not supported. Remove its recipes "
            f"first, or import from {existing.ref!r}."
        )
    directory = repo_directory(url)
    check_upstream_path(directory.as_posix())

    logger.info("UPSTREAM", f"Checking {url}")
    remote = ls_remote(url)
    if existing is not None:
        ref = existing.ref
    elif ref is None:
        ref = remote.default_branch
        if ref is None:
            raise ConfigError(
                f"{url} reports no default branch; pass --ref <branch or tag>"
            )
    if remote.commit_for(ref) is None:
        raise ConfigError(f"{url} has no branch or tag named {ref!r}")

    logger.info("UPSTREAM", f"Fetching {ref} from {url}")
    with FetchedRef(url, ref) as fetched:
        selected = _select_entries(fetched, paths, excludes)
        if app_id is not None and len(selected) != 1:
            raise ConfigError(
                f"--id applies to a single-file import; this selection has "
                f"{len(selected)} recipes"
            )
        known_ids = _project_ids(project_root)
        planned: list[tuple[PlannedRecipe, bytes, str]] = []
        skipped: list[str] = []
        for imported_from, entry in selected:
            # A directory import picks up what the publisher added since the
            # last one; recipes already tracked keep their own pins and are
            # refreshed by update, never by add. A recipe named directly
            # still errors below, since update is what was meant.
            pinned_rel = PurePosixPath(UPSTREAM_DIR_NAME, *directory.parts, entry.path)
            if imported_from != entry.path and _lock_entry_exists(
                project_root, pinned_rel
            ):
                skipped.append(entry.path)
                continue
            planned.append(
                _plan_one(
                    project_root,
                    fetched,
                    url,
                    ref,
                    directory,
                    entry,
                    imported_from,
                    dest,
                    app_id,
                    known_ids,
                )
            )
        commit = fetched.commit

    for recipe, _data, _text in planned:
        if recipe.dropped:
            logger.warning(
                "UPSTREAM",
                f"{recipe.path}: ignoring keys not allowed from upstream recipes: "
                + ", ".join(recipe.dropped),
            )
        if recipe.duplicate_of:
            logger.warning(
                "UPSTREAM",
                f"{recipe.path}: id {recipe.app_id!r} is already used by "
                f"{recipe.duplicate_of}; pass --id to choose another",
            )
    result = AddResult(
        url=url,
        ref=ref,
        commit=commit,
        recipes=tuple(recipe for recipe, _data, _text in planned),
        skipped=tuple(skipped),
        dry_run=dry_run,
    )
    if dry_run or not planned:
        return result

    # Pinned copies first, then overrides, then the lockfile. A run cut
    # short after a pinned copy leaves a file nothing names, which the next
    # run overwrites; one cut short after an override is reported by the
    # loader (its parent is not in the lockfile) and blocks the retry until
    # that override is removed, so the window for it is kept as late as
    # possible.
    for recipe, data, _text in planned:
        logger.verbose("UPSTREAM", f"Writing {recipe.pinned}")
        write_bytes_atomic(project_root / recipe.pinned, data)
    for recipe, _data, text in planned:
        logger.verbose("UPSTREAM", f"Writing {recipe.override}")
        write_text_atomic(project_root / recipe.override, text)
    entries = list(existing.recipes) if existing is not None else []
    for recipe, data, _text in planned:
        tree_entry = next(e for _p, e in selected if e.path == recipe.path)
        entries.append(
            LockedRecipe(
                path=recipe.path,
                override=recipe.override,
                commit=commit,
                blob=tree_entry.blob,
                sha256=canonical_sha256(data),
            )
        )
    repo = LockedRepo(
        url=existing.url if existing is not None else url,
        ref=ref,
        recipes=tuple(entries),
    )
    write_lockfile(lockfile_path, lock.replace_repo(repo, url=url))
    logger.verbose("UPSTREAM", f"Updated {lockfile_path.name}")
    return result


def _plan_one(
    project_root: Path,
    fetched: FetchedRef,
    url: str,
    ref: str,
    directory: PurePosixPath,
    entry: TreeEntry,
    imported_from: str,
    dest: str | None,
    app_id: str | None,
    known_ids: dict[str, str],
) -> tuple[PlannedRecipe, bytes, str]:
    """Fetches one recipe and checks everything about it before any write.

    Returns:
        The plan, the pinned copy's bytes, and the override text.
    """
    data = fetched.read_file(entry.path)
    try:
        parsed: Any = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as err:
        raise ConfigError(f"{entry.path} in {url} is not valid YAML: {err}") from err
    if not isinstance(parsed, dict):
        raise ConfigError(f"{entry.path} in {url} is not a recipe (not a mapping)")
    if "parent" in parsed:
        raise ConfigError(
            f"{entry.path} in {url} declares a parent of its own and cannot be "
            f"imported as a parent; exclude it with --exclude "
            f"{PurePosixPath(entry.path).name!r} or import the recipe it names"
        )

    pinned_rel = PurePosixPath(UPSTREAM_DIR_NAME, *directory.parts, entry.path)
    override_rel = override_path_for(entry.path, imported_from, dest)
    for segment in override_rel.parts:
        check_upstream_path(segment)
    override_abs = project_root / override_rel
    if override_abs.exists():
        raise ConfigError(
            f"{override_rel} already exists; napt upstream add never overwrites "
            f"an override. Remove it, or pass --dest to put the import elsewhere."
        )
    if _lock_entry_exists(project_root, pinned_rel):
        raise ConfigError(
            f"{entry.path} from {url} is already imported ({pinned_rel}); run "
            f"'napt upstream update' to refresh it"
        )

    kept, dropped = filter_pinned_parent(parsed)
    name = parsed.get("name")
    chosen_id = app_id if app_id is not None else parsed.get("id")
    override_obj: dict[str, Any] = {"apiVersion": "napt/v1"}
    parent_ref = os.path.relpath(
        project_root / pinned_rel, override_abs.parent
    ).replace(os.sep, "/")
    override_obj["parent"] = parent_ref
    # Whatever shape the upstream recipe gave these, validation below reports
    # a missing or non-string value before anything is written.
    override_obj["name"] = name
    override_obj["id"] = chosen_id

    parent = LoadedParent(
        path=(project_root / pinned_rel).resolve(), data=kept, dropped=dropped
    )
    merged = merge_config_layers(override_abs, override_obj, parent)
    result = validate_config(merged, recipe_path=str(override_abs))
    if result.errors:
        raise ConfigError(
            f"{entry.path} from {url} would not validate as {override_rel}: "
            + "; ".join(result.errors)
        )
    logger = get_global_logger()
    for warning in result.warnings:
        logger.warning("UPSTREAM", f"{entry.path}: {warning}")
    # Validation rejected a missing id above, so this is always set.
    app_id_final = result.app_id or ""
    duplicate = known_ids.get(app_id_final)
    # Later recipes in this import see the earlier ones' ids too.
    known_ids.setdefault(app_id_final, f"{entry.path} (this import)")
    plan = PlannedRecipe(
        path=entry.path,
        pinned=pinned_rel.as_posix(),
        override=override_rel.as_posix(),
        app_id=app_id_final,
        dropped=dropped,
        duplicate_of=duplicate,
    )
    text = _override_text(url, ref, entry.path, pinned_rel.as_posix(), override_obj)
    return plan, data, text


def _lock_entry_exists(project_root: Path, pinned_rel: PurePosixPath) -> bool:
    """Reports whether the lockfile already tracks a pinned copy's path."""
    lockfile_path = project_root / LOCKFILE_NAME
    if not lockfile_path.is_file():
        return False
    below_upstream = PurePosixPath(*pinned_rel.parts[1:])
    return read_lockfile(lockfile_path).find(below_upstream) is not None
