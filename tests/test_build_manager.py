"""
Tests for notapkgtool.build.manager module.

Tests build orchestration including:
- Finding installer files
- Extracting versions
- Creating build directories
- Copying PSADT and installers
- Applying branding

These are UNIT tests using mocked/fake data for fast execution.
For integration tests with real PSADT, see test_integration_build.py.
"""

from __future__ import annotations

import pytest

from notapkgtool.build.manager import (
    _apply_branding,
    _copy_installer,
    _copy_psadt_pristine,
    _create_build_directory,
    _find_installer_file,
)

# All tests in this file are unit tests (fast, mocked)
pytestmark = pytest.mark.unit


class TestFindInstallerFile:
    """Tests for finding installer files."""

    def test_find_by_url(self, tmp_path):
        """Test finding installer using URL from config."""
        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        installer = downloads_dir / "chrome.msi"
        installer.write_text("fake msi")

        config = {"apps": [{"source": {"url": "https://example.com/chrome.msi"}}]}

        result = _find_installer_file(downloads_dir, config)

        assert result == installer

    def test_find_by_pattern_msi(self, tmp_path):
        """Test finding installer by .msi pattern."""
        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        installer = downloads_dir / "app.msi"
        installer.write_text("fake msi")

        config = {"apps": [{"source": {}}]}

        result = _find_installer_file(downloads_dir, config)

        assert result == installer

    def test_find_by_pattern_exe(self, tmp_path):
        """Test finding installer by .exe pattern."""
        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        installer = downloads_dir / "setup.exe"
        installer.write_text("fake exe")

        config = {"apps": [{"source": {}}]}

        result = _find_installer_file(downloads_dir, config)

        assert result == installer

    def test_find_most_recent(self, tmp_path):
        """Test finding most recent installer when multiple exist."""
        import time

        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()

        old = downloads_dir / "old.msi"
        old.write_text("old")
        time.sleep(0.01)

        new = downloads_dir / "new.msi"
        new.write_text("new")

        config = {"apps": [{"source": {}}]}

        result = _find_installer_file(downloads_dir, config)

        assert result == new

    def test_find_not_found_raises(self, tmp_path):
        """Test error when no installer found."""
        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()

        config = {"apps": [{"source": {}}]}

        with pytest.raises(FileNotFoundError, match="No installer found"):
            _find_installer_file(downloads_dir, config)


class TestCreateBuildDirectory:
    """Tests for creating build directories."""

    def test_create_new_directory(self, tmp_path):
        """Test creating a new build directory."""
        base_dir = tmp_path / "builds"
        app_id = "test-app"
        version = "1.0.0"

        result = _create_build_directory(base_dir, app_id, version)

        expected = base_dir / "test-app" / "1.0.0"
        assert result == expected
        assert result.exists()
        # Note: Files/ and SupportFiles/ come from template, not created here

    def test_create_replaces_existing(self, tmp_path):
        """Test that existing build directory is replaced."""
        base_dir = tmp_path / "builds"
        app_id = "test-app"
        version = "1.0.0"

        # Create existing directory with a file
        existing = base_dir / "test-app" / "1.0.0"
        existing.mkdir(parents=True)
        (existing / "old_file.txt").write_text("old")

        result = _create_build_directory(base_dir, app_id, version)

        assert result == existing
        assert not (result / "old_file.txt").exists()


class TestCopyPSADTPristine:
    """Tests for copying PSADT files (unit tests with fake data)."""

    def test_copy_psadt_structure(self, fake_psadt_template, tmp_path):
        """Test copying PSADT directory structure using fake template."""
        # Use the fake_psadt_template fixture
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_pristine(fake_psadt_template, build_dir)

        # Verify v4 structure copied
        assert (build_dir / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").exists()
        assert (build_dir / "Invoke-AppDeployToolkit.exe").exists()
        assert (build_dir / "Invoke-AppDeployToolkit.ps1").exists()
        assert (build_dir / "Assets").is_dir()
        assert (build_dir / "Files").is_dir()
        assert (build_dir / "Config").is_dir()

    def test_copy_psadt_missing_directory_raises(self, tmp_path):
        """Test error when PSADT directory doesn't exist."""
        cache_dir = tmp_path / "cache" / "4.1.7"
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="PSADT.*not found"):
            _copy_psadt_pristine(cache_dir, build_dir)


class TestCopyInstaller:
    """Tests for copying installer files."""

    def test_copy_installer(self, tmp_path):
        """Test copying installer to Files directory."""
        installer = tmp_path / "app.msi"
        installer.write_bytes(b"fake msi content")

        build_dir = tmp_path / "build"
        files_dir = build_dir / "Files"
        files_dir.mkdir(parents=True)

        _copy_installer(installer, build_dir)

        dest = files_dir / "app.msi"
        assert dest.exists()
        assert dest.read_bytes() == b"fake msi content"


class TestApplyBranding:
    """Tests for applying custom branding (unit tests with fake data)."""

    def test_apply_branding_success(
        self, fake_psadt_template, fake_brand_pack, tmp_path
    ):
        """Test applying branding assets to v4 structure."""
        # Create build with fake template
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_psadt_pristine(fake_psadt_template, build_dir)

        brand_dir, config = fake_brand_pack

        _apply_branding(config, build_dir)

        # Verify branding applied to root Assets/ (v4 structure)
        target = build_dir / "Assets" / "AppIcon.png"
        assert target.exists()
        assert target.read_bytes() == b"custom icon data"

    def test_apply_branding_no_config(self, tmp_path):
        """Test when no branding configured."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        config = {"defaults": {}}

        # Should not raise
        _apply_branding(config, build_dir)

    def test_apply_branding_missing_files(self, tmp_path):
        """Test when branding files don't exist."""
        brand_dir = tmp_path / "branding"
        brand_dir.mkdir()

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        config = {
            "defaults": {
                "psadt": {
                    "brand_pack": {
                        "path": str(brand_dir),
                        "mappings": [
                            {"source": "NonExistent.*", "target": "Assets/AppIcon"}
                        ],
                    }
                }
            }
        }

        # Should not raise - just skip missing files
        _apply_branding(config, build_dir)
