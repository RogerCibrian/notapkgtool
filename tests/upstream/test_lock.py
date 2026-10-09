"""Tests for napt.upstream.lock: hashing, repository directories, the lockfile."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from napt.exceptions import ConfigError
from napt.upstream.lock import (
    LockedRecipe,
    LockedRepo,
    Lockfile,
    canonical_sha256,
    read_lockfile,
    repo_directory,
    write_lockfile,
)

_LOCKFILE = """apiVersion: napt/v1
repos:
  - url: https://github.com/SomeOrg/napt-recipes.git
    ref: main
    recipes:
      - path: recipes/Google/chrome.yaml
        override: recipes/Google/chrome.override.yaml
        commit: 4f2a9c1e0b7d3f8a2c6e1d9b5a4f7c3e8d2b6a1f
        blob: 9c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d
        sha256: abc123
"""


class TestCanonicalSha256:
    """Tests for the line-ending-independent hash."""

    def test_crlf_and_lf_hash_the_same(self):
        """Tests that a Windows checkout hashes like a Unix one."""
        assert canonical_sha256(b"a: 1\r\nb: 2\r\n") == canonical_sha256(
            b"a: 1\nb: 2\n"
        )

    def test_content_change_changes_the_hash(self):
        """Tests that a one-character edit is detected."""
        assert canonical_sha256(b"a: 1\n") != canonical_sha256(b"a: 2\n")


class TestRepoDirectory:
    """Tests for the directory a repository's pinned copies land in."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/Org/Recipes.git",
            "https://github.com/Org/Recipes",
            "https://github.com/Org/Recipes/",
            "https://GitHub.com:443/Org/Recipes.git",
            "ssh://git@github.com:2222/Org/Recipes.git",
            "git@github.com:Org/Recipes.git",
        ],
    )
    def test_every_form_of_one_repository_lands_in_one_place(self, url):
        """Tests that HTTPS, ssh://, and scp-like forms agree."""
        assert repo_directory(url) == PurePosixPath("github.com/Org/Recipes")

    def test_nested_groups_keep_every_segment(self):
        """Tests that a GitLab subgroup path is not flattened."""
        assert repo_directory("https://gitlab.com/group/sub/project.git") == (
            PurePosixPath("gitlab.com/group/sub/project")
        )

    def test_url_without_a_host_names_a_single_directory(self):
        """Tests that a file:// URL falls back to a sanitized whole-URL name."""
        directory = repo_directory("file:///E:/repos/recipes.git")

        assert len(directory.parts) == 1
        assert directory.parts[0] == "file____E__repos_recipes.git"


class TestLockfileFind:
    """Tests for looking an entry up by its pinned copy's path."""

    @staticmethod
    def _lockfile() -> Lockfile:
        entry = LockedRecipe(
            path="recipes/Google/chrome.yaml",
            override="recipes/Google/chrome.override.yaml",
            commit="4f2a",
            blob="9c1d",
            sha256="abc",
        )
        repo = LockedRepo(
            url="https://github.com/SomeOrg/napt-recipes.git",
            ref="main",
            recipes=(entry,),
        )
        return Lockfile(repos=(repo,))

    def test_finds_a_repository_by_any_url_form(self):
        """Tests that scp-like and https forms find the same entry."""
        lock = self._lockfile()

        assert lock.find_repo("git@github.com:someorg/NAPT-recipes.git") is not None
        assert lock.find_repo("https://gitlab.com/x/y.git") is None

    def test_replace_repo_keeps_position_and_appends_new(self):
        """Tests that replacing keeps order and None drops the entry."""
        lock = self._lockfile()
        other = LockedRepo(url="https://gitlab.com/x/y.git", ref="main", recipes=())

        appended = lock.replace_repo(other, url=other.url)
        replaced = appended.replace_repo(
            LockedRepo(url=lock.repos[0].url, ref="v2", recipes=()),
            url="git@github.com:SomeOrg/napt-recipes.git",
        )
        dropped = replaced.replace_repo(None, url=other.url)

        assert [r.url for r in appended.repos] == [lock.repos[0].url, other.url]
        assert replaced.repos[0].ref == "v2" and replaced.repos[1] == other
        assert [r.url for r in dropped.repos] == [lock.repos[0].url]

    def test_finds_by_pinned_copy_path(self):
        """Tests that the derived directory plus the recipe path is the key."""
        found = self._lockfile().find(
            PurePosixPath("github.com/SomeOrg/napt-recipes/recipes/Google/chrome.yaml")
        )

        assert found is not None and found.sha256 == "abc"

    def test_repository_directory_matches_case_insensitively(self):
        """Tests that a differently cased directory still matches its entry."""
        found = self._lockfile().find(
            PurePosixPath("GitHub.com/someorg/NAPT-recipes/recipes/Google/chrome.yaml")
        )

        assert found is not None

    def test_recipe_path_matches_exactly(self):
        """Tests that the recipe path inside the repository is case-sensitive."""
        found = self._lockfile().find(
            PurePosixPath("github.com/SomeOrg/napt-recipes/recipes/google/chrome.yaml")
        )

        assert found is None

    def test_unknown_repository_is_not_found(self):
        """Tests that a path under another repository's directory is None."""
        found = self._lockfile().find(
            PurePosixPath("gitlab.com/x/y/recipes/Google/chrome.yaml")
        )

        assert found is None


class TestReadLockfile:
    """Tests for reading and validating upstream.yaml."""

    def test_reads_a_well_formed_lockfile(self, tmp_path):
        """Tests that entries come back with path and sha256."""
        lockfile = tmp_path / "upstream.yaml"
        lockfile.write_text(_LOCKFILE)

        lock = read_lockfile(lockfile)

        assert lock.repos[0].url == "https://github.com/SomeOrg/napt-recipes.git"
        assert lock.repos[0].ref == "main"
        assert lock.repos[0].recipes[0] == LockedRecipe(
            path="recipes/Google/chrome.yaml",
            override="recipes/Google/chrome.override.yaml",
            commit="4f2a9c1e0b7d3f8a2c6e1d9b5a4f7c3e8d2b6a1f",
            blob="9c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d",
            sha256="abc123",
        )

    def test_round_trip_through_write(self, tmp_path):
        """Tests that a written lockfile reads back equal, header included."""
        lockfile = tmp_path / "upstream.yaml"
        lockfile.write_text(_LOCKFILE)
        lock = read_lockfile(lockfile)
        target = tmp_path / "out" / "upstream.yaml"

        write_lockfile(target, lock)

        assert target.read_text().startswith("# Written by napt upstream.")
        assert read_lockfile(target) == lock

    def test_missing_lockfile_is_a_config_error(self, tmp_path):
        """Tests that a lockfile that does not exist is reported, not raised raw."""
        with pytest.raises(ConfigError, match="does not exist"):
            read_lockfile(tmp_path / "upstream.yaml")

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("- not a mapping\n", "expected a mapping with a 'repos' list"),
            ("apiVersion: napt/v1\nrepos: {}\n", "expected a mapping"),
            ("repos:\n  - url: x\n", r"repos\[0\] needs"),
            (
                _LOCKFILE.replace("    ref: main\n", ""),
                r"repos\[0\] needs a non-empty string 'ref'",
            ),
            (
                _LOCKFILE.replace("        sha256: abc123\n", ""),
                r"recipes\[0\] needs a non-empty string 'sha256'",
            ),
            (
                _LOCKFILE.replace("      - path:", "      - 5\n      - path:"),
                "must be a mapping",
            ),
            ("repos: [\n", "Malformed"),
        ],
    )
    def test_malformed_lockfile_is_a_config_error(self, tmp_path, text, match):
        """Tests that each shape napt upstream never writes is reported."""
        lockfile = tmp_path / "upstream.yaml"
        lockfile.write_text(text)

        with pytest.raises(ConfigError, match=match):
            read_lockfile(lockfile)

    def test_unreadable_lockfile_is_a_config_error(self, tmp_path, monkeypatch):
        """Tests that a read failure is reported as a ConfigError."""
        lockfile = tmp_path / "upstream.yaml"
        lockfile.write_text(_LOCKFILE)

        def _refuse(self):
            raise PermissionError("locked")

        monkeypatch.setattr(Path, "read_bytes", _refuse)

        with pytest.raises(ConfigError, match="Cannot read .*locked"):
            read_lockfile(lockfile)

    def test_unstatable_lockfile_is_a_config_error(self, tmp_path, monkeypatch):
        """Tests that a stat failure other than not-found is a ConfigError."""
        lockfile = tmp_path / "upstream.yaml"

        def _refuse(self, *args, **kwargs):
            raise PermissionError("no access")

        monkeypatch.setattr(Path, "stat", _refuse)

        with pytest.raises(ConfigError, match="Cannot read .*no access"):
            read_lockfile(lockfile)

    def test_same_version_is_parsed_once(self, tmp_path):
        """Tests that an unchanged lockfile is reused across loads in one run."""
        lockfile = tmp_path / "upstream.yaml"
        lockfile.write_text(_LOCKFILE)

        first = read_lockfile(lockfile)
        second = read_lockfile(lockfile)

        assert second is first

    def test_rewritten_lockfile_is_read_again(self, tmp_path):
        """Tests that a changed lockfile is not served from the cache."""
        lockfile = tmp_path / "upstream.yaml"
        lockfile.write_text(_LOCKFILE)
        before = read_lockfile(lockfile)
        lockfile.write_text(_LOCKFILE.replace("abc123", "def456"))

        after = read_lockfile(lockfile)

        assert after is not before
        assert after.repos[0].recipes[0].sha256 == "def456"
