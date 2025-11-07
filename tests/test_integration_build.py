"""
Integration tests for PSADT build functionality with real Template_v4.

These tests download and use actual PSADT Template_v4 from GitHub to validate:
- Template structure matches v4 expectations
- Branding applies to correct directories
- Build directory contains all required files
- Real template files are copied correctly

Run with: pytest tests/test_integration_build.py -m integration
Skip with: pytest tests/ -m "not integration"
"""

from __future__ import annotations

from pathlib import Path

import pytest

from notapkgtool.build.manager import (
    _apply_branding,
    _copy_installer,
    _copy_psadt_pristine,
)


@pytest.mark.integration
@pytest.mark.network
class TestRealPSADTStructure:
    """Validate real PSADT Template_v4 structure."""

    def test_real_template_has_v4_structure(self, real_psadt_template: Path):
        """Test that real PSADT Template_v4 has expected structure."""
        # Root level files
        assert (real_psadt_template / "Invoke-AppDeployToolkit.exe").exists()
        assert (real_psadt_template / "Invoke-AppDeployToolkit.ps1").exists()

        # Root level directories (v4 structure)
        assert (real_psadt_template / "Assets").is_dir()
        assert (real_psadt_template / "Config").is_dir()
        assert (real_psadt_template / "Files").is_dir()
        assert (real_psadt_template / "Strings").is_dir()
        assert (real_psadt_template / "SupportFiles").is_dir()
        assert (real_psadt_template / "PSAppDeployToolkit").is_dir()
        assert (real_psadt_template / "PSAppDeployToolkit.Extensions").is_dir()

    def test_real_template_has_module_files(self, real_psadt_template: Path):
        """Test that PSAppDeployToolkit module has required files."""
        module_dir = real_psadt_template / "PSAppDeployToolkit"

        assert (module_dir / "PSAppDeployToolkit.psd1").exists()
        assert (module_dir / "PSAppDeployToolkit.psm1").exists()
        assert (module_dir / "Assets").is_dir()
        assert (module_dir / "lib").is_dir()

    def test_real_template_has_default_assets(self, real_psadt_template: Path):
        """Test that template includes default assets."""
        assets_dir = real_psadt_template / "Assets"

        # Default PSADT assets
        assert (assets_dir / "AppIcon.png").exists()
        assert (assets_dir / "Banner.Classic.png").exists()


@pytest.mark.integration
@pytest.mark.network
class TestCopyPSADTWithRealTemplate:
    """Test copying real PSADT template to build directory."""

    def test_copy_real_template_preserves_structure(
        self, real_psadt_template: Path, tmp_path: Path
    ):
        """Test that copying real template preserves complete v4 structure."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_pristine(real_psadt_template, build_dir)

        # Verify all root files copied
        assert (build_dir / "Invoke-AppDeployToolkit.exe").exists()
        assert (build_dir / "Invoke-AppDeployToolkit.ps1").exists()

        # Verify all root directories copied
        assert (build_dir / "Assets").is_dir()
        assert (build_dir / "Config").is_dir()
        assert (build_dir / "Files").is_dir()
        assert (build_dir / "Strings").is_dir()
        assert (build_dir / "SupportFiles").is_dir()
        assert (build_dir / "PSAppDeployToolkit").is_dir()
        assert (build_dir / "PSAppDeployToolkit.Extensions").is_dir()

    def test_copy_real_template_includes_module(
        self, real_psadt_template: Path, tmp_path: Path
    ):
        """Test that PSAppDeployToolkit module is copied with all files."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_pristine(real_psadt_template, build_dir)

        module_dir = build_dir / "PSAppDeployToolkit"
        assert (module_dir / "PSAppDeployToolkit.psd1").exists()
        assert (module_dir / "PSAppDeployToolkit.psm1").exists()
        assert (module_dir / "lib").is_dir()
        assert (module_dir / "Assets").is_dir()

    def test_copy_real_template_files_directory_exists(
        self, real_psadt_template: Path, tmp_path: Path
    ):
        """Test that Files directory is ready for installer."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_pristine(real_psadt_template, build_dir)

        files_dir = build_dir / "Files"
        assert files_dir.exists()
        assert files_dir.is_dir()


@pytest.mark.integration
@pytest.mark.network
class TestBrandingWithRealTemplate:
    """Test branding application on real PSADT v4 structure."""

    def test_branding_applies_to_root_assets(
        self, real_psadt_template: Path, tmp_path: Path, fake_brand_pack
    ):
        """Test that branding applies to root Assets/ directory (v4)."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        # Copy real template
        _copy_psadt_pristine(real_psadt_template, build_dir)

        brand_dir, config = fake_brand_pack

        # Apply branding
        _apply_branding(config, build_dir)

        # Verify branding in ROOT Assets directory (v4 structure)
        root_assets = build_dir / "Assets"
        assert (root_assets / "AppIcon.png").exists()
        assert (root_assets / "Banner.Classic.png").exists()

        # Verify custom branding data was applied
        assert (root_assets / "AppIcon.png").read_bytes() == b"custom icon data"
        assert (
            root_assets / "Banner.Classic.png"
        ).read_bytes() == b"custom banner data"

    def test_branding_preserves_filename(
        self, real_psadt_template: Path, tmp_path: Path, fake_brand_pack
    ):
        """Test that Banner.Classic.png stays Banner.Classic.png (not Banner.png)."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_pristine(real_psadt_template, build_dir)
        brand_dir, config = fake_brand_pack

        _apply_branding(config, build_dir)

        # Verify exact filename (regression test for .with_suffix() bug)
        assert (build_dir / "Assets" / "Banner.Classic.png").exists()
        assert not (build_dir / "Assets" / "Banner.png").exists()


@pytest.mark.integration
@pytest.mark.network
class TestInstallerCopyWithRealTemplate:
    """Test installer copying into real template structure."""

    def test_installer_copies_to_files_directory(
        self, real_psadt_template: Path, tmp_path: Path
    ):
        """Test that installer is copied to Files/ directory."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        # Copy real template
        _copy_psadt_pristine(real_psadt_template, build_dir)

        # Create fake installer
        installer = tmp_path / "app.msi"
        installer.write_bytes(b"fake msi installer content")

        # Copy installer
        _copy_installer(installer, build_dir)

        # Verify installer in Files/
        dest = build_dir / "Files" / "app.msi"
        assert dest.exists()
        assert dest.read_bytes() == b"fake msi installer content"

    def test_files_directory_structure_preserved(
        self, real_psadt_template: Path, tmp_path: Path
    ):
        """Test that Files/ directory from template is preserved."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_pristine(real_psadt_template, build_dir)

        files_dir = build_dir / "Files"
        assert files_dir.is_dir()

        # Template may include a placeholder file
        # Just verify the directory is usable
        installer = tmp_path / "test.exe"
        installer.write_bytes(b"test")
        _copy_installer(installer, build_dir)

        assert (files_dir / "test.exe").exists()
