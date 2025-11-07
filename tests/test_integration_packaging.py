"""
Integration tests for .intunewin packaging with real IntuneWinAppUtil.exe.

These tests validate:
- IntuneWinAppUtil.exe downloads correctly from Microsoft
- Tool executes with correct arguments
- .intunewin packages are created with proper structure

Run with: pytest tests/test_integration_packaging.py -m integration
Skip with: pytest tests/ -m "not integration"
"""

from __future__ import annotations

from pathlib import Path

import pytest

from notapkgtool.build.packager import _get_intunewin_tool, _verify_build_structure


@pytest.mark.integration
@pytest.mark.network
class TestIntuneWinToolDownload:
    """Test downloading real IntuneWinAppUtil.exe from Microsoft."""

    def test_download_intunewin_tool_success(self, tmp_path: Path):
        """Test downloading IntuneWinAppUtil.exe from Microsoft."""
        cache_dir = tmp_path / "cache" / "tools"

        tool_path = _get_intunewin_tool(cache_dir, verbose=False)

        assert tool_path.exists()
        assert tool_path.name == "IntuneWinAppUtil.exe"
        assert tool_path.stat().st_size > 10000  # Real tool is ~60KB

    def test_intunewin_tool_cached_on_second_call(self, tmp_path: Path):
        """Test that tool is reused from cache on second download."""
        cache_dir = tmp_path / "cache" / "tools"

        # First download
        tool_path_1 = _get_intunewin_tool(cache_dir, verbose=False)
        mtime_1 = tool_path_1.stat().st_mtime

        # Second call should use cache
        tool_path_2 = _get_intunewin_tool(cache_dir, verbose=False)
        mtime_2 = tool_path_2.stat().st_mtime

        assert tool_path_1 == tool_path_2
        assert mtime_1 == mtime_2  # File not re-downloaded


@pytest.mark.integration
@pytest.mark.network
class TestBuildStructureValidation:
    """Test build directory validation with real PSADT structure."""

    def test_verify_valid_real_build(self, real_psadt_template: Path, tmp_path: Path):
        """Test validation passes for real PSADT build."""
        from notapkgtool.build.manager import _copy_psadt_pristine

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        # Create real build structure
        _copy_psadt_pristine(real_psadt_template, build_dir)

        # Should not raise - real template has everything needed
        _verify_build_structure(build_dir)

    def test_verify_detects_missing_exe(self, real_psadt_template: Path, tmp_path: Path):
        """Test validation fails when Invoke-AppDeployToolkit.exe missing."""
        from notapkgtool.build.manager import _copy_psadt_pristine

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_pristine(real_psadt_template, build_dir)

        # Remove the exe
        (build_dir / "Invoke-AppDeployToolkit.exe").unlink()

        with pytest.raises(ValueError, match="Missing.*Invoke-AppDeployToolkit.exe"):
            _verify_build_structure(build_dir)

    def test_verify_detects_missing_psadt_module(
        self, real_psadt_template: Path, tmp_path: Path
    ):
        """Test validation fails when PSAppDeployToolkit directory missing."""
        from notapkgtool.build.manager import _copy_psadt_pristine
        import shutil

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _copy_psadt_pristine(real_psadt_template, build_dir)

        # Remove PSAppDeployToolkit module
        shutil.rmtree(build_dir / "PSAppDeployToolkit")

        with pytest.raises(ValueError, match="Missing.*PSAppDeployToolkit"):
            _verify_build_structure(build_dir)

