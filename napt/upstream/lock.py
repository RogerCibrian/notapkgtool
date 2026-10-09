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

"""The ``upstream.yaml`` lockfile.

``upstream.yaml`` sits at the project root beside ``defaults/`` and is
written by ``napt upstream`` alone. It lists every imported repository and,
under each, the recipes imported from it:

    apiVersion: napt/v1
    repos:
      - url: https://github.com/someorg/napt-recipes.git
        ref: main
        recipes:
          - path: recipes/Google/chrome.yaml
            override: recipes/Google/chrome.override.yaml
            commit: 4f2a9c1e0b7d3f8a2c6e1d9b5a4f7c3e8d2b6a1f
            blob: 9c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d
            sha256: 8e1b5f2c...

Each recipe carries its own ``commit``, so one repository's recipes can be
pinned at different points and updated one at a time.

The path of a recipe's pinned copy is never stored; it is derived from the
repository URL and the recipe path, and it is the key the config loader
looks an entry up by. ``sha256`` is over the file's bytes with CRLF line
endings normalized to LF, so a checkout with ``autocrlf`` on Windows hashes
the same as one without.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit

import yaml

from napt.exceptions import ConfigError
from napt.files import write_text_atomic

LOCKFILE_NAME = "upstream.yaml"
"""The lockfile's name; it lives beside the ``upstream/`` directory."""

# user@host:path, the scp-like SSH form, which urlsplit reads as a scheme.
_SCP_LIKE = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^:/]+):(?!//)(?P<path>.+)$")

# Everything a fallback directory name keeps; the rest becomes "_".
_UNSAFE_IN_NAME = re.compile(r"[^A-Za-z0-9._-]")


def canonical_sha256(data: bytes) -> str:
    """Hashes file bytes with Windows line endings normalized.

    Args:
        data: The file's bytes as read from disk or from git.

    Returns:
        The hex digest of the bytes with every CRLF replaced by LF.
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def repo_directory(url: str) -> PurePosixPath:
    """Names the directory under ``upstream/`` that holds a repository's pinned copies.

    The directory is the host plus every path segment of the clone URL,
    with the user, port, ``.git`` suffix, and trailing slash removed, so
    HTTPS, ``ssh://``, and scp-like SSH forms of one repository land in one
    place and nested GitLab groups keep every segment. The host is
    lowercased; path segments keep their case and are compared
    case-insensitively by [Lockfile.find][napt.upstream.lock.Lockfile.find].
    A URL with no host, such as ``file://``, becomes a single directory
    named after the whole URL with unsafe characters replaced.

    Args:
        url: A clone URL as given to ``napt upstream add``.

    Returns:
        The repository's directory relative to ``upstream/``.

    Example:
        Three forms of one repository:
            ```python
            repo_directory("https://github.com/Org/Recipes.git")
            # PurePosixPath("github.com/Org/Recipes")
            repo_directory("git@github.com:Org/Recipes.git")
            # PurePosixPath("github.com/Org/Recipes")
            repo_directory("ssh://git@github.com:2222/Org/Recipes/")
            # PurePosixPath("github.com/Org/Recipes")
            ```
    """
    host: str | None = None
    path = ""
    scp = _SCP_LIKE.match(url)
    if scp and "://" not in url:
        host, path = scp.group("host"), scp.group("path")
    else:
        parts = urlsplit(url)
        host, path = parts.hostname, parts.path
    segments = [segment for segment in path.split("/") if segment]
    if segments and segments[-1].endswith(".git"):
        segments[-1] = segments[-1][: -len(".git")]
    if not host or not segments:
        return PurePosixPath(_UNSAFE_IN_NAME.sub("_", url))
    return PurePosixPath(host.lower(), *segments)


@dataclass(frozen=True)
class LockedRecipe:
    """One imported recipe as the lockfile records it.

    Attributes:
        path: The upstream recipe's path inside its repository, forward
            slashes.
        override: The override that runs it, relative to the project root.
        commit: The commit the pinned copy was taken from.
        blob: The git blob id of the upstream recipe's content.
        sha256: The canonical hash of the pinned copy.
    """

    path: str
    override: str
    commit: str
    blob: str
    sha256: str


@dataclass(frozen=True)
class LockedRepo:
    """One imported repository as the lockfile records it.

    Attributes:
        url: The clone URL as first given.
        ref: The branch or tag the recipes are taken from.
        recipes: The recipes imported from it, each with its own commit.
    """

    url: str
    ref: str
    recipes: tuple[LockedRecipe, ...]


def same_repository(first: str, second: str) -> bool:
    """Reports whether two clone URLs name one repository.

    Args:
        first: A clone URL.
        second: Another clone URL, in any form git accepts.

    Returns:
        True when both map to the same directory under ``upstream/``, compared
            case-insensitively.
    """
    a, b = repo_directory(first).parts, repo_directory(second).parts
    return len(a) == len(b) and all(
        x.lower() == y.lower() for x, y in zip(a, b, strict=True)
    )


@dataclass(frozen=True)
class Lockfile:
    """The parsed ``upstream.yaml``.

    Attributes:
        repos: Every imported repository.
    """

    repos: tuple[LockedRepo, ...]

    def find_repo(self, url: str) -> LockedRepo | None:
        """Finds the entry for a repository by any form of its URL.

        Args:
            url: A clone URL.

        Returns:
            The entry, or None when the repository was never imported.
        """
        for repo in self.repos:
            if same_repository(repo.url, url):
                return repo
        return None

    def replace_repo(self, repo: LockedRepo | None, *, url: str) -> Lockfile:
        """Returns a lockfile with one repository's entry replaced.

        Args:
            repo: The new entry, or None to drop the repository.
            url: The URL identifying the repository to replace; a
                repository not yet listed is appended.

        Returns:
            The new lockfile; this one is unchanged.
        """
        kept = [r for r in self.repos if not same_repository(r.url, url)]
        if repo is not None:
            position = next(
                (i for i, r in enumerate(self.repos) if same_repository(r.url, url)),
                len(kept),
            )
            kept.insert(position, repo)
        return Lockfile(repos=tuple(kept))

    def locate(self, pinned: PurePosixPath) -> tuple[LockedRepo, LockedRecipe] | None:
        """Looks a pinned copy up by its path under ``upstream/``.

        The repository part of the path is compared case-insensitively,
        since GitHub names are and Windows directories collide anyway; the
        recipe path is compared exactly, as git recorded it.

        Args:
            pinned: The file's path relative to the ``upstream/``
                directory, for example
                ``github.com/someorg/napt-recipes/recipes/Google/chrome.yaml``.

        Returns:
            The repository and recipe entries, or None when no repository
                entry tracks that pinned copy.
        """
        parts = pinned.parts
        for repo in self.repos:
            directory = repo_directory(repo.url).parts
            head = parts[: len(directory)]
            if len(head) < len(directory) or any(
                a.lower() != b.lower() for a, b in zip(head, directory, strict=True)
            ):
                continue
            recipe_path = "/".join(parts[len(directory) :])
            for recipe in repo.recipes:
                if recipe.path == recipe_path:
                    return repo, recipe
        return None

    def find(self, pinned: PurePosixPath) -> LockedRecipe | None:
        """Looks a pinned copy's recipe entry up by its path under ``upstream/``.

        Args:
            pinned: The file's path relative to the ``upstream/`` directory.

        Returns:
            The matching entry, or None; see
                [locate][napt.upstream.lock.Lockfile.locate].
        """
        located = self.locate(pinned)
        return located[1] if located is not None else None


def _string(mapping: dict[str, Any], key: str, where: str, lockfile: Path) -> str:
    """Reads a required string field from a lockfile mapping."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(
            f"Malformed {lockfile}: {where} needs a non-empty string '{key}'. "
            f"The file is written by napt upstream; restore it from git or "
            f"run 'napt upstream add' again."
        )
    return value


def _parse_lockfile(data: bytes, lockfile: Path) -> Lockfile:
    """Parses lockfile bytes, checking the shape every consumer relies on."""
    try:
        parsed = yaml.safe_load(data.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as err:
        raise ConfigError(f"Malformed {lockfile}: {err}") from err
    if not isinstance(parsed, dict) or not isinstance(parsed.get("repos"), list):
        raise ConfigError(
            f"Malformed {lockfile}: expected a mapping with a 'repos' list. The "
            f"file is written by napt upstream; restore it from git or run "
            f"'napt upstream add' again."
        )
    repos: list[LockedRepo] = []
    for index, repo in enumerate(parsed["repos"]):
        where = f"repos[{index}]"
        if not isinstance(repo, dict) or not isinstance(repo.get("recipes"), list):
            raise ConfigError(
                f"Malformed {lockfile}: {where} needs 'url', 'ref', and a "
                f"'recipes' list"
            )
        recipes: list[LockedRecipe] = []
        for position, entry in enumerate(repo["recipes"]):
            entry_where = f"{where}.recipes[{position}]"
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"Malformed {lockfile}: {entry_where} must be a mapping"
                )
            recipes.append(
                LockedRecipe(
                    path=_string(entry, "path", entry_where, lockfile),
                    override=_string(entry, "override", entry_where, lockfile),
                    commit=_string(entry, "commit", entry_where, lockfile),
                    blob=_string(entry, "blob", entry_where, lockfile),
                    sha256=_string(entry, "sha256", entry_where, lockfile),
                )
            )
        repos.append(
            LockedRepo(
                url=_string(repo, "url", where, lockfile),
                ref=_string(repo, "ref", where, lockfile),
                recipes=tuple(recipes),
            )
        )
    return Lockfile(repos=tuple(repos))


_HEADER = """\
# Written by napt upstream. Do not edit by hand: it records, for every
# pinned copy under upstream/, the commit it was taken from, its blob id,
# and its sha256, and the config loader checks each pinned copy against it.
"""


def write_lockfile(path: Path, lock: Lockfile) -> None:
    """Writes ``upstream.yaml`` atomically, after a fixed header comment.

    Args:
        path: The lockfile.
        lock: What to write.

    Raises:
        OSError: When the file cannot be written.
    """
    document = {
        "apiVersion": "napt/v1",
        "repos": [
            {
                "url": repo.url,
                "ref": repo.ref,
                "recipes": [
                    {
                        "path": recipe.path,
                        "override": recipe.override,
                        "commit": recipe.commit,
                        "blob": recipe.blob,
                        "sha256": recipe.sha256,
                    }
                    for recipe in repo.recipes
                ],
            }
            for repo in lock.repos
        ],
    }
    body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    write_text_atomic(path, _HEADER + body)


@lru_cache(maxsize=8)
def _read_lockfile_version(path: str, mtime_ns: int, size: int) -> Lockfile:
    """Reads and parses one version of a lockfile; cached by its stat."""
    del mtime_ns, size  # Part of the cache key only.
    try:
        data = Path(path).read_bytes()
    except OSError as err:
        raise ConfigError(f"Cannot read {path}: {err}") from err
    return _parse_lockfile(data, Path(path))


def read_lockfile(path: Path) -> Lockfile:
    """Reads ``upstream.yaml``, once per version of the file per run.

    A directory run loads many recipes that share one lockfile; the parsed
    result is reused until the file's size or modification time changes.

    Args:
        path: The lockfile.

    Returns:
        The parsed lockfile.

    Raises:
        ConfigError: When the file does not exist, cannot be read, is not
            valid YAML, or does not have the shape ``napt upstream``
            writes.
    """
    try:
        stat = path.stat()
    except FileNotFoundError as err:
        raise ConfigError(f"{path} does not exist") from err
    except OSError as err:
        raise ConfigError(f"Cannot read {path}: {err}") from err
    return _read_lockfile_version(str(path), stat.st_mtime_ns, stat.st_size)
