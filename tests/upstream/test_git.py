"""Tests for napt.upstream.git against real repositories under tmp_path."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

from napt.exceptions import ConfigError, NetworkError
import napt.upstream.git as git_module
from napt.upstream.git import (
    _LOCAL_REPO_ENV,
    FetchedRef,
    RemoteRefs,
    TreeEntry,
    check_argument,
    check_vendored_path,
    find_git,
    ls_remote,
    redact_url,
    run_git,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)

_RECIPE = b"apiVersion: napt/v1\nname: Google Chrome\nid: chrome\n"
_RECIPE_CRLF = _RECIPE.replace(b"\n", b"\r\n")


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


@pytest.fixture
def repo(tmp_path) -> Repo:
    """A repository holding one recipe on main."""
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("")
    origin = tmp_path / "origin"
    origin.mkdir()
    fixture = Repo(origin, empty_config)
    fixture.commit({"recipes/Google/chrome.yaml": _RECIPE, "README.md": b"# r\n"})
    return fixture


class TestGuards:
    """Tests for the three guards on values handed to git."""

    def test_missing_git_is_a_config_error(self, monkeypatch):
        """Tests that an absent git binary is reported with where to get it."""
        monkeypatch.setattr(git_module.shutil, "which", lambda _name: None)

        with pytest.raises(ConfigError, match="git is required"):
            find_git()

    @pytest.mark.parametrize("value", ["-oProxyCommand=calc", "--upload-pack=x", "-"])
    def test_leading_dash_is_refused(self, value):
        """Tests that a value git would read as an option never reaches it."""
        with pytest.raises(ConfigError, match="starting with '-'"):
            check_argument(value, "ref")

    def test_empty_value_is_refused(self):
        """Tests that an empty URL or ref is reported, not passed to git."""
        with pytest.raises(ConfigError, match="URL is empty"):
            check_argument("", "URL")

    def test_ext_transport_is_blocked(self, tmp_path):
        """Tests that an ext:: URL, which runs a command, is refused by git."""
        marker = tmp_path / "ran"

        with pytest.raises(NetworkError, match="ls-remote failed"):
            ls_remote(f"ext::{sys.executable} -c open('{marker}','w') %S")

        assert not marker.exists()

    def test_ssh_batch_mode_is_set_unless_the_user_set_one(self, monkeypatch):
        """Tests that prompts are disabled by default and respected when set."""
        monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
        monkeypatch.delenv("GIT_SSH", raising=False)
        assert git_module._environment()["GIT_SSH_COMMAND"] == "ssh -oBatchMode=yes"
        assert git_module._environment()["GIT_TERMINAL_PROMPT"] == "0"
        assert git_module._environment()["GIT_ALLOW_PROTOCOL"] == "https:ssh:git:file"

        monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i mykey")

        assert git_module._environment()["GIT_SSH_COMMAND"] == "ssh -i mykey"

    def test_git_in_the_current_directory_is_refused(self, tmp_path, monkeypatch):
        """Tests that a git.cmd in the project root is never what runs."""
        planted = tmp_path / "git.cmd"
        planted.write_text("@echo off\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(git_module.shutil, "which", lambda _name: str(planted))

        with pytest.raises(ConfigError, match="in the current directory"):
            find_git()

    def test_repository_location_variables_are_dropped(
        self, repo, tmp_path, monkeypatch
    ):
        """Tests that a GIT_DIR from a hook cannot redirect the fetch."""
        (tmp_path / "decoy").mkdir()
        decoy = Repo(tmp_path / "decoy", tmp_path / "empty-gitconfig")
        monkeypatch.setenv("GIT_DIR", str(decoy.path / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(decoy.path))
        monkeypatch.setenv("GIT_CONFIG_COUNT", "0")

        env = git_module._environment()
        with FetchedRef(repo.url, "main") as fetched:
            fetched.read_file("recipes/Google/chrome.yaml")

        assert "GIT_DIR" not in env and "GIT_WORK_TREE" not in env
        assert env["GIT_CONFIG_COUNT"] == "0"
        assert decoy.git("remote").strip() == ""
        assert not (decoy.path / ".git" / "shallow").exists()

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://user:tok@github.com/o/r.git", "https://***@github.com/o/r.git"),
            ("https://tok@github.com:8443/o/r", "https://***@github.com:8443/o/r"),
            ("https://github.com/o/r.git", "https://github.com/o/r.git"),
            ("git@github.com:o/r.git", "git@github.com:o/r.git"),
            ("ls-remote", "ls-remote"),
        ],
    )
    def test_user_information_is_redacted(self, url, expected):
        """Tests that a token embedded in a URL never reaches a log line."""
        assert redact_url(url) == expected

    def test_credentials_never_appear_in_output_or_errors(self, capsys):
        """Tests that -v output and the error text carry the redacted URL."""
        from napt.logging import Logger, set_global_logger

        set_global_logger(Logger(verbose=True))
        url = "https://user:s3cret@127.0.0.1:9/nowhere.git"

        with pytest.raises(NetworkError) as err:
            ls_remote(url)

        assert "s3cret" not in str(err.value)
        assert "s3cret" not in capsys.readouterr().out

    def test_nonzero_exit_carries_stderr(self, tmp_path):
        """Tests that a failing git command becomes a NetworkError with its stderr."""
        with pytest.raises(NetworkError, match=r"git ls-remote failed \(exit \d+\)"):
            ls_remote((tmp_path / "nowhere").as_uri())

    def test_timeout_is_a_network_error(self, monkeypatch):
        """Tests that a hung git call is reported instead of waited on forever."""

        def _hang(*_args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=kwargs["timeout"])

        monkeypatch.setattr(git_module.subprocess, "run", _hang)

        with pytest.raises(NetworkError, match="did not finish"):
            run_git(["ls-remote", "--", "x"])

    def test_unlaunchable_git_is_a_network_error(self, tmp_path, monkeypatch):
        """Tests that an OSError from launching git is reported."""
        missing = str(tmp_path / "bin" / "git-nope")
        monkeypatch.setattr(git_module.shutil, "which", lambda _name: missing)

        with pytest.raises(NetworkError, match="Cannot run git"):
            run_git(["ls-remote", "--", "x"])


class TestCheckVendoredPath:
    """Tests for the segment rule applied to upstream file paths."""

    @pytest.mark.parametrize(
        "path",
        [
            "recipes/Google/chrome.yaml",
            "recipes/Visual Studio Code/vscode.yaml",
            "Notepad++/npp.yml",
        ],
    )
    def test_ordinary_paths_pass(self, path):
        """Tests that vendor folders with spaces and plus signs are accepted."""
        assert check_vendored_path(path) == path

    @pytest.mark.parametrize(
        ("path", "segment"),
        [
            ("recipes/../evil.yaml", ".."),
            ("recipes/CON/x.yaml", "CON"),
            ("recipes/trailing./x.yaml", "trailing."),
            ("recipes/ leading/x.yaml", " leading"),
            ("recipes/a:b/x.yaml", "a:b"),
            ("recipes/.hidden/x.yaml", ".hidden"),
            ("recipes/café/x.yaml", "café"),
        ],
    )
    def test_unsafe_segment_is_named(self, path, segment):
        """Tests that each rejected segment is reported by name."""
        with pytest.raises(ConfigError, match=f"segment {segment!r}"):
            check_vendored_path(path)


class TestLsRemote:
    """Tests for listing refs."""

    def test_reports_default_branch_and_refs(self, repo):
        """Tests that the symref gives the default branch and refs carry ids."""
        head = repo.git("rev-parse", "HEAD").strip()

        refs = ls_remote(repo.url)

        assert refs.default_branch == "main"
        assert refs.commit_for("main") == head

    def test_branch_with_a_slash_resolves(self, repo):
        """Tests that feature/x is looked up as refs/heads/feature/x."""
        repo.git("branch", "feature/x")

        assert ls_remote(repo.url).commit_for("feature/x") is not None

    def test_annotated_tag_resolves_to_its_commit(self, repo):
        """Tests that the peeled entry wins over the tag object's own id."""
        head = repo.git("rev-parse", "HEAD").strip()
        repo.git("tag", "-a", "v1", "-m", "release")
        tag_object = repo.git("rev-parse", "v1").strip()

        refs = ls_remote(repo.url)

        assert refs.commit_for("v1") == head
        assert refs.refs["refs/tags/v1"] == tag_object
        assert tag_object != head

    def test_lightweight_tag_resolves(self, repo):
        """Tests that a lightweight tag points straight at the commit."""
        head = repo.git("rev-parse", "HEAD").strip()
        repo.git("tag", "v2")

        assert ls_remote(repo.url).commit_for("v2") == head

    def test_unknown_ref_is_none(self, repo):
        """Tests that a missing branch or tag reports None, not an error."""
        assert ls_remote(repo.url).commit_for("nope") is None

    def test_parses_odd_server_output(self, monkeypatch):
        """Tests blank lines, a non-branch HEAD, a tab-less line, and a full ref."""
        canned = (
            b"ref: refs/tags/pinned\tHEAD\n"
            b"\n"
            b"garbage without a tab\n"
            b"1111111111111111111111111111111111111111\tHEAD\n"
            b"2222222222222222222222222222222222222222\trefs/heads/dev\n"
            b"3333333333333333333333333333333333333333\trefs/tags/pinned\n"
            b"4444444444444444444444444444444444444444\trefs/tags/pinned^{}\n"
        )
        monkeypatch.setattr(git_module, "run_git", lambda args, cwd=None: canned)

        refs = ls_remote("https://example.invalid/r.git")

        assert isinstance(refs, RemoteRefs)
        assert refs.default_branch is None
        assert refs.commit_for("refs/heads/dev") == "2" * 40
        assert refs.commit_for("pinned") == "4" * 40
        assert "garbage without a tab" not in refs.refs


class TestFetchedRef:
    """Tests for the trees-only fetch, listing, reading, and cleanup."""

    def test_records_the_commit_and_lists_recipes(self, repo):
        """Tests that the fetch pins the tip and ls-tree finds recipe files only."""
        head = repo.git("rev-parse", "HEAD").strip()
        blob = repo.git("rev-parse", "HEAD:recipes/Google/chrome.yaml").strip()

        with FetchedRef(repo.url, "main") as fetched:
            entries = fetched.list_recipe_files(["recipes"])

        assert fetched.commit == head
        assert entries == [TreeEntry(path="recipes/Google/chrome.yaml", blob=blob)]

    def test_non_recipe_files_are_skipped(self, repo):
        """Tests that only .yaml and .yml files under the path are listed."""
        repo.commit({"recipes/Google/notes.txt": b"x", "recipes/a.yml": b"a: 1\n"})

        with FetchedRef(repo.url, "main") as fetched:
            entries = fetched.list_recipe_files(["recipes"])

        assert [entry.path for entry in entries] == [
            "recipes/Google/chrome.yaml",
            "recipes/a.yml",
        ]

    def test_single_file_path_lists_itself(self, repo):
        """Tests that a file path lists that one file."""
        with FetchedRef(repo.url, "main") as fetched:
            entries = fetched.list_recipe_files(["recipes/Google/chrome.yaml"])

        assert [entry.path for entry in entries] == ["recipes/Google/chrome.yaml"]

    def test_reads_exact_bytes(self, repo):
        """Tests that CRLF content comes back untouched by any conversion."""
        repo.commit({"recipes/Google/crlf.yaml": _RECIPE_CRLF}, "CRLF")

        with FetchedRef(repo.url, "main") as fetched:
            data = fetched.read_file("recipes/Google/crlf.yaml")

        assert data == _RECIPE_CRLF

    def test_fetch_leaves_blobs_behind_until_read(self, repo):
        """Tests that the fetch is trees-only and a read pulls one blob."""
        with FetchedRef(repo.url, "main") as fetched:
            before = _blob_count(fetched)
            fetched.read_file("recipes/Google/chrome.yaml")
            after = _blob_count(fetched)

        assert before == 0
        assert after == 1

    def test_annotated_tag_fetch_pins_the_commit(self, repo):
        """Tests that FETCH_HEAD^{commit} dereferences an annotated tag."""
        head = repo.git("rev-parse", "HEAD").strip()
        repo.git("tag", "-a", "v1", "-m", "release")

        with FetchedRef(repo.url, "v1") as fetched:
            assert fetched.commit == head

    def test_commit_comes_from_fetch_head_not_ls_remote(self, repo):
        """Tests that a push between ls-remote and fetch cannot desync the pin."""
        before = ls_remote(repo.url).commit_for("main")
        moved = repo.commit({"recipes/Google/other.yaml": _RECIPE}, "Moved")

        with FetchedRef(repo.url, "main") as fetched:
            assert fetched.commit == moved
            assert fetched.commit != before

    def test_server_without_filter_support_still_works(self, repo):
        """Tests that git's own full-fetch fallback is treated as success."""
        repo.git("config", "uploadpack.allowFilter", "false")

        with FetchedRef(repo.url, "main") as fetched:
            data = fetched.read_file("recipes/Google/chrome.yaml")

        assert data == _RECIPE

    def test_temporary_directory_is_removed(self, repo):
        """Tests that read-only pack files do not survive cleanup on Windows."""
        with FetchedRef(repo.url, "main") as fetched:
            fetched.read_file("recipes/Google/chrome.yaml")
            tempdir = fetched._dir
            assert tempdir.is_dir()

        assert not tempdir.exists()

    def test_failed_fetch_cleans_up_and_reports(self, repo):
        """Tests that a missing ref raises NetworkError and leaves no directory."""
        created: list[Path] = []
        original = tempfile.TemporaryDirectory

        def _tracking(*args, **kwargs):
            tempdir = original(*args, **kwargs)
            created.append(Path(tempdir.name))
            return tempdir

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(git_module.tempfile, "TemporaryDirectory", _tracking)
            with pytest.raises(NetworkError, match="git fetch failed"):
                FetchedRef(repo.url, "no-such-branch")

        assert len(created) == 1
        assert not created[0].exists()

    def test_missing_file_is_a_config_error(self, repo):
        """Tests that a path absent at the commit is a lockfile problem, not network."""
        with (
            FetchedRef(repo.url, "main") as fetched,
            pytest.raises(ConfigError, match="does not exist at commit"),
        ):
            fetched.read_file("recipes/Google/missing.yaml")

    def test_unsafe_upstream_path_is_refused(self, repo):
        """Tests that a file whose path has an unsafe segment aborts the listing."""
        repo.commit_path("recipes/Google/.secret.yaml", _RECIPE)

        with (
            FetchedRef(repo.url, "main") as fetched,
            pytest.raises(ConfigError, match="segment '.secret.yaml'"),
        ):
            fetched.list_recipe_files(["recipes"])

    def test_symlink_entries_are_skipped(self, repo):
        """Tests that a .yaml symlink in the tree is not vendored as a recipe."""
        repo.commit_path("recipes/Google/link.yaml", b"chrome.yaml", mode="120000")

        with FetchedRef(repo.url, "main") as fetched:
            entries = fetched.list_recipe_files(["recipes"])

        assert [entry.path for entry in entries] == ["recipes/Google/chrome.yaml"]

    def test_path_with_spaces_is_listed(self, repo):
        """Tests that a vendor folder with a space is accepted."""
        repo.commit({"recipes/Visual Studio Code/vscode.yaml": _RECIPE}, "Space")

        with FetchedRef(repo.url, "main") as fetched:
            entries = fetched.list_recipe_files(["recipes/Visual Studio Code"])

        assert [entry.path for entry in entries] == [
            "recipes/Visual Studio Code/vscode.yaml"
        ]

    def test_leading_dash_path_never_reaches_git(self, repo):
        """Tests that a lockfile path starting with '-' is refused up front."""
        with (
            FetchedRef(repo.url, "main") as fetched,
            pytest.raises(ConfigError, match="starting with '-'"),
        ):
            fetched.list_recipe_files(["--output=x"])


def _blob_count(fetched: FetchedRef) -> int:
    """Counts blob objects present locally in a fetched repository."""
    output = run_git(
        ["cat-file", "--batch-all-objects", "--batch-check=%(objecttype)"],
        cwd=fetched._dir,
    )
    return output.decode().split().count("blob")


@pytest.mark.integration
def test_fetches_a_recipe_from_this_repository_on_github():
    """Tests the transport against a real server: this repo's chrome recipe."""
    url = "https://github.com/RogerCibrian/notapkgtool.git"
    refs = ls_remote(url)
    assert refs.default_branch == "main"

    with FetchedRef(url, "main") as fetched:
        entries = fetched.list_recipe_files(["recipes/Google/chrome.yaml"])
        data = fetched.read_file("recipes/Google/chrome.yaml")

    assert fetched.commit == refs.commit_for("main")
    assert entries[0].path == "recipes/Google/chrome.yaml"
    assert b'id: "napt-chrome"' in data
