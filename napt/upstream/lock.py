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
under each, the recipes vendored from it:

    apiVersion: napt/v1
    repos:
      - url: https://github.com/someorg/napt-recipes.git
        ref: main
        commit: 4f2a9c1e0b7d3f8a2c6e1d9b5a4f7c3e8d2b6a1f
        recipes:
          - path: recipes/Google/chrome.yaml
            override: recipes/Google/chrome.override.yaml
            blob: 9c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d
            sha256: 8e1b5f2c...

The vendored location of a recipe is never stored; it is derived from the
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
    """Names the directory under ``upstream/`` a repository vendors into.

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
    """One vendored recipe as the lockfile records it.

    Attributes:
        path: The recipe's path inside its repository, forward slashes.
        sha256: The canonical hash of the vendored copy.
    """

    path: str
    sha256: str


@dataclass(frozen=True)
class LockedRepo:
    """One imported repository as the lockfile records it.

    Attributes:
        url: The clone URL as first given.
        recipes: The recipes vendored from it.
    """

    url: str
    recipes: tuple[LockedRecipe, ...]


@dataclass(frozen=True)
class Lockfile:
    """The parsed ``upstream.yaml``.

    Attributes:
        repos: Every imported repository.
    """

    repos: tuple[LockedRepo, ...]

    def find(self, vendored: PurePosixPath) -> LockedRecipe | None:
        """Looks a vendored file up by its path under ``upstream/``.

        The repository part of the path is compared case-insensitively,
        since GitHub names are and Windows directories collide anyway; the
        recipe path is compared exactly, as git recorded it.

        Args:
            vendored: The file's path relative to the ``upstream/``
                directory, for example
                ``github.com/someorg/napt-recipes/recipes/Google/chrome.yaml``.

        Returns:
            The matching entry, or None when no repository vendors that
                file.
        """
        parts = vendored.parts
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
                    return recipe
        return None


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
    # Every field napt upstream writes is required, so a malformed file is
    # rejected whole, but only the fields the loader reads are kept; a later
    # consumer that reads ref, commit, blob, or override adds it to the model.
    repos: list[LockedRepo] = []
    for index, repo in enumerate(parsed["repos"]):
        where = f"repos[{index}]"
        if not isinstance(repo, dict) or not isinstance(repo.get("recipes"), list):
            raise ConfigError(
                f"Malformed {lockfile}: {where} needs 'url', 'ref', 'commit', "
                f"and a 'recipes' list"
            )
        url = _string(repo, "url", where, lockfile)
        for key in ("ref", "commit"):
            _string(repo, key, where, lockfile)
        recipes: list[LockedRecipe] = []
        for position, entry in enumerate(repo["recipes"]):
            entry_where = f"{where}.recipes[{position}]"
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"Malformed {lockfile}: {entry_where} must be a mapping"
                )
            for key in ("override", "blob"):
                _string(entry, key, entry_where, lockfile)
            recipes.append(
                LockedRecipe(
                    path=_string(entry, "path", entry_where, lockfile),
                    sha256=_string(entry, "sha256", entry_where, lockfile),
                )
            )
        repos.append(LockedRepo(url=url, recipes=tuple(recipes)))
    return Lockfile(repos=tuple(repos))


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
