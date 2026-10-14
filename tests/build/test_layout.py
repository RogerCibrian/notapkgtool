"""Tests for napt.build.layout: the build folder and what is copied into it."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from napt.build.layout import (
    apply_branding,
    copy_installer,
    copy_psadt_template,
    create_build_directory,
    write_build_file,
)
from napt.exceptions import ConfigError, PackagingError


class TestCreateBuildDirectory:
    """Tests for creating build directories."""

    def test_create_new_directory(self, tmp_path):
        """Tests that the packagefiles folder is created under app/version."""
        base_dir = tmp_path / "builds"

        result = create_build_directory(base_dir, "test-app", "1.0.0")

        expected = base_dir / "test-app" / "1.0.0" / "packagefiles"
        assert result == expected
        assert result.exists()

    def test_create_replaces_existing(self, tmp_path):
        """Tests that an existing build directory is replaced."""
        base_dir = tmp_path / "builds"
        existing = base_dir / "test-app" / "1.0.0"
        existing.mkdir(parents=True)
        (existing / "old_file.txt").write_text("old")

        result = create_build_directory(base_dir, "test-app", "1.0.0")

        assert result == base_dir / "test-app" / "1.0.0" / "packagefiles"
        assert not (existing / "old_file.txt").exists()

    def test_version_with_parent_segments_deletes_nothing(self, tmp_path):
        """Tests that a traversing version is refused before any delete."""
        base_dir = tmp_path / "builds"
        victim = tmp_path / "important"
        victim.mkdir()
        (victim / "keep.txt").write_text("keep")
        # From builds/test-app/, two levels up is tmp_path, so this version
        # would resolve to the victim folder and the rebuild would delete it.
        version = "../../important"

        with pytest.raises(PackagingError, match="cannot be used as a folder name"):
            create_build_directory(base_dir, "test-app", version)

        assert (victim / "keep.txt").exists()

    def test_unwritable_base_is_a_packaging_error(self, tmp_path):
        """Tests that a builds path that cannot hold folders is reported."""
        base_dir = tmp_path / "builds"
        base_dir.write_text("not a directory")

        with pytest.raises(PackagingError, match="Cannot create"):
            create_build_directory(base_dir, "test-app", "1.0.0")


class TestCopyPSADTPristine:
    """Tests for copying PSADT files (unit tests with fake data)."""

    def test_copy_psadt_structure(self, fake_psadt_template, tmp_path):
        """Tests that the v4 structure is copied whole."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        copy_psadt_template(fake_psadt_template, build_dir)

        assert (build_dir / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").exists()
        assert (build_dir / "Invoke-AppDeployToolkit.exe").exists()
        assert (build_dir / "Invoke-AppDeployToolkit.ps1").exists()
        assert (build_dir / "Assets").is_dir()
        assert (build_dir / "Files").is_dir()
        assert (build_dir / "Config").is_dir()

    def test_copy_psadt_missing_directory_raises(self, tmp_path):
        """Tests that a missing PSADT cache directory is an error."""
        cache_dir = tmp_path / "cache" / "4.1.7"
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        with pytest.raises(PackagingError, match="PSADT.*not found"):
            copy_psadt_template(cache_dir, build_dir)

    def test_copy_failure_is_a_packaging_error(self, fake_psadt_template, tmp_path):
        """Tests that a copy the file system refuses is reported by path."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        with patch(
            "napt.build.layout.shutil.copytree",
            side_effect=OSError(28, "No space left on device"),
        ):
            with pytest.raises(PackagingError, match="No space left"):
                copy_psadt_template(fake_psadt_template, build_dir)


class TestCopyInstaller:
    """Tests for copying installer files."""

    def test_copy_installer(self, tmp_path):
        """Tests that the installer lands in Files/."""
        installer = tmp_path / "app.msi"
        installer.write_bytes(b"fake msi content")
        build_dir = tmp_path / "build"
        (build_dir / "Files").mkdir(parents=True)

        copy_installer(installer, build_dir)

        dest = build_dir / "Files" / "app.msi"
        assert dest.read_bytes() == b"fake msi content"

    def test_copy_failure_is_a_packaging_error(self, tmp_path):
        """Tests that a copy the file system refuses is reported by path."""
        installer = tmp_path / "app.msi"
        installer.write_bytes(b"fake msi content")
        build_dir = tmp_path / "build"
        (build_dir / "Files").mkdir(parents=True)

        with patch(
            "napt.build.layout.shutil.copy2",
            side_effect=OSError(13, "Permission denied"),
        ):
            with pytest.raises(PackagingError, match="app.msi"):
                copy_installer(installer, build_dir)


class TestApplyBranding:
    """Tests for applying custom branding (unit tests with fake data)."""

    def test_apply_branding_success(
        self, fake_psadt_template, fake_brand_pack, tmp_path
    ):
        """Tests that brand assets replace the ones in the root Assets/."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        copy_psadt_template(fake_psadt_template, build_dir)
        _brand_dir, config = fake_brand_pack

        apply_branding(config, build_dir)

        target = build_dir / "Assets" / "AppIcon.png"
        assert target.read_bytes() == b"custom icon data"

    def test_apply_branding_copy_failure_is_a_packaging_error(
        self, fake_psadt_template, fake_brand_pack, tmp_path
    ):
        """Tests that a brand asset the file system refuses to copy is
        reported by path, not as an OSError traceback."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        copy_psadt_template(fake_psadt_template, build_dir)
        _brand_dir, config = fake_brand_pack

        with patch(
            "napt.build.layout.shutil.copy2",
            side_effect=OSError(13, "Permission denied"),
        ):
            with pytest.raises(PackagingError, match="Permission denied"):
                apply_branding(config, build_dir)

    def test_apply_branding_no_config(self, tmp_path):
        """Tests that no brand pack means PSADT's defaults stay."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        config = {"psadt": {"brand_pack": {"path": "", "mappings": []}}}

        apply_branding(config, build_dir)

    def test_missing_brand_pack_path_is_a_config_error(self, tmp_path):
        """Tests that a configured folder that does not exist fails the build
        instead of shipping a package with default branding."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        config = {
            "psadt": {
                "brand_pack": {
                    "path": str(tmp_path / "nope"),
                    "mappings": [{"source": "AppIcon.*", "target": "Assets/AppIcon"}],
                }
            }
        }

        with pytest.raises(ConfigError, match="brand_pack.path") as info:
            apply_branding(config, build_dir)
        assert str(tmp_path / "nope") in str(info.value)

    def test_mapping_matching_nothing_is_skipped(self, tmp_path):
        """Tests that a glob with no match leaves the default asset alone."""
        brand_dir = tmp_path / "branding"
        brand_dir.mkdir()
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        config = {
            "psadt": {
                "brand_pack": {
                    "path": str(brand_dir),
                    "mappings": [
                        {"source": "NonExistent.*", "target": "Assets/AppIcon"}
                    ],
                }
            }
        }

        apply_branding(config, build_dir)

        assert not (build_dir / "Assets").exists()


class TestWriteBuildFile:
    """Tests for the guarded write every generated build file goes through."""

    def test_writes_the_text(self, tmp_path):
        """Tests that the file lands with the given encoding."""
        target = tmp_path / "Invoke-AppDeployToolkit.ps1"

        write_build_file(target, "Write-Host hi\n", "utf-8-sig")

        assert target.read_bytes().startswith(b"\xef\xbb\xbf")
        assert target.read_text(encoding="utf-8-sig") == "Write-Host hi\n"

    def test_write_failure_is_a_packaging_error(self, tmp_path):
        """Tests that a file the file system refuses to write is reported by
        path, not as an OSError traceback."""
        target = tmp_path / "Invoke-AppDeployToolkit.ps1"
        target.mkdir()

        with pytest.raises(PackagingError, match="Invoke-AppDeployToolkit.ps1"):
            write_build_file(target, "x", "utf-8")
