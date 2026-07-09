"""
Tests for napt.build.manager module.

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

import json
from pathlib import Path

import pytest

from napt.build.icons import IconExtraction
from napt.build.manager import (
    _apply_branding,
    _apply_msi_commands,
    _copy_installer,
    _copy_psadt_template,
    _create_build_directory,
    _extract_app_icon,
    _find_installer_file,
    _get_installer_version,
    _write_build_manifest,
)
from napt.exceptions import ConfigError
from napt.versioning.msi import MSIMetadata

# All tests in this file are unit tests (fast, mocked)


def _write_pending_state(state_dir: Path, app_id: str, pending: dict) -> None:
    """Writes a deployment state file with the given pending release."""
    deployment_dir = state_dir / "deployment"
    deployment_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "schemaVersion": 1,
        "deployed": None,
        "pending": pending,
        "rings": {},
        "retained": [],
    }
    (deployment_dir / f"{app_id}.json").write_text(json.dumps(state))


class TestFindInstallerFile:
    """Tests for finding installer files."""

    def test_find_by_url(self, tmp_path):
        """Test finding installer using URL from config."""
        downloads_dir = tmp_path / "downloads"
        app_dir = downloads_dir / "napt-chrome"
        app_dir.mkdir(parents=True)
        installer = app_dir / "chrome.msi"
        installer.write_text("fake msi")

        config = {
            "id": "napt-chrome",
            "discovery": {"url": "https://example.com/chrome.msi"},
        }

        result = _find_installer_file(downloads_dir, config)

        assert result == installer

    def test_find_by_pattern_msi(self, tmp_path):
        """Test finding installer by .msi pattern."""
        downloads_dir = tmp_path / "downloads"
        app_dir = downloads_dir / "test-app"
        app_dir.mkdir(parents=True)
        installer = app_dir / "test-app.msi"
        installer.write_text("fake msi")

        config = {"id": "test-app", "name": "Test App", "discovery": {}}

        result = _find_installer_file(downloads_dir, config)

        assert result == installer

    def test_find_by_pattern_exe(self, tmp_path):
        """Test finding installer by .exe pattern."""
        downloads_dir = tmp_path / "downloads"
        app_dir = downloads_dir / "test-app"
        app_dir.mkdir(parents=True)
        installer = app_dir / "test-app-setup.exe"
        installer.write_text("fake exe")

        config = {"id": "test-app", "name": "Test App", "discovery": {}}

        result = _find_installer_file(downloads_dir, config)

        assert result == installer

    def test_find_most_recent(self, tmp_path):
        """Test finding most recent installer when multiple exist."""
        import time

        downloads_dir = tmp_path / "downloads"
        app_dir = downloads_dir / "test-app"
        app_dir.mkdir(parents=True)

        old = app_dir / "test-app-1.0.msi"
        old.write_text("old")
        time.sleep(0.01)

        new = app_dir / "test-app-2.0.msi"
        new.write_text("new")

        config = {"id": "test-app", "name": "Test App", "discovery": {}}

        result = _find_installer_file(downloads_dir, config)

        assert result == new

    def test_find_by_deployment_state_url(self, tmp_path):
        """Tests that the pending release URL locates a vendor filename
        that name matching cannot."""
        downloads_dir = tmp_path / "downloads"
        app_dir = downloads_dir / "napt-test-7zip"
        app_dir.mkdir(parents=True)
        installer = app_dir / "7z2602-x64.exe"
        installer.write_text("fake exe")

        _write_pending_state(
            tmp_path / "state",
            "napt-test-7zip",
            {
                "version": "26.02",
                "sha256": "abc123",
                "url": "https://example.com/dl/7z2602-x64.exe",
            },
        )

        config = {
            "id": "napt-test-7zip",
            "name": "NAPT Test 7-Zip",
            "discovery": {},
            "directories": {"state": str(tmp_path / "state")},
        }

        result = _find_installer_file(downloads_dir, config)

        assert result == installer

    def test_find_no_pending_state_falls_through(self, tmp_path):
        """Tests that an empty deployment state falls through to name
        matching."""
        downloads_dir = tmp_path / "downloads"
        app_dir = downloads_dir / "test-app"
        app_dir.mkdir(parents=True)
        installer = app_dir / "test-app.msi"
        installer.write_text("fake msi")

        config = {
            "id": "test-app",
            "name": "Test App",
            "discovery": {},
            "directories": {"state": str(tmp_path / "state")},
        }

        result = _find_installer_file(downloads_dir, config)

        assert result == installer

    def test_find_not_found_raises(self, tmp_path):
        """Test error when no installer found."""
        downloads_dir = tmp_path / "downloads"
        app_dir = downloads_dir / "test-app"
        app_dir.mkdir(parents=True)

        config = {"id": "test-app", "name": "Test App", "discovery": {}}

        from napt.exceptions import PackagingError

        with pytest.raises(PackagingError, match="Cannot locate installer file"):
            _find_installer_file(downloads_dir, config)


class TestGetInstallerVersion:
    """Tests for determining installer versions."""

    def test_version_from_deployment_state(self, tmp_path):
        """Tests that a non-MSI installer version falls back to the
        pending release in deployment state."""
        installer = tmp_path / "7z2602-x64.exe"
        installer.write_text("fake exe")

        _write_pending_state(
            tmp_path / "state",
            "napt-test-7zip",
            {
                "version": "26.02",
                "sha256": "abc123",
                "url": "https://example.com/dl/7z2602-x64.exe",
            },
        )

        config = {
            "id": "napt-test-7zip",
            "name": "NAPT Test 7-Zip",
            "directories": {"state": str(tmp_path / "state")},
        }

        assert _get_installer_version(installer, config) == "26.02"

    def test_discovery_cache_wins_over_state(self, tmp_path):
        """Tests that the discovery cache version takes priority over
        deployment state."""
        installer = tmp_path / "app-setup.exe"
        installer.write_text("fake exe")

        cache_file = tmp_path / "cache" / "discovery.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(
            json.dumps({"apps": {"test-app": {"known_version": "1.2.3"}}})
        )

        _write_pending_state(
            tmp_path / "state",
            "test-app",
            {"version": "9.9.9", "sha256": "abc123", "url": ""},
        )

        config = {
            "id": "test-app",
            "name": "Test App",
            "directories": {"state": str(tmp_path / "state")},
        }

        assert _get_installer_version(installer, config, cache_file) == "1.2.3"

    def test_no_version_source_raises(self, tmp_path):
        """Tests that a non-MSI installer with no cache and no pending
        release raises ConfigError."""
        installer = tmp_path / "app-setup.exe"
        installer.write_text("fake exe")

        config = {
            "id": "test-app",
            "name": "Test App",
            "directories": {"state": str(tmp_path / "state")},
        }

        with pytest.raises(ConfigError, match="Could not determine version"):
            _get_installer_version(installer, config)


class TestCreateBuildDirectory:
    """Tests for creating build directories."""

    def test_create_new_directory(self, tmp_path):
        """Test creating a new build directory."""
        base_dir = tmp_path / "builds"
        app_id = "test-app"
        version = "1.0.0"

        result = _create_build_directory(base_dir, app_id, version)

        expected = base_dir / "test-app" / "1.0.0" / "packagefiles"
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

        expected = base_dir / "test-app" / "1.0.0" / "packagefiles"
        assert result == expected
        assert not (existing / "old_file.txt").exists()


class TestCopyPSADTPristine:
    """Tests for copying PSADT files (unit tests with fake data)."""

    def test_copy_psadt_structure(self, fake_psadt_template, tmp_path):
        """Test copying PSADT directory structure using fake template."""
        # Use the fake_psadt_template fixture
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_template(fake_psadt_template, build_dir)

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

        from napt.exceptions import PackagingError

        with pytest.raises(PackagingError, match="PSADT.*not found"):
            _copy_psadt_template(cache_dir, build_dir)


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
        _copy_psadt_template(fake_psadt_template, build_dir)

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

        config = {"psadt": {"brand_pack": {"path": "", "mappings": []}}}

        # Should not raise
        _apply_branding(config, build_dir)

    def test_apply_branding_missing_files(self, tmp_path):
        """Test when branding files don't exist."""
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

        # Should not raise - just skip missing files
        _apply_branding(config, build_dir)


class TestWriteBuildManifest:
    """Tests for build manifest generation."""

    def test_manifest_contains_required_fields(self, tmp_path):
        """Test that manifest contains all required fields."""
        # Create build structure
        version_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        build_dir = version_dir / "packagefiles"
        build_dir.mkdir(parents=True)

        detection_path = version_dir / "Test-App_1.0.0-Detection.ps1"
        requirements_path = version_dir / "Test-App_1.0.0-Requirements.ps1"
        detection_path.write_text("# detection")
        requirements_path.write_text("# requirements")

        result = _write_build_manifest(
            build_dir=build_dir,
            app_id="test-app",
            app_name="Test App",
            version="1.0.0",
            build_types="both",
            architecture="x64",
            installer_sha256="a" * 64,
            detection_script_path=detection_path,
            requirements_script_path=requirements_path,
        )

        assert result.exists()
        assert result.name == "build-manifest.json"

        manifest = json.loads(result.read_text(encoding="utf-8"))

        assert manifest["app_id"] == "test-app"
        assert manifest["app_name"] == "Test App"
        assert manifest["version"] == "1.0.0"
        assert manifest["win32_build_types"] == "both"
        assert manifest["architecture"] == "x64"
        assert manifest["installer_sha256"] == "a" * 64
        assert manifest["detection_script_path"] == "Test-App_1.0.0-Detection.ps1"
        assert manifest["requirements_script_path"] == "Test-App_1.0.0-Requirements.ps1"

    def test_manifest_build_types_app_only(self, tmp_path):
        """Test manifest for app_only build type."""
        version_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        build_dir = version_dir / "packagefiles"
        build_dir.mkdir(parents=True)

        detection_path = version_dir / "Test-App_1.0.0-Detection.ps1"
        detection_path.write_text("# detection")

        result = _write_build_manifest(
            build_dir=build_dir,
            app_id="test-app",
            app_name="Test App",
            version="1.0.0",
            build_types="app_only",
            architecture="x64",
            installer_sha256="a" * 64,
            detection_script_path=detection_path,
            requirements_script_path=None,  # No requirements script for app_only
        )

        manifest = json.loads(result.read_text(encoding="utf-8"))

        assert manifest["win32_build_types"] == "app_only"
        assert manifest["detection_script_path"] == "Test-App_1.0.0-Detection.ps1"
        assert "requirements_script_path" not in manifest

    def test_manifest_build_types_update_only(self, tmp_path):
        """Test manifest for update_only build type (detection always generated)."""
        version_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        build_dir = version_dir / "packagefiles"
        build_dir.mkdir(parents=True)

        detection_path = version_dir / "Test-App_1.0.0-Detection.ps1"
        detection_path.write_text("# detection")
        requirements_path = version_dir / "Test-App_1.0.0-Requirements.ps1"
        requirements_path.write_text("# requirements")

        result = _write_build_manifest(
            build_dir=build_dir,
            app_id="test-app",
            app_name="Test App",
            version="1.0.0",
            build_types="update_only",
            architecture="x64",
            installer_sha256="a" * 64,
            detection_script_path=detection_path,  # Detection always generated
            requirements_script_path=requirements_path,
        )

        manifest = json.loads(result.read_text(encoding="utf-8"))

        assert manifest["win32_build_types"] == "update_only"
        assert manifest["detection_script_path"] == "Test-App_1.0.0-Detection.ps1"
        assert manifest["requirements_script_path"] == "Test-App_1.0.0-Requirements.ps1"

    def test_manifest_script_paths_are_relative(self, tmp_path):
        """Test that script paths in manifest are relative (filename only)."""
        version_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        build_dir = version_dir / "packagefiles"
        build_dir.mkdir(parents=True)

        detection_path = version_dir / "Google-Chrome_131.0.0-Detection.ps1"
        detection_path.write_text("# detection")

        result = _write_build_manifest(
            build_dir=build_dir,
            app_id="napt-chrome",
            app_name="Google Chrome",
            version="131.0.0",
            build_types="app_only",
            architecture="x64",
            installer_sha256="a" * 64,
            detection_script_path=detection_path,
            requirements_script_path=None,
        )

        manifest = json.loads(result.read_text(encoding="utf-8"))

        # Path should be filename only (relative), not absolute path
        assert (
            manifest["detection_script_path"] == "Google-Chrome_131.0.0-Detection.ps1"
        )
        assert "/" not in manifest["detection_script_path"]
        assert "\\" not in manifest["detection_script_path"]

    def test_manifest_location_sibling_to_packagefiles(self, tmp_path):
        """Test that manifest is saved as sibling to packagefiles/."""
        version_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        build_dir = version_dir / "packagefiles"
        build_dir.mkdir(parents=True)

        result = _write_build_manifest(
            build_dir=build_dir,
            app_id="test-app",
            app_name="Test App",
            version="1.0.0",
            build_types="both",
            architecture="x64",
            installer_sha256="a" * 64,
            detection_script_path=None,
            requirements_script_path=None,
        )

        # Manifest should be in version_dir, not in packagefiles/
        assert result.parent == version_dir
        assert result.parent.name == "1.0.0"


class TestExtractAppIcon:
    """Tests for the _extract_app_icon build hook."""

    @staticmethod
    def _fail_if_called(installer_path):
        raise AssertionError("extract_icon_png should not have been called")

    def _config(self, make_config, tmp_path):
        return make_config(
            {
                "id": "test-app",
                "name": "Test App",
                "directories": {"icons": str(tmp_path / "icons")},
            }
        )

    @staticmethod
    def _installer(tmp_path):
        installer = tmp_path / "app.msi"
        installer.write_bytes(b"fake msi")
        return installer

    def test_logo_path_set_skips_extraction(
        self, make_config, tmp_path, monkeypatch, capsys
    ):
        """Tests that extraction is skipped when intune.logo_path is set."""
        import napt.build.manager as manager_module

        monkeypatch.setattr(manager_module, "extract_icon_png", self._fail_if_called)
        config = self._config(make_config, tmp_path)
        config["intune"]["logo_path"] = str(tmp_path / "logo.png")

        _extract_app_icon(config, self._installer(tmp_path), "test-app")

        assert "intune.logo_path is set" in capsys.readouterr().out

    def test_existing_icon_file_skips_extraction(
        self, make_config, tmp_path, monkeypatch, capsys
    ):
        """Tests that an existing icon file is never overwritten."""
        import napt.build.manager as manager_module

        monkeypatch.setattr(manager_module, "extract_icon_png", self._fail_if_called)
        config = self._config(make_config, tmp_path)
        icon_path = tmp_path / "icons" / "test-app.png"
        icon_path.parent.mkdir(parents=True)
        icon_path.write_bytes(b"curated icon")

        _extract_app_icon(config, self._installer(tmp_path), "test-app")

        assert "already exists" in capsys.readouterr().out
        assert icon_path.read_bytes() == b"curated icon"

    def test_success_writes_icon_file(
        self, make_config, tmp_path, monkeypatch, capsys
    ):
        """Tests that a successful extraction writes the icon file."""
        import napt.build.manager as manager_module

        monkeypatch.setattr(
            manager_module,
            "extract_icon_png",
            lambda path: IconExtraction(b"png bytes", 256, "MSI Icon table"),
        )
        config = self._config(make_config, tmp_path)

        _extract_app_icon(config, self._installer(tmp_path), "test-app")

        icon_path = tmp_path / "icons" / "test-app.png"
        assert icon_path.read_bytes() == b"png bytes"
        assert "Extracted app icon (256px)" in capsys.readouterr().out

    def test_failure_warns_with_remedies(
        self, make_config, tmp_path, monkeypatch, capsys
    ):
        """Tests that a failed extraction warns with actionable remedies."""
        import napt.build.manager as manager_module

        monkeypatch.setattr(
            manager_module,
            "extract_icon_png",
            lambda path: IconExtraction(None, None, "no Icon table in MSI"),
        )
        config = self._config(make_config, tmp_path)

        _extract_app_icon(config, self._installer(tmp_path), "test-app")

        output = capsys.readouterr().out
        assert "no Icon table in MSI" in output
        assert "test-app.png" in output
        assert "intune.logo_path" in output
        icon_path = tmp_path / "icons" / "test-app.png"
        assert not icon_path.exists()

    def test_failure_writes_no_icon_marker(self, make_config, tmp_path, monkeypatch):
        """Tests that a failed extraction records a .no-icon marker."""
        import napt.build.manager as manager_module

        monkeypatch.setattr(
            manager_module,
            "extract_icon_png",
            lambda path: IconExtraction(None, None, "no Icon table in MSI"),
        )
        config = self._config(make_config, tmp_path)
        installer = self._installer(tmp_path)

        _extract_app_icon(config, installer, "test-app")

        marker = tmp_path / "icons" / "test-app.no-icon"
        assert installer.name in marker.read_text(encoding="utf-8")

    def test_matching_marker_skips_extraction(
        self, make_config, tmp_path, monkeypatch, capsys
    ):
        """Tests that a marker for the same installer skips re-extraction."""
        import napt.build.manager as manager_module

        monkeypatch.setattr(
            manager_module,
            "extract_icon_png",
            lambda path: IconExtraction(None, None, "no Icon table in MSI"),
        )
        config = self._config(make_config, tmp_path)
        installer = self._installer(tmp_path)
        _extract_app_icon(config, installer, "test-app")
        capsys.readouterr()

        monkeypatch.setattr(manager_module, "extract_icon_png", self._fail_if_called)
        _extract_app_icon(config, installer, "test-app")

        assert "no icon was found in this installer previously" in (
            capsys.readouterr().out
        )

    def test_stale_marker_re_extracts(self, make_config, tmp_path, monkeypatch):
        """Tests that a marker from a different installer does not skip."""
        import napt.build.manager as manager_module

        config = self._config(make_config, tmp_path)
        installer = self._installer(tmp_path)
        marker = tmp_path / "icons" / "test-app.no-icon"
        marker.parent.mkdir(parents=True)
        marker.write_text("other.msi|123|456", encoding="utf-8")

        monkeypatch.setattr(
            manager_module,
            "extract_icon_png",
            lambda path: IconExtraction(b"png bytes", 256, "MSI Icon table"),
        )
        _extract_app_icon(config, installer, "test-app")

        icon_path = tmp_path / "icons" / "test-app.png"
        assert icon_path.read_bytes() == b"png bytes"

    def test_success_clears_marker(self, make_config, tmp_path, monkeypatch):
        """Tests that a successful extraction removes a stale marker."""
        import napt.build.manager as manager_module

        config = self._config(make_config, tmp_path)
        marker = tmp_path / "icons" / "test-app.no-icon"
        marker.parent.mkdir(parents=True)
        marker.write_text("other.msi|123|456", encoding="utf-8")
        monkeypatch.setattr(
            manager_module,
            "extract_icon_png",
            lambda path: IconExtraction(b"png bytes", 256, "MSI Icon table"),
        )

        _extract_app_icon(config, self._installer(tmp_path), "test-app")

        assert not marker.exists()

    def test_write_error_warns_without_raising(
        self, make_config, tmp_path, monkeypatch, capsys
    ):
        """Tests that a filesystem error while writing warns, not raises."""
        import napt.build.manager as manager_module

        monkeypatch.setattr(
            manager_module,
            "extract_icon_png",
            lambda path: IconExtraction(b"png bytes", 256, "MSI Icon table"),
        )
        config = self._config(make_config, tmp_path)
        # Occupy the icons directory path with a file so mkdir fails
        (tmp_path / "icons").write_bytes(b"not a directory")

        _extract_app_icon(config, self._installer(tmp_path), "test-app")

        assert "Could not write app icon" in capsys.readouterr().out


class TestApplyMsiCommands:
    """Tests for MSI install/uninstall command auto-generation."""

    EXPECTED_INSTALL = (
        'Start-ADTMsiProcess -Action Install -FilePath "7z2501-x64.msi"'
        ' -AdditionalArgumentList "ALLUSERS=1"'
    )
    EXPECTED_UNINSTALL = (
        "Uninstall-ADTApplication -Name '7-Zip 25.01 (x64 edition)'"
        " -NameMatch 'Exact' -ApplicationType 'MSI'"
    )

    @pytest.fixture(autouse=True)
    def _verbose_logger(self):
        """Installs a visible logger and restores the default afterward."""
        from napt.logging import get_global_logger, get_logger, set_global_logger

        previous = get_global_logger()
        set_global_logger(get_logger(verbose=True))
        yield
        set_global_logger(previous)

    @staticmethod
    def _logger():
        from napt.logging import get_global_logger

        return get_global_logger()

    @staticmethod
    def _metadata(product_name="7-Zip 25.01 (x64 edition)"):
        return MSIMetadata(
            product_name=product_name,
            product_version="25.01.00.0",
            architecture="x64",
        )

    @staticmethod
    def _config(install=None, uninstall=None, override=None, run_as="system"):
        psadt = {"app_vars": {"AppName": "7-Zip"}}
        if install is not None:
            psadt["install"] = install
        if uninstall is not None:
            psadt["uninstall"] = uninstall
        if override is not None:
            psadt["override_msi_commands"] = override
        return {"psadt": psadt, "intune": {"run_as_account": run_as}}

    INSTALLER = Path("7z2501-x64.msi")

    def test_default_generates_install_command(self):
        """Tests that the install command is auto-generated by default."""
        config = self._config()

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert config["psadt"]["install"] == self.EXPECTED_INSTALL

    def test_default_generates_uninstall_command(self):
        """Tests that the uninstall command uses exact ProductName matching."""
        config = self._config()

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert config["psadt"]["uninstall"] == self.EXPECTED_UNINSTALL

    def test_user_account_omits_allusers(self):
        """Tests that run_as_account user omits the ALLUSERS argument."""
        config = self._config(run_as="user")

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert "ALLUSERS" not in config["psadt"]["install"]
        assert config["psadt"]["install"].endswith('"7z2501-x64.msi"')

    def test_default_ignores_recipe_install_with_warning(self, capsys):
        """Tests that a recipe install command is ignored with a warning."""
        config = self._config(install="Custom-Install")

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert config["psadt"]["install"] == self.EXPECTED_INSTALL
        output = capsys.readouterr().out
        assert "ignored for MSI installers" in output
        assert "override_msi_commands" in output

    def test_default_ignores_recipe_uninstall_with_warning(self, capsys):
        """Tests that a recipe uninstall command is ignored with a warning."""
        config = self._config(uninstall="Custom-Uninstall")

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert config["psadt"]["uninstall"] == self.EXPECTED_UNINSTALL
        assert "psadt.uninstall is set but will be ignored" in (
            capsys.readouterr().out
        )

    def test_default_overwrites_both_when_only_install_set(self, capsys):
        """Tests that both commands are replaced when only install is set."""
        config = self._config(install="Custom-Install")

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert config["psadt"]["install"] == self.EXPECTED_INSTALL
        assert config["psadt"]["uninstall"] == self.EXPECTED_UNINSTALL
        output = capsys.readouterr().out
        assert "psadt.install is set but will be ignored" in output
        assert "psadt.uninstall is set" not in output

    def test_override_uses_recipe_values(self):
        """Tests that override keeps both recipe commands untouched."""
        config = self._config(
            install="Custom-Install", uninstall="Custom-Uninstall", override=True
        )

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert config["psadt"]["install"] == "Custom-Install"
        assert config["psadt"]["uninstall"] == "Custom-Uninstall"

    def test_override_fills_missing_install(self):
        """Tests that override auto-fills install when only uninstall is set."""
        config = self._config(uninstall="Custom-Uninstall", override=True)

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert config["psadt"]["install"] == self.EXPECTED_INSTALL
        assert config["psadt"]["uninstall"] == "Custom-Uninstall"

    def test_override_fills_missing_uninstall(self):
        """Tests that override auto-fills uninstall when only install is set."""
        config = self._config(install="Custom-Install", override=True)

        _apply_msi_commands(config, self._metadata(), self.INSTALLER, self._logger())

        assert config["psadt"]["install"] == "Custom-Install"
        assert config["psadt"]["uninstall"] == self.EXPECTED_UNINSTALL

    def test_override_without_commands_raises(self):
        """Tests that override with neither command set raises ConfigError."""
        config = self._config(override=True)

        with pytest.raises(ConfigError, match="override_msi_commands"):
            _apply_msi_commands(
                config, self._metadata(), self.INSTALLER, self._logger()
            )

    def test_product_name_with_quote_is_escaped(self):
        """Tests that single quotes in ProductName are escaped for PowerShell."""
        config = self._config()

        _apply_msi_commands(
            config,
            self._metadata(product_name="O'Reilly Viewer"),
            self.INSTALLER,
            self._logger(),
        )

        assert "-Name 'O''Reilly Viewer'" in config["psadt"]["uninstall"]

    def test_empty_product_name_raises(self):
        """Tests that a missing ProductName fails uninstall auto-generation."""
        config = self._config()

        with pytest.raises(ConfigError, match="ProductName"):
            _apply_msi_commands(
                config, self._metadata(product_name=""), self.INSTALLER, self._logger()
            )

    def test_empty_product_name_allowed_with_override_uninstall(self):
        """Tests that override with a recipe uninstall skips the ProductName check."""
        config = self._config(uninstall="Custom-Uninstall", override=True)

        _apply_msi_commands(
            config, self._metadata(product_name=""), self.INSTALLER, self._logger()
        )

        assert config["psadt"]["uninstall"] == "Custom-Uninstall"
        assert config["psadt"]["install"] == self.EXPECTED_INSTALL
