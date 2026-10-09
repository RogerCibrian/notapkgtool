"""Tests for napt.upstream.refresh: the check and update scan."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from napt.exceptions import ConfigError
from napt.upstream.add import add_recipes
from napt.upstream.lock import canonical_sha256, read_lockfile
from napt.upstream.refresh import (
    CHANGED,
    MISSING,
    MODIFIED_LOCALLY,
    UNCHANGED,
    refresh,
)
from tests.upstream.conftest import CHROME_RECIPE, FIREFOX_RECIPE

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


def _statuses(result) -> dict[str, str]:
    return {r.path: r.status for r in result.recipes}


def _entries(project: Path) -> dict[str, object]:
    lock = read_lockfile(project / "upstream.yaml")
    return {r.path: r for r in lock.repos[0].recipes}


class TestCheck:
    """Tests for the read-only scan."""

    def test_everything_unchanged_skips_the_fetch(self, imported, upstream, capsys):
        """Tests that a tip equal to every pin needs no fetch and reports unchanged."""
        result = refresh(imported, write=False)

        assert _statuses(result) == {
            "recipes/Google/chrome.yaml": UNCHANGED,
            "recipes/Mozilla/firefox.yaml": UNCHANGED,
        }
        assert all(r.new_commit is None for r in result.recipes)
        assert result.drifted == ()
        assert "Fetching" not in capsys.readouterr().out

    def test_changed_and_missing_are_reported_without_writing(self, imported, upstream):
        """Tests that upstream edits and deletions show up and nothing changes."""
        upstream.commit({"recipes/Google/chrome.yaml": CHROME_RECIPE + b"# v2\n"})
        upstream.git("rm", "-q", "recipes/Mozilla/firefox.yaml")
        upstream.git("commit", "-q", "-m", "Drop firefox")
        before = (imported / "upstream.yaml").read_bytes()

        result = refresh(imported, write=False)

        statuses = _statuses(result)
        assert statuses["recipes/Google/chrome.yaml"] == CHANGED
        assert statuses["recipes/Mozilla/firefox.yaml"] == MISSING
        chrome = next(r for r in result.recipes if r.path.endswith("chrome.yaml"))
        assert chrome.new_commit != chrome.old_commit
        assert chrome.new_blob != chrome.old_blob
        assert [r.path for r in result.drifted] == [
            "recipes/Google/chrome.yaml",
            "recipes/Mozilla/firefox.yaml",
        ]
        assert (imported / "upstream.yaml").read_bytes() == before
        assert _pinned(imported, "chrome.yaml").read_bytes() == CHROME_RECIPE

    def test_tip_moved_but_recipe_untouched_is_unchanged(self, imported, upstream):
        """Tests that a commit elsewhere in the repository is not drift."""
        upstream.commit({"README.md": b"# changed\n"})

        result = refresh(imported, write=False)

        assert set(_statuses(result).values()) == {UNCHANGED}
        assert all(r.new_commit is not None for r in result.recipes)

    def test_locally_edited_pinned_copy_is_reported(self, imported):
        """Tests that a hand-edited pinned copy is modified-locally, fetch or not."""
        pinned = _pinned(imported, "chrome.yaml")
        pinned.write_bytes(CHROME_RECIPE + b"# local edit\n")

        result = refresh(imported, write=False)

        assert _statuses(result)["recipes/Google/chrome.yaml"] == MODIFIED_LOCALLY
        assert result.drifted == ()

    def test_deleted_pinned_copy_is_modified_locally(self, imported):
        """Tests that a pinned copy removed by hand counts as local drift."""
        _pinned(imported, "chrome.yaml").unlink()

        result = refresh(imported, write=False)

        assert _statuses(result)["recipes/Google/chrome.yaml"] == MODIFIED_LOCALLY

    def test_paths_limit_the_scan(self, imported, upstream):
        """Tests that an override or pinned copy selects one recipe."""
        override = imported / "recipes" / "Google" / "chrome.override.yaml"

        by_override = refresh(imported, write=False, paths=[override])
        by_pinned = refresh(
            imported, write=False, paths=[_pinned(imported, "firefox.yaml")]
        )

        assert [r.path for r in by_override.recipes] == ["recipes/Google/chrome.yaml"]
        assert [r.path for r in by_pinned.recipes] == ["recipes/Mozilla/firefox.yaml"]

    def test_path_in_one_repository_leaves_the_other_alone(
        self, imported, tmp_path, capsys
    ):
        """Tests that a second repository is not even contacted for one path."""
        from tests.upstream.conftest import Repo

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
        capsys.readouterr()

        result = refresh(
            imported,
            write=False,
            paths=[imported / "recipes" / "Google" / "chrome.override.yaml"],
        )

        assert [r.path for r in result.recipes] == ["recipes/Google/chrome.yaml"]
        assert other.url not in capsys.readouterr().out

    def test_unknown_path_is_a_config_error(self, imported):
        """Tests that a path outside the project's pinned copies is refused."""
        stray = imported / "recipes" / "plain.yaml"
        stray.write_text("apiVersion: napt/v1\nname: P\nid: p\n")

        with pytest.raises(ConfigError, match="declares no parent"):
            refresh(imported, write=False, paths=[stray])

    def test_path_outside_this_project_is_a_config_error(self, imported, tmp_path):
        """Tests that a pinned copy in another checkout is not scanned from here."""
        other = tmp_path / "other"
        pinned = other / "upstream" / "github.com" / "o" / "r" / "recipes" / "x.yaml"
        pinned.parent.mkdir(parents=True)
        pinned.write_text("a: 1\n")
        (other / "upstream.yaml").write_text("apiVersion: napt/v1\nrepos: []\n")

        with pytest.raises(ConfigError, match="not a pinned copy in this project"):
            refresh(imported, write=False, paths=[pinned])

    def test_untracked_pinned_copy_is_a_config_error(self, imported):
        """Tests that a file under upstream/ with no lockfile entry is refused."""
        stray = _pinned(imported, "chrome.yaml").with_name("stray.yaml")
        stray.write_text("a: 1\n")

        with pytest.raises(ConfigError, match="is not tracked in upstream.yaml"):
            refresh(imported, write=False, paths=[stray])

    def test_missing_lockfile_is_a_config_error(self, project):
        """Tests that a project with nothing imported says so."""
        with pytest.raises(ConfigError, match="nothing has been imported"):
            refresh(project, write=False)

    def test_vanished_ref_is_a_config_error(self, imported, upstream):
        """Tests that a branch deleted upstream is reported, not a crash."""
        upstream.git("branch", "-m", "main", "renamed")

        with pytest.raises(ConfigError, match="no longer has a branch or tag"):
            refresh(imported, write=False)


class TestUpdate:
    """Tests for rewriting pinned copies."""

    def test_rewrites_changed_recipe_only(self, imported, upstream):
        """Tests that a changed recipe is rewritten and repinned, the other kept."""
        before = _entries(imported)
        moved = upstream.commit(
            {"recipes/Google/chrome.yaml": CHROME_RECIPE + b"# v2\n"}
        )

        result = refresh(imported, write=True)

        chrome = next(r for r in result.recipes if r.path.endswith("chrome.yaml"))
        assert chrome.status == CHANGED and chrome.updated is True
        assert (
            _pinned(imported, "chrome.yaml").read_bytes() == CHROME_RECIPE + b"# v2\n"
        )
        after = _entries(imported)
        assert after["recipes/Google/chrome.yaml"].commit == moved
        assert after["recipes/Google/chrome.yaml"].sha256 == canonical_sha256(
            CHROME_RECIPE + b"# v2\n"
        )
        assert (
            after["recipes/Mozilla/firefox.yaml"]
            == before["recipes/Mozilla/firefox.yaml"]
        )
        assert result.refused == ()

    def test_update_one_recipe_by_path_leaves_the_other_stale(self, imported, upstream):
        """Tests that a path argument refreshes that recipe alone."""
        upstream.commit(
            {
                "recipes/Google/chrome.yaml": CHROME_RECIPE + b"# v2\n",
                "recipes/Mozilla/firefox.yaml": FIREFOX_RECIPE + b"# v2\n",
            }
        )
        before = _entries(imported)

        refresh(
            imported,
            write=True,
            paths=[imported / "recipes" / "Google" / "chrome.override.yaml"],
        )

        after = _entries(imported)
        assert (
            after["recipes/Google/chrome.yaml"].commit
            != before["recipes/Google/chrome.yaml"].commit
        )
        assert (
            after["recipes/Mozilla/firefox.yaml"]
            == before["recipes/Mozilla/firefox.yaml"]
        )
        assert _pinned(imported, "firefox.yaml").read_bytes() == FIREFOX_RECIPE

    def test_override_is_never_touched(self, imported, upstream):
        """Tests that update rewrites pinned copies, not overrides."""
        override = imported / "recipes" / "Google" / "chrome.override.yaml"
        override.write_text(override.read_text() + "intune:\n  description: Mine\n")
        text = override.read_text()
        upstream.commit({"recipes/Google/chrome.yaml": CHROME_RECIPE + b"# v2\n"})

        refresh(imported, write=True)

        assert override.read_text() == text

    def test_missing_recipe_keeps_its_entry(self, imported, upstream):
        """Tests that a recipe deleted upstream keeps its file and pin."""
        upstream.git("rm", "-q", "recipes/Mozilla/firefox.yaml")
        upstream.git("commit", "-q", "-m", "Drop firefox")
        before = _entries(imported)

        result = refresh(imported, write=True)

        assert _statuses(result)["recipes/Mozilla/firefox.yaml"] == MISSING
        assert (
            _entries(imported)["recipes/Mozilla/firefox.yaml"]
            == before["recipes/Mozilla/firefox.yaml"]
        )
        assert _pinned(imported, "firefox.yaml").exists()

    def test_locally_modified_is_refused_unless_forced(self, imported, upstream):
        """Tests that a hand-edited pinned copy is left alone, then overwritten."""
        pinned = _pinned(imported, "chrome.yaml")
        pinned.write_bytes(CHROME_RECIPE + b"# local edit\n")
        upstream.commit({"recipes/Google/chrome.yaml": CHROME_RECIPE + b"# v2\n"})

        refused = refresh(imported, write=True)

        assert [r.path for r in refused.refused] == ["recipes/Google/chrome.yaml"]
        assert pinned.read_bytes() == CHROME_RECIPE + b"# local edit\n"

        forced = refresh(imported, write=True, force=True)

        chrome = next(r for r in forced.recipes if r.path.endswith("chrome.yaml"))
        assert chrome.status == MODIFIED_LOCALLY and chrome.updated is True
        assert pinned.read_bytes() == CHROME_RECIPE + b"# v2\n"
        assert forced.refused == ()

    def test_force_restores_a_locally_edited_copy_with_no_upstream_change(
        self, imported
    ):
        """Tests that --force fetches even when the tip has not moved."""
        pinned = _pinned(imported, "chrome.yaml")
        pinned.write_bytes(b"garbage\n")

        result = refresh(imported, write=True, force=True)

        chrome = next(r for r in result.recipes if r.path.endswith("chrome.yaml"))
        assert chrome.updated is True
        assert pinned.read_bytes() == CHROME_RECIPE

    def test_update_warns_about_newly_dropped_keys(self, imported, upstream, capsys):
        """Tests that a tenant key arriving in an update is named once."""
        upstream.commit(
            {
                "recipes/Mozilla/firefox.yaml": FIREFOX_RECIPE
                + b"deployment:\n  rings: []\n"
            }
        )

        result = refresh(imported, write=True)

        firefox = next(r for r in result.recipes if r.path.endswith("firefox.yaml"))
        assert firefox.dropped == ("deployment",)
        assert (
            "[UPSTREAM] WARNING: recipes/Mozilla/firefox.yaml: ignoring keys not "
            "allowed from upstream recipes: deployment"
        ) in capsys.readouterr().out

    @pytest.mark.parametrize(
        "content", [b"- a list\n", b"name: [unclosed\n", b"\xff\xfe"]
    )
    def test_unparseable_upstream_content_is_still_written(
        self, imported, upstream, content
    ):
        """Tests that update does not judge content; the loader reports it later."""
        upstream.commit({"recipes/Google/chrome.yaml": content})

        result = refresh(imported, write=True)

        chrome = next(r for r in result.recipes if r.path.endswith("chrome.yaml"))
        assert chrome.updated is True and chrome.dropped == ()
        assert _pinned(imported, "chrome.yaml").read_bytes() == content

    def test_nothing_to_do_leaves_the_lockfile_untouched(self, imported):
        """Tests that an update with no changes does not rewrite upstream.yaml."""
        before = (imported / "upstream.yaml").read_bytes()

        result = refresh(imported, write=True)

        assert not any(r.updated for r in result.recipes)
        assert (imported / "upstream.yaml").read_bytes() == before

    def test_updated_copy_passes_the_loader(self, imported, upstream):
        """Tests that the rewritten pinned copy and lockfile agree for the loader."""
        from napt.config.loader import load_effective_config

        upstream.commit(
            {
                "recipes/Google/chrome.yaml": CHROME_RECIPE.replace(
                    b"From upstream", b"v2"
                )
            }
        )
        refresh(imported, write=True)

        config = load_effective_config(
            imported / "recipes" / "Google" / "chrome.override.yaml"
        )

        assert config["intune"]["description"] == "v2"


def test_quiet_prints_nothing_but_still_rewrites(imported, upstream, capsys):
    """Tests that quiet mode suppresses progress and warnings, not the work."""
    upstream.commit(
        {"recipes/Mozilla/firefox.yaml": FIREFOX_RECIPE + b"deployment:\n  rings: []\n"}
    )

    result = refresh(imported, write=True, quiet=True)

    firefox = next(r for r in result.recipes if r.path.endswith("firefox.yaml"))
    assert firefox.updated and firefox.dropped == ("deployment",)
    assert capsys.readouterr().out == ""
