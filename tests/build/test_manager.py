"""Tests for napt.build.manager: the order build_package does things in."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from napt.build.manager import build_package
from napt.exceptions import ConfigError
from napt.versioning.msi import MSIMetadata

TEMPLATE = """$adtSession = @{
    AppName = ''
    AppVersion = ''
}

function Install-ADTDeployment {
    ## <Perform Installation tasks here>
}

function Uninstall-ADTDeployment {
    ## <Perform Uninstallation tasks here>
}
"""


@pytest.fixture
def psadt(fake_psadt_template):
    """The fake PSADT cache with a template the generator can fill."""
    (fake_psadt_template / "Invoke-AppDeployToolkit.ps1").write_text(
        TEMPLATE, encoding="utf-8"
    )
    return fake_psadt_template


def _save_installer(tmp_path: Path, version: str, name: str) -> Path:
    version_dir = tmp_path / "downloads" / "napt-app" / version
    version_dir.mkdir(parents=True)
    installer = version_dir / name
    installer.write_bytes(f"{name} {version}".encode())
    return installer


def _config(make_config, tmp_path, **overrides):
    base = {
        "id": "napt-app",
        "name": "Test App",
        "directories": {
            "discover": str(tmp_path / "downloads"),
            "build": str(tmp_path / "builds"),
            "state": str(tmp_path / "state"),
            "icons": str(tmp_path / "icons"),
        },
        # The icon step is covered in test_icons; skip it here.
        "intune": {"logo_path": str(tmp_path / "logo.png")},
        "psadt": {"app_vars": {"AppName": "Test App"}},
    }
    from napt.config.loader import _deep_merge_dicts

    return make_config(_deep_merge_dicts(base, overrides))


def _build(config, psadt, tmp_path):
    """Runs build_package with the config and PSADT cache given."""
    with (
        patch("napt.build.manager.load_effective_config", return_value=config),
        patch("napt.build.manager.get_psadt_release", return_value=psadt) as psadt_mock,
    ):
        result = build_package(tmp_path / "recipe.yaml")
    return result, psadt_mock


class TestBuildPackage:
    """Tests for the build sequence as a whole."""

    def test_exe_build_writes_scripts_and_manifest(self, make_config, psadt, tmp_path):
        """Tests that an EXE build produces the package tree, both scripts, and
        a manifest that names them."""
        _save_installer(tmp_path, "26.02", "7z2602-x64.exe")
        config = _config(
            make_config,
            tmp_path,
            psadt={"install": "Start-ADTProcess", "uninstall": "Remove-It"},
            intune={"detection": {"display_name": "7-Zip", "architecture": "x64"}},
        )

        result, _ = _build(config, psadt, tmp_path)

        version_dir = tmp_path / "builds" / "napt-app" / "26.02"
        assert result.build_dir == version_dir / "packagefiles"
        assert result.version == "26.02"
        assert result.psadt_version == "4.1.7"
        assert result.build_types == "both"
        invoke = (
            version_dir / "packagefiles" / "Invoke-AppDeployToolkit.ps1"
        ).read_text(encoding="utf-8-sig")
        assert "Start-ADTProcess" in invoke
        assert "AppArch = 'x64'" in invoke
        assert (version_dir / "packagefiles" / "Files" / "7z2602-x64.exe").is_file()
        assert result.detection_script_path == version_dir / "7-Zip_26.02-Detection.ps1"
        assert (
            result.requirements_script_path
            == version_dir / "7-Zip_26.02-Requirements.ps1"
        )
        manifest = json.loads(
            (version_dir / "build-manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["detection_script_path"] == "7-Zip_26.02-Detection.ps1"
        assert manifest["architecture"] == "x64"
        assert manifest["installer_sha256"]

    def test_app_only_skips_the_requirements_script(self, make_config, psadt, tmp_path):
        """Tests that build_types app_only writes detection alone."""
        _save_installer(tmp_path, "26.02", "7z2602-x64.exe")
        config = _config(
            make_config,
            tmp_path,
            psadt={"install": "Start-ADTProcess", "uninstall": "Remove-It"},
            intune={
                "build_types": "app_only",
                "detection": {"display_name": "7-Zip", "architecture": "x64"},
            },
        )

        result, _ = _build(config, psadt, tmp_path)

        assert result.requirements_script_path is None
        manifest = json.loads(
            (result.build_dir.parent / "build-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert "requirements_script_path" not in manifest

    def test_incomplete_exe_recipe_fails_before_touching_the_build(
        self, make_config, psadt, tmp_path
    ):
        """Tests that a recipe check failure leaves that version's existing
        build folder in place and fetches no PSADT release."""
        _save_installer(tmp_path, "26.02", "7z2602-x64.exe")
        previous = tmp_path / "builds" / "napt-app" / "26.02" / "keep.txt"
        previous.parent.mkdir(parents=True)
        previous.write_text("previous build")
        config = _config(
            make_config,
            tmp_path,
            psadt={"install": "Start-ADTProcess", "uninstall": "Remove-It"},
            intune={"detection": {"architecture": "x64"}},
        )

        with (
            patch("napt.build.manager.load_effective_config", return_value=config),
            patch(
                "napt.build.manager.get_psadt_release",
                side_effect=AssertionError("PSADT was fetched"),
            ),
            pytest.raises(ConfigError, match="display_name is required"),
        ):
            build_package(tmp_path / "recipe.yaml")

        assert previous.read_text() == "previous build"

    def test_msi_metadata_is_read_once_per_build(self, make_config, psadt, tmp_path):
        """Tests that one build launches one metadata read, not one per step."""
        _save_installer(tmp_path, "26.02.00.0", "7z2602-x64.msi")
        config = _config(make_config, tmp_path)
        metadata = MSIMetadata(
            product_name="7-Zip", product_version="26.02.00.0", architecture="x64"
        )

        with patch(
            "napt.build.installer.extract_msi_metadata", return_value=metadata
        ) as extract:
            result, _ = _build(config, psadt, tmp_path)

        assert extract.call_count == 1
        invoke = (result.build_dir / "Invoke-AppDeployToolkit.ps1").read_text(
            encoding="utf-8-sig"
        )
        assert (
            "Start-ADTMsiProcess -Action Install -FilePath '7z2602-x64.msi'" in invoke
        )
        assert result.detection_script_path.name == "7-Zip_26.02.00.0-Detection.ps1"

    def test_ignored_recipe_fields_warn_once_per_build(
        self, make_config, psadt, tmp_path, capsys
    ):
        """Tests that a field an MSI build ignores draws one warning, not one
        per generated script."""
        _save_installer(tmp_path, "26.02.00.0", "7z2602-x64.msi")
        config = _config(
            make_config, tmp_path, intune={"detection": {"display_name": "Other"}}
        )
        metadata = MSIMetadata(
            product_name="7-Zip", product_version="26.02.00.0", architecture="x64"
        )

        with patch("napt.build.installer.extract_msi_metadata", return_value=metadata):
            _build(config, psadt, tmp_path)

        out = capsys.readouterr().out
        assert (
            out.count("intune.detection.display_name is set but will be ignored") == 1
        )
