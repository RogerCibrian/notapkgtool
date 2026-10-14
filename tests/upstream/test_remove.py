"""Tests for napt.upstream.remove."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from napt.exceptions import ConfigError
from napt.upstream.add import add_recipes
from napt.upstream.lock import read_lockfile
from napt.upstream.remove import remove_recipe

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


@pytest.fixture
def imported(upstream, project) -> Path:
    """A project with both upstream recipes imported; returns the project."""
    add_recipes(project, upstream.url, ["recipes"])
    return project


def _pinned(project: Path, name: str) -> Path:
    return next((project / "upstream").rglob(name))


class TestRemoveRecipe:
    """Tests for removing by override, by pinned copy, and the last recipe."""

    def test_remove_by_override_keeps_the_override(self, imported, capsys):
        """Tests that the pinned copy and entry go, and the override is warned."""
        override = imported / "recipes" / "Google" / "chrome.override.yaml"

        result = remove_recipe(imported, override)

        assert not _exists(imported, "chrome.yaml")
        assert override.is_file()
        assert result.override == "recipes/Google/chrome.override.yaml"
        assert result.override_deleted is False
        assert result.repo_removed is False
        lock = read_lockfile(imported / "upstream.yaml")
        assert [r.path for r in lock.repos[0].recipes] == [
            "recipes/Mozilla/firefox.yaml"
        ]
        assert "still names the removed file as parent" in capsys.readouterr().out

    def test_remove_by_pinned_copy_and_delete_override(self, imported):
        """Tests that the pinned copy resolves the entry and the override can go."""
        pinned = _pinned(imported, "firefox.yaml")

        result = remove_recipe(imported, pinned, delete_override=True)

        assert result.override_deleted is True
        assert not (imported / "recipes" / "Mozilla" / "firefox.override.yaml").exists()
        assert not pinned.exists()
        assert not pinned.parent.exists()  # Mozilla/ emptied and pruned

    def test_removing_one_repository_leaves_the_other(self, imported, tmp_path):
        """Tests that a second repository's entry and directory survive."""
        from tests.upstream.conftest import FIREFOX_RECIPE, Repo

        other_dir = tmp_path / "other"
        other_dir.mkdir()
        other = Repo(other_dir, tmp_path / "empty-gitconfig")
        other.commit(
            {
                "recipes/Tools/tool.yaml": FIREFOX_RECIPE.replace(
                    b"mozilla-firefox", b"tool"
                )
            }
        )
        add_recipes(imported, other.url, ["recipes/Tools/tool.yaml"])

        result = remove_recipe(imported, _pinned(imported, "tool.yaml"))

        assert result.repo_removed is True
        lock = read_lockfile(imported / "upstream.yaml")
        assert [r.url for r in lock.repos] == [lock.repos[0].url]
        assert len(lock.repos[0].recipes) == 2
        assert (imported / "upstream").is_dir()

    def test_unreadable_override_is_a_config_error(self, imported):
        """Tests that an override that is not YAML is reported, not raised raw."""
        override = imported / "recipes" / "Google" / "chrome.override.yaml"
        override.write_text("parent: [unclosed\n")

        with pytest.raises(ConfigError, match="Cannot read"):
            remove_recipe(imported, override)

    def test_delete_failures_are_config_errors(self, imported, monkeypatch):
        """Tests that an OSError deleting a file is reported with the path."""
        pinned = _pinned(imported, "chrome.yaml")

        def _refuse(self, missing_ok=False):
            raise PermissionError("locked")

        monkeypatch.setattr(Path, "unlink", _refuse)

        with pytest.raises(ConfigError, match="Cannot delete .*locked"):
            remove_recipe(imported, pinned)

    def test_override_delete_failure_is_a_config_error(self, imported, monkeypatch):
        """Tests that an OSError deleting the override is reported with its path."""
        override = imported / "recipes" / "Google" / "chrome.override.yaml"
        real_unlink = Path.unlink

        def _refuse_override(self, missing_ok=False):
            if self.name.endswith(".override.yaml"):
                raise PermissionError("busy")
            real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", _refuse_override)

        with pytest.raises(ConfigError, match="Cannot delete .*override.yaml: busy"):
            remove_recipe(imported, override, delete_override=True)

    def test_last_recipe_removes_the_repository_entry_and_directory(self, imported):
        """Tests that nothing of the repository remains after its last recipe."""
        remove_recipe(imported, _pinned(imported, "chrome.yaml"))

        result = remove_recipe(imported, _pinned(imported, "firefox.yaml"))

        assert result.repo_removed is True
        assert not (imported / "upstream.yaml").exists()
        assert not (imported / "upstream").exists()

    def test_untracked_file_under_upstream_is_refused(self, imported):
        """Tests that a hand-copied file is not removed through the lockfile."""
        stray = _pinned(imported, "chrome.yaml").with_name("stray.yaml")
        stray.write_text("a: 1\n")

        with pytest.raises(ConfigError, match="is not tracked in"):
            remove_recipe(imported, stray)

        assert stray.exists()

    def test_override_without_parent_is_refused(self, imported):
        """Tests that a plain recipe is not an imported recipe's override."""
        plain = imported / "recipes" / "plain.yaml"
        plain.write_text("apiVersion: napt/v1\nname: P\nid: p\n")

        with pytest.raises(ConfigError, match="declares no parent"):
            remove_recipe(imported, plain)

    def test_override_pointing_outside_upstream_is_refused(self, imported):
        """Tests that a local parent cannot be removed through this command."""
        base = imported / "recipe-bases" / "base.yaml"
        base.parent.mkdir()
        base.write_text("apiVersion: napt/v1\n")
        child = imported / "recipes" / "child.override.yaml"
        child.write_text("apiVersion: napt/v1\nparent: ../recipe-bases/base.yaml\n")

        with pytest.raises(ConfigError, match="not under a tracked"):
            remove_recipe(imported, child)

    def test_pinned_copy_in_another_project_is_refused(self, imported, tmp_path):
        """Tests that an override pointing into another checkout is refused."""
        other = tmp_path / "other-project"
        other_pinned = (
            other / "upstream" / "github.com" / "o" / "r" / "recipes" / "x.yaml"
        )
        other_pinned.parent.mkdir(parents=True)
        other_pinned.write_text("apiVersion: napt/v1\n")
        (other / "upstream.yaml").write_text("apiVersion: napt/v1\nrepos: []\n")
        override = imported / "recipes" / "stray.override.yaml"
        rel = Path(os.path.relpath(other_pinned, override.parent)).as_posix()
        override.write_text(f"apiVersion: napt/v1\nparent: {rel}\nname: S\nid: s\n")

        with pytest.raises(ConfigError, match="not this project's"):
            remove_recipe(imported, override)

        assert other_pinned.exists()

    @pytest.mark.parametrize(
        "recorded", ["../../outside.yaml", "upstream/x.yaml", "recipes/a:b.yaml"]
    )
    def test_tampered_override_field_is_refused(self, imported, recorded):
        """Tests that a lockfile override path outside recipes/ is never deleted."""
        lockfile = imported / "upstream.yaml"
        lockfile.write_text(
            lockfile.read_text().replace(
                "override: recipes/Google/chrome.override.yaml",
                f"override: {recorded}",
            )
        )
        outside = imported.parent / "outside.yaml"
        outside.write_text("victim\n")

        with pytest.raises(ConfigError, match="fix the entry by hand|segment"):
            remove_recipe(
                imported, _pinned(imported, "chrome.yaml"), delete_override=True
            )

        assert outside.exists()

    def test_recorded_override_must_name_the_pinned_copy(self, imported):
        """Tests that a recorded override pointing elsewhere is not deleted."""
        lockfile = imported / "upstream.yaml"
        lockfile.write_text(
            lockfile.read_text().replace(
                "override: recipes/Google/chrome.override.yaml",
                "override: recipes/Mozilla/firefox.override.yaml",
            )
        )

        with pytest.raises(ConfigError, match="does not name .* as its parent"):
            remove_recipe(
                imported, _pinned(imported, "chrome.yaml"), delete_override=True
            )

        assert (imported / "recipes" / "Mozilla" / "firefox.override.yaml").exists()

    def test_missing_override_is_reported_as_none(self, imported):
        """Tests that a removed-by-hand override does not break removal."""
        (imported / "recipes" / "Google" / "chrome.override.yaml").unlink()

        result = remove_recipe(imported, _pinned(imported, "chrome.yaml"))

        assert result.override is None


def _exists(project: Path, name: str) -> bool:
    return (
        any((project / "upstream").rglob(name))
        if (project / "upstream").exists()
        else False
    )
