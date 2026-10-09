"""Tests for napt.upstream.add against real repositories under tmp_path."""

from __future__ import annotations

from pathlib import PurePosixPath
import shutil

import pytest
import yaml

from napt.config.loader import load_effective_config
from napt.exceptions import ConfigError
from napt.upstream.add import add_recipes, override_path_for
from napt.upstream.lock import canonical_sha256, read_lockfile
from napt.validation import validate_recipe
from tests.upstream.conftest import CHROME_RECIPE as _CHROME, FIREFOX_RECIPE as _FIREFOX

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


class TestOverridePath:
    """Tests for where an override lands."""

    @pytest.mark.parametrize(
        "imported_from", ["recipes", "recipes/Google", "recipes/Google/chrome.yaml"]
    )
    def test_mirrors_after_the_last_recipes_segment(self, imported_from):
        """Tests that one file lands in one place however it was selected."""
        assert override_path_for(
            "recipes/Google/chrome.yaml", imported_from, None
        ) == PurePosixPath("recipes/Google/chrome.override.yaml")

    def test_last_recipes_segment_wins(self):
        """Tests that a nested recipes/ segment is the one mirrored."""
        assert override_path_for(
            "stuff/recipes/old/recipes/X/a.yaml", "stuff", None
        ) == PurePosixPath("recipes/X/a.override.yaml")

    def test_dest_rehomes_a_mirrored_path(self):
        """Tests that --dest replaces recipes/ as the root."""
        assert override_path_for(
            "recipes/Google/chrome.yaml", "recipes", "apps"
        ) == PurePosixPath("apps/Google/chrome.override.yaml")

    def test_no_recipes_segment_requires_dest(self):
        """Tests that a path with nothing to mirror asks for --dest."""
        with pytest.raises(ConfigError, match="--dest"):
            override_path_for("apps/Google/chrome.yaml", "apps", None)

    def test_no_recipes_segment_with_dest_keeps_relative_layout(self):
        """Tests that a directory import under --dest keeps its sub-folders."""
        assert override_path_for(
            "apps/Google/chrome.yaml", "apps", "recipes/Imported"
        ) == PurePosixPath("recipes/Imported/Google/chrome.override.yaml")
        assert override_path_for(
            "apps/Google/chrome.yaml", "apps/Google/chrome.yaml", "recipes/X"
        ) == PurePosixPath("recipes/X/chrome.override.yaml")

    def test_yml_becomes_override_yaml(self):
        """Tests that the override is always named <app>.override.yaml."""
        assert override_path_for("recipes/a.yml", "recipes", None) == PurePosixPath(
            "recipes/a.override.yaml"
        )


class TestAddRecipes:
    """Tests for importing one file and a directory."""

    def test_imports_one_recipe_end_to_end(self, upstream, project):
        """Tests that add writes the pinned copy, override, and lockfile."""
        result = add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

        assert result.ref == "main"
        assert [r.override for r in result.recipes] == [
            "recipes/Google/chrome.override.yaml"
        ]
        recipe = result.recipes[0]
        assert (project / recipe.pinned).read_bytes() == _CHROME
        override = project / recipe.override
        text = override.read_text()
        assert text.startswith("# Imported by napt upstream from\n")
        data = yaml.safe_load(text)
        assert list(data) == ["apiVersion", "parent", "name", "id"]
        assert data["id"] == "google-chrome"
        assert (override.parent / data["parent"]).resolve() == (
            project / recipe.pinned
        ).resolve()
        lock = read_lockfile(project / "upstream.yaml")
        assert lock.repos[0].url == upstream.url
        entry = lock.repos[0].recipes[0]
        assert entry.commit == result.commit
        assert entry.path == "recipes/Google/chrome.yaml"
        assert entry.override == recipe.override
        assert entry.sha256 == canonical_sha256(_CHROME)
        assert recipe.dropped == ("psadt.release", "intune.build_types", "deployment")

    def test_imported_override_loads_with_org_policy_winning(self, upstream, project):
        """Tests that the written override passes the real loader and the allow list."""
        add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

        config = load_effective_config(
            project / "recipes" / "Google" / "chrome.override.yaml"
        )

        assert config["intune"]["build_types"] == "both"
        assert config["deployment"]["rings"][0]["name"] == "ours"
        assert config["intune"]["description"] == "From upstream"
        assert config["discovery"]["url"] == "https://dl.google.com/chrome.msi"

    def test_directory_import_skips_non_recipes_and_excludes(self, upstream, project):
        """Tests that a directory imports every recipe minus --exclude globs."""
        result = add_recipes(project, upstream.url, ["recipes"], excludes=["Mozilla/*"])

        assert [r.path for r in result.recipes] == ["recipes/Google/chrome.yaml"]

    def test_directory_import_takes_every_recipe(self, upstream, project):
        """Tests that both recipes land, each under its vendor folder."""
        result = add_recipes(project, upstream.url, ["recipes"])

        assert [r.override for r in result.recipes] == [
            "recipes/Google/chrome.override.yaml",
            "recipes/Mozilla/firefox.override.yaml",
        ]
        assert len(read_lockfile(project / "upstream.yaml").repos[0].recipes) == 2

    def test_dry_run_writes_nothing(self, upstream, project):
        """Tests that --dry-run reports the plan and leaves the project untouched."""
        result = add_recipes(project, upstream.url, ["recipes"], dry_run=True)

        assert result.dry_run and len(result.recipes) == 2
        assert result.recipes[0].dropped
        assert not (project / "upstream").exists()
        assert not (project / "upstream.yaml").exists()
        assert list((project / "recipes").iterdir()) == []

    def test_second_add_from_the_same_repo_extends_the_entry(self, upstream, project):
        """Tests that a later add appends to the repository's recipe list."""
        add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])
        add_recipes(project, upstream.url, ["recipes/Mozilla/firefox.yaml"])

        lock = read_lockfile(project / "upstream.yaml")
        assert len(lock.repos) == 1
        assert [r.path for r in lock.repos[0].recipes] == [
            "recipes/Google/chrome.yaml",
            "recipes/Mozilla/firefox.yaml",
        ]

    def test_recipes_from_one_repo_keep_their_own_commits(self, upstream, project):
        """Tests that a later add pins the new recipe without moving the old one."""
        first = add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])
        moved = upstream.commit({"recipes/Mozilla/firefox.yaml": _FIREFOX + b"# v2\n"})

        second = add_recipes(project, upstream.url, ["recipes/Mozilla/firefox.yaml"])

        lock = read_lockfile(project / "upstream.yaml")
        by_path = {r.path: r.commit for r in lock.repos[0].recipes}
        assert by_path["recipes/Google/chrome.yaml"] == first.commit
        assert by_path["recipes/Mozilla/firefox.yaml"] == second.commit == moved
        assert first.commit != moved

    def test_no_default_branch_requires_ref(self, upstream, project, monkeypatch):
        """Tests that a server that reports no HEAD symref asks for --ref."""
        from napt.upstream.git import RemoteRefs

        monkeypatch.setattr(
            "napt.upstream.add.ls_remote",
            lambda _url: RemoteRefs(default_branch=None, refs={}),
        )

        with pytest.raises(ConfigError, match="reports no default branch"):
            add_recipes(project, upstream.url, ["recipes"])

    @pytest.mark.parametrize(
        ("content", "match"),
        [(b"name: [unclosed\n", "not valid YAML"), (b"- a list\n", "not a recipe")],
    )
    def test_unparseable_upstream_file_is_named(
        self, upstream, project, content, match
    ):
        """Tests that a file that is not a recipe mapping aborts with its path."""
        upstream.commit({"recipes/Bad/broken.yaml": content})

        with pytest.raises(ConfigError, match=f"recipes/Bad/broken.yaml in .*{match}"):
            add_recipes(project, upstream.url, ["recipes/Bad/broken.yaml"])

    def test_file_selected_through_two_paths_is_imported_once(self, upstream, project):
        """Tests that overlapping --path values do not plan a recipe twice."""
        result = add_recipes(
            project,
            upstream.url,
            ["recipes", "recipes/Google", "recipes/Google/chrome.yaml"],
        )

        assert [r.path for r in result.recipes] == [
            "recipes/Google/chrome.yaml",
            "recipes/Mozilla/firefox.yaml",
        ]

    def test_upstream_validation_warnings_are_relayed(self, upstream, project, capsys):
        """Tests that a warning from validating the merged config is printed."""
        upstream.commit(
            {
                "recipes/Odd/odd.yaml": (
                    b"apiVersion: napt/v1\nname: Odd\nid: Odd_App\n"
                    b"discovery:\n  strategy: url_download\n  url: https://x/a.msi\n"
                )
            }
        )

        add_recipes(project, upstream.url, ["recipes/Odd/odd.yaml"])

        assert "recommended form" in capsys.readouterr().out

    def test_project_id_scan_tolerates_unreadable_files(self, upstream, project):
        """Tests that a broken recipe in the project does not stop the id scan."""
        (project / "recipes" / "broken.yaml").write_text("name: [unclosed\n")

        result = add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

        assert result.recipes[0].duplicate_of is None

    def test_conflicting_ref_for_a_known_repo_is_refused(self, upstream, project):
        """Tests that one repository is pinned to one ref."""
        upstream.git("branch", "v2")
        add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

        with pytest.raises(ConfigError, match="already imported from ref 'main'"):
            add_recipes(
                project, upstream.url, ["recipes/Mozilla/firefox.yaml"], ref="v2"
            )

    def test_explicit_ref_and_tag(self, upstream, project):
        """Tests that --ref selects a tag and the lockfile records it."""
        upstream.git("tag", "-a", "v1", "-m", "release")
        head = upstream.git("rev-parse", "HEAD").strip()

        result = add_recipes(
            project, upstream.url, ["recipes/Google/chrome.yaml"], ref="v1"
        )

        assert result.ref == "v1" and result.commit == head
        assert read_lockfile(project / "upstream.yaml").repos[0].ref == "v1"

    def test_unknown_ref_is_a_config_error(self, upstream, project):
        """Tests that a missing branch or tag is reported before any fetch."""
        with pytest.raises(ConfigError, match="no branch or tag named 'nope'"):
            add_recipes(project, upstream.url, ["recipes"], ref="nope")

    def test_existing_override_is_never_overwritten(self, upstream, project):
        """Tests that a file already at the override path aborts the import."""
        (project / "recipes" / "Google").mkdir()
        (project / "recipes" / "Google" / "chrome.override.yaml").write_text("x: 1\n")

        with pytest.raises(ConfigError, match="already exists"):
            add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

        assert not (project / "upstream").exists()

    def test_already_imported_recipe_named_directly_points_at_update(
        self, upstream, project
    ):
        """Tests that re-adding a tracked recipe by name says to run update."""
        add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])
        (project / "recipes" / "Google" / "chrome.override.yaml").unlink()

        with pytest.raises(ConfigError, match="already imported"):
            add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

    def test_directory_re_add_skips_tracked_recipes_and_takes_new_ones(
        self, upstream, project
    ):
        """Tests that re-running a directory import picks up only what is new."""
        first = add_recipes(project, upstream.url, ["recipes"])
        lock_before = read_lockfile(project / "upstream.yaml")
        upstream.commit(
            {
                "recipes/Google/chrome.yaml": _CHROME + b"# changed upstream\n",
                "recipes/Zoom/zoom.yaml": _FIREFOX.replace(b"mozilla-firefox", b"zoom"),
            }
        )

        again = add_recipes(project, upstream.url, ["recipes"])

        assert again.skipped == (
            "recipes/Google/chrome.yaml",
            "recipes/Mozilla/firefox.yaml",
        )
        assert [r.path for r in again.recipes] == ["recipes/Zoom/zoom.yaml"]
        lock_after = read_lockfile(project / "upstream.yaml")
        by_path = {r.path: r for r in lock_after.repos[0].recipes}
        # The tracked recipes keep their pins; only Zoom is at the new tip.
        for old in lock_before.repos[0].recipes:
            assert by_path[old.path] == old
        assert by_path["recipes/Zoom/zoom.yaml"].commit == again.commit
        assert again.commit != first.commit
        chrome = project / "upstream"
        assert (
            b"# changed upstream" not in next(chrome.rglob("chrome.yaml")).read_bytes()
        )

    def test_directory_re_add_with_nothing_new_writes_nothing(self, upstream, project):
        """Tests that a re-run with nothing new reports zero and keeps the lockfile."""
        add_recipes(project, upstream.url, ["recipes"])
        before = (project / "upstream.yaml").read_bytes()

        again = add_recipes(project, upstream.url, ["recipes"])

        assert again.recipes == ()
        assert len(again.skipped) == 2
        assert (project / "upstream.yaml").read_bytes() == before

    def test_project_without_recipes_directory_imports_fine(self, upstream, project):
        """Tests that a project with no recipes/ yet gets one from the import."""
        (project / "recipes").rmdir()

        result = add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

        assert result.recipes[0].duplicate_of is None
        assert (project / "recipes" / "Google" / "chrome.override.yaml").is_file()

    def test_empty_path_list_is_an_error(self, upstream, project):
        """Tests that the engine refuses an import with no paths."""
        with pytest.raises(ConfigError, match="At least one --path"):
            add_recipes(project, upstream.url, [])

    def test_invalid_upstream_recipe_aborts_before_any_write(self, upstream, project):
        """Tests that one bad recipe in a directory import writes nothing."""
        upstream.commit(
            {"recipes/Bad/bad.yaml": b"apiVersion: napt/v1\nname: Bad\nid: bad\n"}
        )

        with pytest.raises(ConfigError, match="would not validate"):
            add_recipes(project, upstream.url, ["recipes"])

        assert not (project / "upstream").exists()
        assert list((project / "recipes").iterdir()) == []

    def test_secret_the_org_does_not_declare_fails_the_import(self, upstream, project):
        """Tests that validation runs on the merged, org-aware configuration."""
        upstream.commit(
            {
                "recipes/Vendor/api.yaml": (
                    b"apiVersion: napt/v1\nname: Api\nid: vendor-api\n"
                    b"discovery:\n  strategy: api_json\n"
                    b"  api_url: https://api.vendor.com/latest\n"
                    b"  version_path: version\n  download_url_path: url\n"
                    b"  headers:\n    Authorization: Bearer ${VENDOR_TOKEN}\n"
                )
            }
        )

        with pytest.raises(ConfigError, match="does not declare under secrets"):
            add_recipes(project, upstream.url, ["recipes/Vendor/api.yaml"])

    def test_upstream_file_declaring_parent_is_refused(self, upstream, project):
        """Tests that a publisher's own override cannot be imported as a parent."""
        upstream.commit(
            {
                "recipes/Mozilla/nightly.override.yaml": (
                    b"apiVersion: napt/v1\nparent: ../../recipe-bases/base.yaml\n"
                    b"name: Nightly\nid: mozilla-nightly\n"
                )
            }
        )

        with pytest.raises(ConfigError, match="declares a parent of its own") as err:
            add_recipes(project, upstream.url, ["recipes"])

        assert "--exclude 'nightly.override.yaml'" in str(err.value)

    def test_id_override_applies_to_single_file_only(self, upstream, project):
        """Tests that --id replaces the upstream id and refuses bulk imports."""
        with pytest.raises(ConfigError, match="single-file import"):
            add_recipes(project, upstream.url, ["recipes"], app_id="x")

        result = add_recipes(
            project, upstream.url, ["recipes/Google/chrome.yaml"], app_id="chrome-ent"
        )

        assert result.recipes[0].app_id == "chrome-ent"
        text = (project / "recipes" / "Google" / "chrome.override.yaml").read_text()
        assert "id: chrome-ent" in text

    def test_duplicate_id_is_reported(self, upstream, project, capsys):
        """Tests that an id already used in the project is named."""
        (project / "recipes" / "mine.yaml").write_text(
            "apiVersion: napt/v1\nname: Mine\nid: google-chrome\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n"
        )

        result = add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

        assert result.recipes[0].duplicate_of == "recipes/mine.yaml"
        assert "already used by recipes/mine.yaml" in capsys.readouterr().out

    def test_dest_without_recipes_segment(self, upstream, project):
        """Tests that a repository without a recipes/ folder imports under --dest."""
        upstream.commit({"apps/tool.yaml": _FIREFOX})

        with pytest.raises(ConfigError, match="--dest"):
            add_recipes(project, upstream.url, ["apps/tool.yaml"])
        result = add_recipes(
            project, upstream.url, ["apps/tool.yaml"], dest="recipes/Tools"
        )

        assert result.recipes[0].override == "recipes/Tools/tool.override.yaml"
        assert validate_recipe(project / result.recipes[0].override).is_valid

    def test_unsafe_dest_is_refused(self, upstream, project):
        """Tests that --dest cannot escape the project."""
        with pytest.raises(ConfigError, match="segment '..'"):
            add_recipes(
                project, upstream.url, ["recipes/Google/chrome.yaml"], dest="../out"
            )

    def test_empty_selection_is_an_error(self, upstream, project):
        """Tests that a path with no recipes beneath it is reported."""
        with pytest.raises(ConfigError, match="No recipe files"):
            add_recipes(project, upstream.url, ["recipe-bases/none"])

    def test_dropped_keys_are_warned_once_per_recipe(self, upstream, project, capsys):
        """Tests that add names the keys the loader will ignore."""
        add_recipes(project, upstream.url, ["recipes/Google/chrome.yaml"])

        out = capsys.readouterr().out
        assert (
            "[UPSTREAM] WARNING: recipes/Google/chrome.yaml: ignoring keys not "
            "allowed from upstream recipes: psadt.release, intune.build_types, "
            "deployment"
        ) in out
