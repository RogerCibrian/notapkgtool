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

"""Read-only git transport for upstream recipe repositories.

Every network operation of ``napt upstream`` goes through the ``git``
binary, so authentication is whatever git already does (credential
helpers, SSH keys) and any host that serves git works. Nothing here
touches the user's own repository: a fetch lands in a temporary directory
that is removed when the operation ends.

Three guards apply to every value that reaches git from a lockfile or a
command line, because ``upstream.yaml`` can be edited by anyone who can
open a pull request:

- A URL, ref, or path that starts with ``-`` is refused, so git never
  reads one as an option.
- Positional arguments follow ``--`` wherever git accepts it.
- ``GIT_ALLOW_PROTOCOL`` limits transports to ``https``, ``ssh``, ``git``,
  and ``file``, so an ``ext::`` URL, which runs a command, is never
  reachable.

Prompts are disabled (``GIT_TERMINAL_PROMPT=0``, SSH batch mode) so a
missing credential fails at once instead of hanging a CI job. The
variables that would point git at another repository (``GIT_DIR`` and its
relatives, which git exports into hooks) are dropped from the environment,
and a ``git`` found in the current directory is refused, so the user's own
repository is never the one acted on.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit, urlunsplit

from napt.exceptions import ConfigError, NetworkError
from napt.logging import get_global_logger
from napt.paths import is_safe_path_component

ALLOWED_PROTOCOLS = "https:ssh:git:file"
"""Transports git may use; ``ext`` and other command-running schemes are out."""

RECIPE_SUFFIXES = (".yaml", ".yml")
"""File name endings that make a tree entry a recipe."""

# Seconds one git call may take before it is reported as a network failure.
_TIMEOUT = 300

# Tree entry modes of a regular file (plain and executable).
_REGULAR_FILE_MODES = frozenset({"100644", "100755"})

# Set on every call, over whatever the user's environment holds.
_GIT_FIXED_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
    "GIT_ALLOW_PROTOCOL": ALLOWED_PROTOCOLS,
}

# The variables that point git at a repository other than the one in its
# working directory. Git exports them into hooks and the commands they run,
# so a `napt upstream check` wired into a pre-commit hook would otherwise
# fetch into the user's own .git. This is git's own local_repo_env list,
# the set it clears before running a command in a submodule.
_LOCAL_REPO_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_GRAFT_FILE",
    "GIT_SHALLOW_FILE",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_IMPLICIT_WORK_TREE",
)


def find_git() -> str:
    """Locates the git binary.

    On Windows the search includes the current directory, which for
    ``napt upstream`` is the user's project; a ``git.cmd`` committed there
    must never be what runs, so a result in the current directory is
    refused rather than used.

    Returns:
        The path to ``git``.

    Raises:
        ConfigError: When git is not on ``PATH``, or the only match is in
            the current directory.
    """
    found = shutil.which("git")
    if found is None:
        raise ConfigError(
            "git is required for napt upstream and was not found on PATH. "
            "Install it from https://git-scm.com/downloads and try again."
        )
    if Path(found).resolve().parent == Path.cwd().resolve():
        raise ConfigError(
            f"Refusing to run {found}: it is in the current directory, not on "
            f"PATH. Remove it or run napt from another directory."
        )
    return found


def redact_url(value: str) -> str:
    """Hides the user information of a URL for logs and messages.

    Args:
        value: Any command argument; one that is not a URL with user
            information is returned unchanged.

    Returns:
        The value with ``user:password@`` replaced by ``***@``.
    """
    if "://" not in value:
        return value
    parts = urlsplit(value)
    if not parts.username and not parts.password:
        return value
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit(parts._replace(netloc=f"***@{host}"))


def check_argument(value: str, what: str) -> str:
    """Refuses a value git would read as an option.

    Args:
        value: A URL, ref name, or repository path about to be passed to
            git.
        what: What the value is, for the message ("URL", "ref", "path").

    Returns:
        The value, unchanged.

    Raises:
        ConfigError: When the value is empty or starts with ``-``.
    """
    if not value:
        raise ConfigError(f"The {what} is empty")
    if value.startswith("-"):
        raise ConfigError(
            f"Refusing {what} {value!r}: a value starting with '-' would be read "
            f"by git as an option"
        )
    return value


def _environment() -> dict[str, str]:
    """Builds the environment every git call runs with.

    The user's environment passes through, so credential helpers, proxies,
    ``GIT_SSH_COMMAND``, and the ``GIT_CONFIG_COUNT`` family keep working,
    minus the variables that would point git at another repository.
    """
    env = {
        key: value for key, value in os.environ.items() if key not in _LOCAL_REPO_ENV
    }
    env.update(_GIT_FIXED_ENV)
    if "GIT_SSH_COMMAND" not in env and "GIT_SSH" not in env:
        env["GIT_SSH_COMMAND"] = "ssh -oBatchMode=yes"
    return env


def run_git(args: list[str], cwd: Path | None = None) -> bytes:
    """Runs one git command and returns its stdout.

    Args:
        args: The arguments after ``git``.
        cwd: The repository to run in, or None for a command that needs
            none (``ls-remote``).

    Returns:
        The command's stdout, as bytes, because paths and refs are not
            guaranteed to be UTF-8.

    Raises:
        ConfigError: When git is not installed.
        NetworkError: When git exits non-zero (the message carries its
            stderr), times out, or cannot be launched.
    """
    logger = get_global_logger()
    git = find_git()
    shown = [redact_url(arg) for arg in args]
    logger.verbose("UPSTREAM", "git " + " ".join(shown))
    try:
        completed = subprocess.run(
            [git, *args],
            cwd=cwd,
            capture_output=True,
            timeout=_TIMEOUT,
            env=_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        raise NetworkError(
            f"git {args[0]} did not finish within {_TIMEOUT} seconds"
        ) from err
    except OSError as err:
        raise NetworkError(f"Cannot run git: {err}") from err
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    for raw, safe in zip(args, shown, strict=True):
        if raw != safe:
            stderr = stderr.replace(raw, safe)
    if completed.returncode != 0:
        raise NetworkError(
            f"git {args[0]} failed (exit {completed.returncode}): "
            f"{stderr or 'no error output'}"
        )
    if stderr:
        # Partial fetches print promisor notices on success; never an error.
        logger.debug("UPSTREAM", stderr)
    return completed.stdout


@dataclass(frozen=True)
class RemoteRefs:
    """What ``git ls-remote`` reported for a repository.

    Attributes:
        default_branch: The branch ``HEAD`` points at, or None when the
            server did not say.
        refs: Each full ref name (``refs/heads/main``, ``refs/tags/v1``,
            and the peeled ``refs/tags/v1^{}`` of an annotated tag) mapped
            to its object id.
    """

    default_branch: str | None
    refs: dict[str, str]

    def commit_for(self, ref: str) -> str | None:
        """Finds the commit a branch or tag name points at.

        A branch wins over a tag of the same name. An annotated tag
        resolves through its peeled entry to the commit, so a pinned
        commit compares against commits only.

        Args:
            ref: A branch or tag name as the user gave it, or a full ref.

        Returns:
            The commit id, or None when the remote has no such ref.
        """
        for candidate in (
            f"refs/heads/{ref}",
            f"refs/tags/{ref}^{{}}",
            f"refs/tags/{ref}",
            f"{ref}^{{}}",
            ref,
        ):
            found = self.refs.get(candidate)
            if found is not None:
                return found
        return None


def ls_remote(url: str) -> RemoteRefs:
    """Lists a repository's refs without fetching anything.

    Args:
        url: The clone URL.

    Returns:
        The default branch and every ref with its object id.

    Raises:
        ConfigError: When git is missing or the URL starts with ``-``.
        NetworkError: When the repository cannot be reached.
    """
    check_argument(url, "URL")
    output = run_git(["ls-remote", "--symref", "--", url])
    default_branch: str | None = None
    refs: dict[str, str] = {}
    for raw in output.decode("utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        left, _, right = raw.partition("\t")
        if left.startswith("ref: ") and right == "HEAD":
            target = left[len("ref: ") :]
            if target.startswith("refs/heads/"):
                default_branch = target[len("refs/heads/") :]
            continue
        if right:
            refs[right] = left
    return RemoteRefs(default_branch=default_branch, refs=refs)


@dataclass(frozen=True)
class TreeEntry:
    """One recipe file in a fetched tree.

    Attributes:
        path: The file's path from the repository root, forward slashes.
        blob: The git blob id of its content.
    """

    path: str
    blob: str


def check_vendored_path(path: str) -> str:
    """Refuses a repository path that cannot become a directory tree here.

    Every segment must satisfy
    [is_safe_path_component][napt.paths.is_safe_path_component] with
    spaces allowed, so ``..``, reserved device names, trailing dots, and
    characters Windows forbids never reach the filesystem.

    Args:
        path: A path from ``git ls-tree``, forward slashes.

    Returns:
        The path, unchanged.

    Raises:
        ConfigError: When a segment is unsafe, naming it.
    """
    for segment in path.split("/"):
        if not is_safe_path_component(segment, allow_spaces=True):
            raise ConfigError(
                f"Cannot vendor {path!r}: the path segment {segment!r} is not a "
                f"safe directory or file name (letters, digits, spaces, '.', "
                f"'-', '_', '+', starting with a letter or digit)"
            )
    return path


class FetchedRef:
    """A repository's ref fetched trees-only into a temporary directory.

    Use as a context manager; the directory and everything git wrote into
    it are removed on exit. ``TemporaryDirectory`` already retries after
    resetting permissions, which is what git's read-only pack files need
    on Windows.

    Example:
        Read one file at a branch tip:
            ```python
            with FetchedRef(url, "main") as fetched:
                data = fetched.read_file("recipes/Google/chrome.yaml")
            ```

    Attributes:
        commit: The commit the ref resolved to when fetched; the value the
            lockfile pins.
    """

    def __init__(self, url: str, ref: str) -> None:
        """Fetches the ref's tip without its blobs.

        Args:
            url: The clone URL.
            ref: A branch or tag name.

        Raises:
            ConfigError: When git is missing or a value starts with ``-``.
            NetworkError: When the fetch fails.
        """
        check_argument(url, "URL")
        check_argument(ref, "ref")
        self._tempdir = tempfile.TemporaryDirectory(prefix="napt-upstream-")
        self._dir = Path(self._tempdir.name)
        try:
            run_git(["init", "-q", "-b", "main"], cwd=self._dir)
            run_git(["remote", "add", "origin", "--", url], cwd=self._dir)
            # A named remote is required: below git 2.24 a filtered fetch
            # from a bare URL dies, and the promisor configuration git writes
            # lands on the remote by name.
            run_git(
                [
                    "fetch",
                    "--quiet",
                    "--depth",
                    "1",
                    "--filter=blob:none",
                    "origin",
                    ref,
                ],
                cwd=self._dir,
            )
            # FETCH_HEAD rather than ls-remote's answer, so a push between
            # the two calls cannot pin a commit the files did not come from;
            # ^{commit} dereferences an annotated tag.
            self.commit = (
                run_git(["rev-parse", "FETCH_HEAD^{commit}"], cwd=self._dir)
                .decode("ascii")
                .strip()
            )
        except BaseException:
            self._tempdir.cleanup()
            raise

    def __enter__(self) -> FetchedRef:
        """Returns the fetched ref for use inside a ``with`` block."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Removes the temporary directory, whatever happened inside."""
        del exc_info  # The directory goes either way.
        self._tempdir.cleanup()

    def list_recipe_files(self, paths: Iterable[str]) -> list[TreeEntry]:
        """Lists the recipe files under the given repository paths.

        A directory lists every ``.yaml`` and ``.yml`` beneath it; a file
        lists itself. Each returned path has passed
        [check_vendored_path][napt.upstream.git.check_vendored_path].

        Args:
            paths: Files or directories relative to the repository root.

        Returns:
            The matching files with their blob ids, in tree order.

        Raises:
            ConfigError: When a path starts with ``-`` or a listed file's
                path has an unsafe segment.
            NetworkError: When git fails.
        """
        wanted = [check_argument(path, "path") for path in paths]
        output = run_git(
            ["ls-tree", "-r", "-z", self.commit, "--", *wanted], cwd=self._dir
        )
        entries: list[TreeEntry] = []
        for record in output.split(b"\0"):
            if not record:
                continue
            meta, _, path = record.partition(b"\t")
            mode, kind, blob = meta.decode("ascii").split(" ")
            name = path.decode("utf-8", errors="replace")
            # A symlink is listed as a blob too (mode 120000); only regular
            # files are recipes.
            if mode not in _REGULAR_FILE_MODES or kind != "blob":
                continue
            if not name.endswith(RECIPE_SUFFIXES):
                continue
            entries.append(TreeEntry(path=check_vendored_path(name), blob=blob))
        return entries

    def read_file(self, path: str) -> bytes:
        """Reads one file's exact bytes at the fetched commit.

        The blob is fetched from the remote on demand; no line-ending or
        filter conversion is applied.

        Args:
            path: The file's path from the repository root.

        Returns:
            The file's content as git stores it.

        Raises:
            ConfigError: When the path starts with ``-`` or names no file
                at the commit (a lockfile or command-line problem, not a
                network one).
            NetworkError: When the blob cannot be fetched.
        """
        check_argument(path, "path")
        # The trees are local, so this answers without touching the network
        # and separates "no such file" from a failed blob fetch.
        listed = run_git(["ls-tree", "-z", self.commit, "--", path], cwd=self._dir)
        if not listed:
            raise ConfigError(
                f"{path!r} does not exist at commit {self.commit[:12]} of the "
                f"fetched ref"
            )
        return run_git(["cat-file", "blob", f"{self.commit}:{path}"], cwd=self._dir)
