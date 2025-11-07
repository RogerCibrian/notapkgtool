"""
Tests for notapkgtool.build.packager module.

Tests .intunewin package creation including:
- Build structure validation
- IntuneWinAppUtil.exe handling
- Package creation

These are UNIT tests using mocked data for fast execution.
For integration tests with real IntuneWinAppUtil.exe, see test_integration_packaging.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from notapkgtool.build.packager import (
    _verify_build_structure,
    create_intunewin,
)

# All tests in this file are unit tests (fast, mocked)
pytestmark = pytest.mark.unit


class TestVerifyBuildStructure:
    """Tests for build directory validation."""

    def test_verify_valid_structure(self, tmp_path):
        """Test verification of valid PSADT build."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        # Create required structure
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        # Should not raise
        _verify_build_structure(build_dir)

    def test_verify_missing_psadt_raises(self, tmp_path):
        """Test error when PSAppDeployToolkit directory missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ValueError, match="Missing.*PSAppDeployToolkit"):
            _verify_build_structure(build_dir)

    def test_verify_missing_files_raises(self, tmp_path):
        """Test error when Files directory missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ValueError, match="Missing.*Files"):
            _verify_build_structure(build_dir)

    def test_verify_missing_script_raises(self, tmp_path):
        """Test error when Invoke-AppDeployToolkit.ps1 missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ValueError, match="Missing.*Invoke-AppDeployToolkit.ps1"):
            _verify_build_structure(build_dir)


class TestCreateIntunewin:
    """Tests for .intunewin package creation."""

    @patch("notapkgtool.build.packager._get_intunewin_tool")
    @patch("notapkgtool.build.packager._execute_packaging")
    def test_create_intunewin_success(self, mock_execute, mock_get_tool, tmp_path):
        """Test successful .intunewin creation."""
        # Create valid build structure
        build_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        build_dir.mkdir(parents=True)
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        # Mock tool and packaging
        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        package_path = tmp_path / "packages" / "test-app" / "test-app-1.0.0.intunewin"
        package_path.parent.mkdir(parents=True)
        package_path.write_bytes(b"intunewin")
        mock_execute.return_value = package_path

        result = create_intunewin(build_dir)

        assert result["app_id"] == "test-app"
        assert result["version"] == "1.0.0"
        assert result["status"] == "success"
        assert result["package_path"] == package_path

    def test_create_intunewin_invalid_structure_raises(self, tmp_path):
        """Test error when build directory is invalid."""
        build_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        build_dir.mkdir(parents=True)

        with pytest.raises(ValueError, match="Invalid PSADT build directory"):
            create_intunewin(build_dir)

    def test_create_intunewin_missing_directory_raises(self, tmp_path):
        """Test error when build directory doesn't exist."""
        build_dir = tmp_path / "nonexistent" / "test-app" / "1.0.0"

        with pytest.raises(FileNotFoundError):
            create_intunewin(build_dir)

    @patch("notapkgtool.build.packager._get_intunewin_tool")
    @patch("notapkgtool.build.packager._execute_packaging")
    def test_create_intunewin_with_clean_source(
        self, mock_execute, mock_get_tool, tmp_path
    ):
        """Test --clean-source option removes build directory."""
        # Create valid build structure
        build_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        build_dir.mkdir(parents=True)
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        # Mock packaging
        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        package_path = tmp_path / "packages" / "test-app" / "test-app-1.0.0.intunewin"
        package_path.parent.mkdir(parents=True)
        package_path.write_bytes(b"intunewin")
        mock_execute.return_value = package_path

        result = create_intunewin(build_dir, clean_source=True)

        # Build directory should be removed
        assert not build_dir.exists()
        assert result["status"] == "success"
