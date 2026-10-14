"""Tests for napt.build.scripts: the detection and requirements scripts."""

from __future__ import annotations

from pathlib import Path

import pytest

from napt.build.installer import InstallerInfo
from napt.build.scripts import (
    sanitize_filename,
    write_detection_script,
    write_requirements_script,
)
from napt.versioning.msi import MSIMetadata
from napt.versioning.msix import MSIXMetadata


class TestSanitizeFilename:
    """Tests for the filename-safe form of an app name."""

    def test_basic_sanitization(self):
        """Tests that spaces become hyphens."""
        assert sanitize_filename("Google Chrome", "app") == "Google-Chrome"
        assert sanitize_filename("My App v2.0", "app") == "My-App-v2.0"

    def test_removes_invalid_chars(self):
        """Tests that characters Windows forbids in filenames are dropped."""
        assert sanitize_filename("Test<>App", "app") == "TestApp"
        assert sanitize_filename('App:Name|"Test"', "app") == "AppNameTest"

    def test_collapses_hyphens_and_trims_dots(self):
        """Tests that runs of hyphens collapse and edge dots and hyphens go."""
        assert sanitize_filename("A  --  B.", "app") == "A-B"

    def test_fallback_to_app_id(self):
        """Tests that a name with nothing usable falls back to the recipe id."""
        assert sanitize_filename("  ", "my-app") == "my-app"
        assert sanitize_filename("", "test") == "test"


def _info(
    tmp_path: Path, name: str, app_name: str = "Google Chrome", msi=None, msix=None
) -> InstallerInfo:
    return InstallerInfo(
        path=tmp_path / name,
        sha256="a" * 64,
        version="131.0.0",
        app_name=app_name,
        architecture="x64",
        msi=msi,
        msix=msix,
    )


def _config(make_config, **overrides):
    return make_config({"id": "napt-chrome", "name": "Google Chrome", **overrides})


class TestWriteScripts:
    """Tests for the scripts written beside the packagefiles folder."""

    def test_detection_script_is_named_after_the_app_and_version(
        self, tmp_path, make_config
    ):
        """Tests that the script lands as a sibling of packagefiles/."""
        build_dir = tmp_path / "builds" / "napt-chrome" / "131.0.0" / "packagefiles"
        build_dir.mkdir(parents=True)

        path = write_detection_script(
            _info(tmp_path, "chrome.exe"), _config(make_config), build_dir
        )

        assert path == build_dir.parent / "Google-Chrome_131.0.0-Detection.ps1"
        assert path.is_file()

    def test_requirements_script_is_named_after_the_app_and_version(
        self, tmp_path, make_config
    ):
        """Tests that the requirements script sits beside the detection script."""
        build_dir = tmp_path / "builds" / "napt-chrome" / "131.0.0" / "packagefiles"
        build_dir.mkdir(parents=True)

        path = write_requirements_script(
            _info(tmp_path, "chrome.exe"), _config(make_config), build_dir
        )

        assert path == build_dir.parent / "Google-Chrome_131.0.0-Requirements.ps1"
        assert path.is_file()

    def test_name_with_nothing_usable_falls_back_to_the_recipe_id(
        self, tmp_path, make_config
    ):
        """Tests that an unprintable app name still yields a usable filename."""
        build_dir = tmp_path / "builds" / "napt-chrome" / "131.0.0" / "packagefiles"
        build_dir.mkdir(parents=True)

        path = write_detection_script(
            _info(tmp_path, "chrome.exe", app_name="<>"),
            _config(make_config),
            build_dir,
        )

        assert path.name == "napt-chrome_131.0.0-Detection.ps1"

    def test_msi_uses_the_strict_registry_match(self, tmp_path, make_config):
        """Tests that an MSI build's script only matches Windows Installer entries."""
        build_dir = tmp_path / "builds" / "napt-chrome" / "131.0.0" / "packagefiles"
        build_dir.mkdir(parents=True)
        info = _info(
            tmp_path,
            "chrome.msi",
            msi=MSIMetadata(
                product_name="Google Chrome",
                product_version="131.0.0",
                architecture="x64",
            ),
        )

        path = write_detection_script(info, _config(make_config), build_dir)

        script = path.read_text(encoding="utf-8-sig")
        assert "$IsMSIInstaller = $True" in script
        assert '$ExpectedArchitecture = "x64"' in script

    def test_msix_uses_the_appx_scripts(self, tmp_path, make_config):
        """Tests that an MSIX build queries the package identity, not the registry."""
        build_dir = tmp_path / "builds" / "napt-chrome" / "131.0.0" / "packagefiles"
        build_dir.mkdir(parents=True)
        info = _info(
            tmp_path,
            "chrome.msix",
            msix=MSIXMetadata(
                display_name="Google Chrome",
                version="131.0.0",
                architecture="x64",
                identity_name="Google.Chrome",
            ),
        )

        detection = write_detection_script(info, _config(make_config), build_dir)
        requirements = write_requirements_script(info, _config(make_config), build_dir)

        assert "Google.Chrome" in detection.read_text(encoding="utf-8-sig")
        assert "Get-AppxProvisionedPackage" in requirements.read_text(
            encoding="utf-8-sig"
        )

    def test_wildcard_in_name_switches_to_like_matching(self, tmp_path, make_config):
        """Tests that a * in the display name keeps the -like operator."""
        build_dir = tmp_path / "builds" / "napt-chrome" / "131.0.0" / "packagefiles"
        build_dir.mkdir(parents=True)

        path = write_detection_script(
            _info(tmp_path, "chrome.exe", app_name="Google Chrome*"),
            _config(make_config),
            build_dir,
        )

        assert "-like $AppName" in path.read_text(encoding="utf-8-sig")

    @pytest.mark.parametrize("exact_match", [True, False])
    def test_exact_match_setting_reaches_the_script(
        self, tmp_path, make_config, exact_match
    ):
        """Tests that intune.detection.exact_match is written into the script."""
        build_dir = tmp_path / "builds" / "napt-chrome" / "131.0.0" / "packagefiles"
        build_dir.mkdir(parents=True)
        config = _config(
            make_config, intune={"detection": {"exact_match": exact_match}}
        )

        path = write_detection_script(_info(tmp_path, "chrome.exe"), config, build_dir)

        expected = "$True" if exact_match else "$False"
        assert f"$ExactMatch = {expected}" in path.read_text(encoding="utf-8-sig")
