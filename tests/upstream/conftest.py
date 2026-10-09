"""Shared fixtures for the upstream tests: throwaway git repositories.

Every git command a fixture runs has the developer's global and system
configuration hidden and a fixed identity, so commit signing, hooks, and
aliases configured on the machine never reach a test.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from napt.upstream.git import _LOCAL_REPO_ENV

CHROME_RECIPE = b"""apiVersion: napt/v1
name: Google Chrome
id: google-chrome
discovery:
  strategy: url_download
  url: https://dl.google.com/chrome.msi
psadt:
  release: "4.0.0"
  app_vars:
    AppName: Google Chrome
intune:
  build_types: update_only
  description: From upstream
deployment:
  rings: []
"""

FIREFOX_RECIPE = b"""apiVersion: napt/v1
name: Mozilla Firefox
id: mozilla-firefox
discovery:
  strategy: url_download
  url: https://download.mozilla.org/firefox.msi
"""


class Repo:
    """A throwaway git repository the tests push commits into.

    Every git command runs with the developer's global and system
    configuration hidden and a fixed identity, so commit signing, hooks,
    and aliases configured on the machine never reach the fixture.
    """

    def __init__(self, path: Path, empty_config: Path) -> None:
        self.path = path
        self.env = {
            **{k: v for k, v in os.environ.items() if k not in _LOCAL_REPO_ENV},
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "GIT_CONFIG_SYSTEM": str(empty_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        self.git("init", "-q", "-b", "main")
        self.git("config", "uploadpack.allowFilter", "true")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")

    @property
    def url(self) -> str:
        """The file:// URL git fetches this repository by."""
        return self.path.resolve().as_uri()

    def git(self, *args: str) -> str:
        """Runs git in the repository and returns its stdout."""
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def commit(self, files: dict[str, bytes], message: str = "Add files") -> str:
        """Writes files, commits them, and returns the commit id."""
        for name, data in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self.git("add", "--", name)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def commit_path(self, path: str, data: bytes, mode: str = "100644") -> str:
        """Commits an index entry directly: an odd path, or a symlink mode."""
        blob = (
            subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=self.path,
                env=self.env,
                input=data,
                capture_output=True,
                check=True,
            )
            .stdout.decode()
            .strip()
        )
        self.git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}")
        tree = self.git("write-tree").strip()
        parent = self.git("rev-parse", "HEAD").strip()
        commit = self.git("commit-tree", tree, "-p", parent, "-m", "Odd path").strip()
        self.git("update-ref", "refs/heads/main", commit)
        return commit


def _empty_config(tmp_path: Path) -> Path:
    empty = tmp_path / "empty-gitconfig"
    if not empty.exists():
        empty.write_text("")
    return empty


@pytest.fixture
def repo(tmp_path) -> Repo:
    """A repository holding one small recipe on main (transport tests)."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    origin = tmp_path / "origin"
    origin.mkdir()
    fixture = Repo(origin, _empty_config(tmp_path))
    fixture.commit(
        {
            "recipes/Google/chrome.yaml": (
                b"apiVersion: napt/v1\nname: Google Chrome\nid: chrome\n"
            ),
            "README.md": b"# r\n",
        }
    )
    return fixture


@pytest.fixture
def upstream(tmp_path) -> Repo:
    """A publisher's repository with two full recipes and a base recipe."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    origin = tmp_path / "origin"
    origin.mkdir()
    fixture = Repo(origin, _empty_config(tmp_path))
    fixture.commit(
        {
            "recipes/Google/chrome.yaml": CHROME_RECIPE,
            "recipes/Mozilla/firefox.yaml": FIREFOX_RECIPE,
            "recipes/README.md": b"# recipes\n",
            "recipe-bases/base.yaml": FIREFOX_RECIPE,
        }
    )
    return fixture


@pytest.fixture
def project(tmp_path) -> Path:
    """A NAPT project whose org.yaml sets tenant policy an upstream recipe may not."""
    root = tmp_path / "project"
    (root / "defaults").mkdir(parents=True)
    (root / "defaults" / "org.yaml").write_text(
        "apiVersion: napt/v1\nintune:\n  build_types: both\n"
        "deployment:\n  rings:\n    - name: ours\n      groups: [g]\n"
    )
    (root / "recipes").mkdir()
    return root
