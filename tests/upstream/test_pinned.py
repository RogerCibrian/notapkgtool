"""Tests for napt.upstream.pinned: pinned parents, the hash check, the filter."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess
import sys

import pytest

from napt.exceptions import ConfigError
from napt.upstream.lock import canonical_sha256
from napt.upstream.pinned import (
    ALLOWED_PARENT_KEYS,
    PinnedLocation,
    filter_pinned_parent,
    is_pinned_copy,
    pinned_location,
    tracked_location,
    verify_pinned_copy,
)

_PINNED_COPY = "github.com/someorg/napt-recipes/recipes/Google/chrome.yaml"


def link_directory(link: Path, target: Path) -> None:
    """Makes ``link`` resolve to ``target`` by symlink, or by junction on Windows.

    A symlink needs elevation on a default Windows account; a junction does
    not and is resolved the same way, so the resolved-path check still gets
    exercised. Skips the test when neither can be created.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        pass
    if sys.platform != "win32":
        pytest.skip("cannot create a symlink here")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"cannot create a junction here: {result.stderr.strip()}")


def _lockfile_text(sha256: str) -> str:
    return (
        "apiVersion: napt/v1\n"
        "repos:\n"
        "  - url: https://github.com/someorg/napt-recipes.git\n"
        "    ref: main\n"
        "    recipes:\n"
        "      - path: recipes/Google/chrome.yaml\n"
        "        override: recipes/Google/chrome.override.yaml\n"
        "        commit: 4f2a9c1e\n"
        "        blob: 9c1d2e3f\n"
        f"        sha256: {sha256}\n"
    )


class TestPinnedLocation:
    """Tests for deciding whether a parent reference points at a pinned copy."""

    def test_reference_through_upstream_is_a_pinned_copy(self, tmp_path):
        """Tests that the usual override points at the upstream directory."""
        recipe_dir = tmp_path / "recipes" / "Google"

        location = pinned_location(recipe_dir, f"../../upstream/{_PINNED_COPY}")

        assert location == PinnedLocation(
            upstream_dir=tmp_path / "upstream", relative=PurePosixPath(_PINNED_COPY)
        )
        assert location.lockfile == tmp_path / "upstream.yaml"

    def test_local_base_is_not_a_pinned_copy(self, tmp_path):
        """Tests that a parent in recipe-bases/ gets no check."""
        recipe_dir = tmp_path / "recipes" / "Google"

        assert pinned_location(recipe_dir, "../../recipe-bases/base.yaml") is None

    def test_directory_name_matches_any_case(self, tmp_path):
        """Tests that Upstream/ is the same reserved directory as upstream/."""
        recipe_dir = tmp_path / "recipes" / "Google"

        location = pinned_location(recipe_dir, f"../../Upstream/{_PINNED_COPY}")

        assert location is not None
        assert location.upstream_dir == tmp_path / "Upstream"

    def test_absolute_reference_is_made_relative_first(self, tmp_path):
        """Tests that an absolute parent path inside upstream/ is a pinned copy."""
        recipe_dir = tmp_path / "recipes" / "Google"
        absolute = str(tmp_path / "upstream" / Path(_PINNED_COPY))

        location = pinned_location(recipe_dir, absolute)

        assert location is not None
        assert location.relative == PurePosixPath(_PINNED_COPY)

    def test_project_under_a_folder_named_upstream_is_unaffected(self, tmp_path):
        """Tests that only segments between override and parent are examined."""
        project = tmp_path / "upstream" / "myproject"
        recipe_dir = project / "recipes" / "Google"

        assert pinned_location(recipe_dir, "../../recipe-bases/base.yaml") is None

    def test_parent_file_itself_named_upstream_is_not_a_directory(self, tmp_path):
        """Tests that a file called upstream.yaml beside the override is local."""
        recipe_dir = tmp_path / "recipes" / "Google"

        assert pinned_location(recipe_dir, "upstream.yaml") is None

    def test_a_path_on_another_drive_is_local(self, tmp_path, monkeypatch):
        """Tests that a reference relpath cannot express is treated as local."""
        import napt.upstream.pinned as module

        def _cannot_relate(*_args):
            raise ValueError("different drives")

        monkeypatch.setattr(module.os.path, "relpath", _cannot_relate)

        assert pinned_location(tmp_path, "../../upstream/x/y.yaml") is None


class TestIsPinnedCopy:
    """Tests for recognizing a pinned copy by where it sits."""

    def test_file_under_tracked_upstream_is_a_pinned_copy(self, tmp_path):
        """Tests that a file under a tracked upstream/ is a pinned copy."""
        pinned = tmp_path / "upstream" / Path(_PINNED_COPY)
        pinned.parent.mkdir(parents=True)
        pinned.write_text("apiVersion: napt/v1\n")
        (tmp_path / "upstream.yaml").write_text(_lockfile_text("x"))

        assert is_pinned_copy(pinned) is True

    def test_upstream_folder_without_lockfile_is_not_pinned(self, tmp_path):
        """Tests that a project living under a folder named upstream is unaffected."""
        recipe = tmp_path / "upstream" / "myproject" / "recipes" / "app.yaml"
        recipe.parent.mkdir(parents=True)
        recipe.write_text("apiVersion: napt/v1\n")

        assert is_pinned_copy(recipe) is False

    def test_override_is_not_pinned(self, tmp_path):
        """Tests that the override beside a tracked upstream/ runs normally."""
        (tmp_path / "upstream").mkdir()
        (tmp_path / "upstream.yaml").write_text(_lockfile_text("x"))
        override = tmp_path / "recipes" / "Google" / "chrome.override.yaml"
        override.parent.mkdir(parents=True)
        override.write_text("apiVersion: napt/v1\n")

        assert is_pinned_copy(override) is False


class TestTrackedLocation:
    """Tests for classifying a file by where it really is."""

    def test_file_under_tracked_upstream_reports_its_location(self, tmp_path):
        """Tests that the lockfile and the relative key come from the real path."""
        pinned = tmp_path / "upstream" / Path(_PINNED_COPY)
        pinned.parent.mkdir(parents=True)
        pinned.write_text("a: 1\n")
        (tmp_path / "upstream.yaml").write_text(_lockfile_text("x"))

        location = tracked_location(pinned)

        assert location is not None
        assert location.upstream_dir == tmp_path.resolve() / "upstream"
        assert location.relative == PurePosixPath(_PINNED_COPY)

    def test_link_into_upstream_is_seen_through(self, tmp_path):
        """Tests that a link from recipe-bases/ still resolves to the pinned copy."""
        pinned = tmp_path / "upstream" / Path(_PINNED_COPY)
        pinned.parent.mkdir(parents=True)
        pinned.write_text("a: 1\n")
        (tmp_path / "upstream.yaml").write_text(_lockfile_text("x"))
        link_directory(tmp_path / "recipe-bases", pinned.parent)

        location = tracked_location(tmp_path / "recipe-bases" / "chrome.yaml")

        assert location is not None
        assert location.relative == PurePosixPath(_PINNED_COPY)

    def test_local_base_has_no_tracked_location(self, tmp_path):
        """Tests that a real file in recipe-bases/ is local."""
        base = tmp_path / "recipe-bases" / "base.yaml"
        base.parent.mkdir()
        base.write_text("a: 1\n")

        assert tracked_location(base) is None


class TestVerifyPinnedCopy:
    """Tests for the hash check against upstream.yaml."""

    @staticmethod
    def _project(tmp_path, data: bytes, lockfile_text: str | None) -> tuple:
        pinned = tmp_path / "upstream" / Path(_PINNED_COPY)
        pinned.parent.mkdir(parents=True)
        pinned.write_bytes(data)
        if lockfile_text is not None:
            (tmp_path / "upstream.yaml").write_text(lockfile_text)
        location = PinnedLocation(
            upstream_dir=tmp_path / "upstream", relative=PurePosixPath(_PINNED_COPY)
        )
        return pinned, location

    def test_matching_hash_passes(self, tmp_path):
        """Tests that a pinned copy equal to its record is accepted."""
        data = b"apiVersion: napt/v1\nname: Chrome\n"
        pinned, location = self._project(
            tmp_path, data, _lockfile_text(canonical_sha256(data))
        )

        verify_pinned_copy(pinned, location, data)

    def test_crlf_checkout_still_matches(self, tmp_path):
        """Tests that autocrlf on Windows does not produce false drift."""
        data = b"apiVersion: napt/v1\nname: Chrome\n"
        on_disk = data.replace(b"\n", b"\r\n")
        pinned, location = self._project(
            tmp_path, on_disk, _lockfile_text(canonical_sha256(data))
        )

        verify_pinned_copy(pinned, location, on_disk)

    def test_missing_lockfile_names_both_fixes(self, tmp_path):
        """Tests that upstream/ without upstream.yaml beside it is an error."""
        pinned, location = self._project(tmp_path, b"a: 1\n", None)

        with pytest.raises(ConfigError, match="no .*upstream.yaml tracking it"):
            verify_pinned_copy(pinned, location, b"a: 1\n")

    def test_untracked_file_is_an_error(self, tmp_path):
        """Tests that a file under upstream/ with no lockfile entry is refused."""
        pinned, location = self._project(tmp_path, b"a: 1\n", _lockfile_text("x"))
        other = PinnedLocation(
            upstream_dir=location.upstream_dir,
            relative=PurePosixPath("github.com/someorg/napt-recipes/recipes/x.yaml"),
        )

        with pytest.raises(ConfigError, match="is not tracked in"):
            verify_pinned_copy(pinned, other, b"a: 1\n")

    def test_edited_file_names_the_two_fixes(self, tmp_path):
        """Tests that a hash mismatch says to move edits or run update."""
        pinned, location = self._project(
            tmp_path, b"edited\n", _lockfile_text(canonical_sha256(b"original\n"))
        )

        with pytest.raises(ConfigError, match="differs from what .* recorded") as err:
            verify_pinned_copy(pinned, location, b"edited\n")

        assert "napt upstream update" in str(err.value)
        assert "override" in str(err.value)


class TestFilterPinnedParent:
    """Tests for the parent allow list."""

    def test_app_owned_keys_are_kept(self):
        """Tests that discovery, install blocks, and detection pass through."""
        parent = {
            "apiVersion": "napt/v1",
            "name": "Chrome",
            "id": "chrome",
            "discovery": {"strategy": "url_download", "url": "https://x/a.msi"},
            "psadt": {"app_vars": {"AppName": "Chrome"}, "install": "Start-X"},
            "intune": {"detection": {"exact_match": True}, "publisher": "Google"},
        }

        kept, dropped = filter_pinned_parent(parent)

        assert kept == parent
        assert dropped == ()

    def test_tenant_keys_are_dropped_and_named(self):
        """Tests that org-policy keys are removed in the order written."""
        parent = {
            "name": "Chrome",
            "deployment": {"rings": []},
            "psadt": {"release": "4.1.7", "install": "Start-X"},
            "intune": {"build_types": "both", "logo_path": "x.png", "owner": "IT"},
            "directories": {"state": "elsewhere"},
            "secrets": {"TOKEN": {"hosts": ["evil.example"]}},
        }

        kept, dropped = filter_pinned_parent(parent)

        assert kept == {"name": "Chrome", "psadt": {"install": "Start-X"}}
        assert dropped == (
            "deployment",
            "psadt.release",
            "intune.build_types",
            "intune.logo_path",
            "intune.owner",
            "directories",
            "secrets",
        )

    @pytest.mark.parametrize("value", [[], None, "not a mapping"])
    def test_restricted_section_of_the_wrong_shape_is_dropped(self, value):
        """Tests that a non-mapping psadt or intune cannot replace the tenant's."""
        kept, dropped = filter_pinned_parent({"name": "X", "intune": value})

        assert kept == {"name": "X"}
        assert dropped == ("intune",)

    def test_whole_section_of_the_wrong_shape_passes_through(self):
        """Tests that validation, not the filter, reports a malformed discovery."""
        kept, dropped = filter_pinned_parent({"discovery": "not a mapping"})

        assert kept == {"discovery": "not a mapping"}
        assert dropped == ()

    def test_every_schema_key_is_classified(self):
        """Tests that the allow list and the dropped set cover the schema."""
        from napt.validation import _INTUNE_FIELDS, _PSADT_FIELDS

        dropped_psadt = {"release", "brand_pack"}
        dropped_intune = {
            "build_types",
            "update_name_prefix",
            "install_command",
            "uninstall_command",
            "is_featured",
            "allow_available_uninstall",
            "enforce_signature_check",
            "owner",
            "logo_path",
        }
        psadt_allowed = ALLOWED_PARENT_KEYS["psadt"]
        intune_allowed = ALLOWED_PARENT_KEYS["intune"]
        assert psadt_allowed is not None and intune_allowed is not None

        assert set(_PSADT_FIELDS) == psadt_allowed | dropped_psadt
        assert set(_INTUNE_FIELDS) == intune_allowed | dropped_intune
