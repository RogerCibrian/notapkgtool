"""
Tests for napt.build.packager module.

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

from napt.build.packager import (
    INTUNEWIN_GITHUB_API,
    _get_intunewin_tool,
    _verify_build_structure,
    create_intunewin,
    fetch_latest_intunewin_version,
)
from napt.exceptions import ConfigError, NetworkError, PackagingError

# All tests in this file are unit tests (fast, mocked)


def _make_build_dir(
    tmp_path: Path,
    app_id: str = "test-app",
    version: str = "1.0.0",
    detection: bool = False,
    requirements: bool = False,
) -> Path:
    """Create a valid build version dir with packagefiles/ subdir.

    Args:
        tmp_path: Pytest tmp_path fixture.
        app_id: App identifier used in the directory path.
        version: Version string used in the directory path.
        detection: If True, create a Detection.ps1 script in the version dir.
        requirements: If True, create a Requirements.ps1 script in the version dir.

    Returns:
        Path to the version directory (builds/{app_id}/{version}/).
    """
    version_dir = tmp_path / "builds" / app_id / version
    packagefiles = version_dir / "packagefiles"
    packagefiles.mkdir(parents=True)
    (packagefiles / "PSAppDeployToolkit").mkdir()
    (packagefiles / "Files").mkdir()
    (packagefiles / "Invoke-AppDeployToolkit.ps1").write_text("script")
    (packagefiles / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")
    if detection:
        (version_dir / f"{app_id}-Detection.ps1").write_text("detection script")
    if requirements:
        (version_dir / f"{app_id}-Requirements.ps1").write_text("requirements script")
    return version_dir


_DOWNLOAD_URL_PREFIX = (
    "https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool/raw"
)


class TestFetchLatestIntunewinVersion:
    """Tests for fetching latest IntuneWinAppUtil version from GitHub."""

    def test_fetch_latest_success_bare_tag(self, requests_mock):
        """Tests version extraction when tag has no v prefix."""
        requests_mock.get(INTUNEWIN_GITHUB_API, json={"tag_name": "1.8.6"})

        assert fetch_latest_intunewin_version() == "1.8.6"

    def test_fetch_latest_success_v_prefix(self, requests_mock):
        """Tests that v prefix is stripped from tag name."""
        requests_mock.get(INTUNEWIN_GITHUB_API, json={"tag_name": "v1.8.6"})

        assert fetch_latest_intunewin_version() == "1.8.6"

    def test_fetch_latest_api_error(self, requests_mock):
        """Tests NetworkError on GitHub API failure."""
        requests_mock.get(INTUNEWIN_GITHUB_API, status_code=500)

        with pytest.raises(NetworkError, match="Failed to fetch latest IntuneWinAppUtil"):
            fetch_latest_intunewin_version()

    def test_fetch_latest_invalid_tag(self, requests_mock):
        """Tests NetworkError when tag name cannot be parsed."""
        requests_mock.get(INTUNEWIN_GITHUB_API, json={"tag_name": "not-a-version"})

        with pytest.raises(NetworkError, match="Could not extract version"):
            fetch_latest_intunewin_version()


class TestGetIntunewinTool:
    """Tests for _get_intunewin_tool version resolution and caching."""

    def test_cache_hit_returns_path(self, tmp_path):
        """Tests that a cached tool is returned without downloading."""
        cache_dir = tmp_path / "tools"
        tool_path = cache_dir / "1.8.6" / "IntuneWinAppUtil.exe"
        tool_path.parent.mkdir(parents=True)
        tool_path.write_bytes(b"fake exe")

        result = _get_intunewin_tool(cache_dir, "1.8.6")

        assert result == tool_path

    @patch("napt.build.packager.fetch_latest_intunewin_version")
    def test_latest_resolves_via_api(self, mock_fetch, tmp_path, requests_mock):
        """Tests that 'latest' calls fetch_latest_intunewin_version."""
        mock_fetch.return_value = "1.8.6"
        cache_dir = tmp_path / "tools"

        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/v1.8.6/IntuneWinAppUtil.exe",
            content=b"fake exe",
        )

        _get_intunewin_tool(cache_dir, "latest")

        mock_fetch.assert_called_once()

    def test_v_prefix_stripped_from_release(self, tmp_path, requests_mock):
        """Tests that a user-specified v prefix is normalised."""
        cache_dir = tmp_path / "tools"
        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/v1.8.6/IntuneWinAppUtil.exe",
            content=b"fake exe",
        )

        result = _get_intunewin_tool(cache_dir, "v1.8.6")

        assert result == cache_dir / "1.8.6" / "IntuneWinAppUtil.exe"

    def test_download_uses_v_prefix_tag_first(self, tmp_path, requests_mock):
        """Tests that download tries v{version} before bare tag."""
        cache_dir = tmp_path / "tools"
        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/v1.8.6/IntuneWinAppUtil.exe",
            content=b"fake exe",
        )

        result = _get_intunewin_tool(cache_dir, "1.8.6")

        assert result.exists()
        assert result == cache_dir / "1.8.6" / "IntuneWinAppUtil.exe"

    def test_download_falls_back_to_bare_tag(self, tmp_path, requests_mock):
        """Tests fallback to bare tag when v-prefixed tag 404s."""
        cache_dir = tmp_path / "tools"
        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/v1.8.3/IntuneWinAppUtil.exe",
            status_code=404,
        )
        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/1.8.3/IntuneWinAppUtil.exe",
            content=b"fake exe",
        )

        result = _get_intunewin_tool(cache_dir, "1.8.3")

        assert result.exists()
        assert result == cache_dir / "1.8.3" / "IntuneWinAppUtil.exe"

    def test_both_tags_404_raises_network_error(self, tmp_path, requests_mock):
        """Tests NetworkError when both tag formats return 404."""
        cache_dir = tmp_path / "tools"
        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/v9.9.9/IntuneWinAppUtil.exe",
            status_code=404,
        )
        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/9.9.9/IntuneWinAppUtil.exe",
            status_code=404,
        )

        with pytest.raises(NetworkError, match="not found"):
            _get_intunewin_tool(cache_dir, "9.9.9")

    def test_download_cached_on_disk(self, tmp_path, requests_mock):
        """Tests downloaded tool is written to the versioned cache path."""
        cache_dir = tmp_path / "tools"
        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/v1.8.6/IntuneWinAppUtil.exe",
            content=b"fake exe content",
        )

        result = _get_intunewin_tool(cache_dir, "1.8.6")

        assert result.read_bytes() == b"fake exe content"
        assert result.parent == cache_dir / "1.8.6"


class TestVerifyBuildStructure:
    """Tests for build directory validation."""

    def test_verify_valid_structure(self, tmp_path):
        """Tests that a valid PSADT directory passes validation."""
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
        """Tests error when PSAppDeployToolkit directory is missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ConfigError, match="Missing.*PSAppDeployToolkit"):
            _verify_build_structure(build_dir)

    def test_verify_missing_files_raises(self, tmp_path):
        """Tests error when Files directory is missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ConfigError, match="Missing.*Files"):
            _verify_build_structure(build_dir)

    def test_verify_missing_script_raises(self, tmp_path):
        """Tests error when Invoke-AppDeployToolkit.ps1 is missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ConfigError, match="Missing.*Invoke-AppDeployToolkit.ps1"):
            _verify_build_structure(build_dir)


class TestCreateIntunewin:
    """Tests for .intunewin package creation."""

    @patch("napt.build.packager._get_intunewin_tool")
    @patch("napt.build.packager._execute_packaging")
    def test_create_intunewin_success(self, mock_execute, mock_get_tool, tmp_path):
        """Tests successful .intunewin creation with versioned output path."""
        build_dir = _make_build_dir(tmp_path)
        packages_dir = tmp_path / "packages"

        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        # Return a path within the versioned output dir
        intunewin_path = (
            packages_dir / "test-app" / "1.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )
        mock_execute.return_value = intunewin_path

        result = create_intunewin(build_dir, output_dir=packages_dir)

        assert result.app_id == "test-app"
        assert result.version == "1.0.0"
        assert result.status == "success"
        assert result.package_path == intunewin_path

    @patch("napt.build.packager._get_intunewin_tool")
    @patch("napt.build.packager._execute_packaging")
    def test_execute_packaging_called_with_packagefiles_dir(
        self, mock_execute, mock_get_tool, tmp_path
    ):
        """Tests that IntuneWinAppUtil is invoked on packagefiles/ not the version dir."""
        build_dir = _make_build_dir(tmp_path)
        packages_dir = tmp_path / "packages"

        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        mock_execute.return_value = (
            packages_dir / "test-app" / "1.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )

        create_intunewin(build_dir, output_dir=packages_dir)

        # Source dir passed to tool must be the packagefiles/ subdir
        call_args = mock_execute.call_args
        source_dir = call_args[0][1]
        assert source_dir == build_dir.resolve() / "packagefiles"

    @patch("napt.build.packager._get_intunewin_tool")
    @patch("napt.build.packager._execute_packaging")
    def test_create_intunewin_copies_detection_script(
        self, mock_execute, mock_get_tool, tmp_path
    ):
        """Tests detection script is copied into the package output directory."""
        build_dir = _make_build_dir(tmp_path, detection=True)
        packages_dir = tmp_path / "packages"

        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        mock_execute.return_value = (
            packages_dir / "test-app" / "1.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )

        create_intunewin(build_dir, output_dir=packages_dir)

        version_output_dir = (packages_dir / "test-app" / "1.0.0").resolve()
        assert (version_output_dir / "test-app-Detection.ps1").exists()

    @patch("napt.build.packager._get_intunewin_tool")
    @patch("napt.build.packager._execute_packaging")
    def test_create_intunewin_copies_requirements_script(
        self, mock_execute, mock_get_tool, tmp_path
    ):
        """Tests requirements script is copied into the package output directory."""
        build_dir = _make_build_dir(tmp_path, detection=True, requirements=True)
        packages_dir = tmp_path / "packages"

        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        mock_execute.return_value = (
            packages_dir / "test-app" / "1.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )

        create_intunewin(build_dir, output_dir=packages_dir)

        version_output_dir = (packages_dir / "test-app" / "1.0.0").resolve()
        assert (version_output_dir / "test-app-Requirements.ps1").exists()

    @patch("napt.build.packager._get_intunewin_tool")
    @patch("napt.build.packager._execute_packaging")
    def test_create_intunewin_removes_previous_version(
        self, mock_execute, mock_get_tool, tmp_path
    ):
        """Tests previous version directory is removed when new version is packaged."""
        build_dir = _make_build_dir(tmp_path, version="2.0.0")
        packages_dir = tmp_path / "packages"

        # Pre-existing old version dir
        old_version_dir = packages_dir / "test-app" / "1.0.0"
        old_version_dir.mkdir(parents=True)
        (old_version_dir / "Invoke-AppDeployToolkit.intunewin").write_bytes(b"old")

        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        mock_execute.return_value = (
            packages_dir / "test-app" / "2.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )

        create_intunewin(build_dir, output_dir=packages_dir)

        assert not old_version_dir.exists()
        assert (packages_dir / "test-app" / "2.0.0").resolve().exists()

    @patch("napt.build.packager._get_intunewin_tool")
    @patch("napt.build.packager._execute_packaging")
    def test_create_intunewin_same_version_no_removal(
        self, mock_execute, mock_get_tool, tmp_path
    ):
        """Tests that repackaging the same version does not remove the output dir."""
        build_dir = _make_build_dir(tmp_path, version="1.0.0")
        packages_dir = tmp_path / "packages"

        # Same version already exists
        existing_dir = packages_dir / "test-app" / "1.0.0"
        existing_dir.mkdir(parents=True)

        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        mock_execute.return_value = (
            packages_dir / "test-app" / "1.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )

        # Should not raise and should not remove the dir
        create_intunewin(build_dir, output_dir=packages_dir)
        assert existing_dir.resolve().exists()

    def test_create_intunewin_invalid_structure_raises(self, tmp_path):
        """Tests error when packagefiles directory has invalid PSADT structure."""
        build_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        (build_dir / "packagefiles").mkdir(parents=True)
        # packagefiles/ is empty — missing required PSADT files

        with pytest.raises(ConfigError, match="Invalid PSADT build directory"):
            create_intunewin(build_dir)

    def test_create_intunewin_missing_directory_raises(self, tmp_path):
        """Tests error when build directory does not exist."""
        build_dir = tmp_path / "nonexistent" / "test-app" / "1.0.0"

        with pytest.raises(PackagingError):
            create_intunewin(build_dir)

    @patch("napt.build.packager._get_intunewin_tool")
    @patch("napt.build.packager._execute_packaging")
    def test_create_intunewin_with_clean_source(
        self, mock_execute, mock_get_tool, tmp_path
    ):
        """Tests --clean-source removes the build version directory after packaging."""
        build_dir = _make_build_dir(tmp_path)
        packages_dir = tmp_path / "packages"

        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        mock_execute.return_value = (
            packages_dir / "test-app" / "1.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )

        result = create_intunewin(build_dir, output_dir=packages_dir, clean_source=True)

        assert not build_dir.exists()
        assert result.status == "success"

    @patch("napt.build.packager._get_intunewin_tool")
    @patch("napt.build.packager._execute_packaging")
    def test_tool_release_forwarded_to_get_tool(
        self, mock_execute, mock_get_tool, tmp_path
    ):
        """Tests that tool_release is forwarded to _get_intunewin_tool."""
        build_dir = _make_build_dir(tmp_path)
        packages_dir = tmp_path / "packages"

        mock_get_tool.return_value = Path("tool/IntuneWinAppUtil.exe")
        mock_execute.return_value = (
            packages_dir / "test-app" / "1.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )

        create_intunewin(build_dir, output_dir=packages_dir, tool_release="1.8.6")

        _, call_release = mock_get_tool.call_args[0]
        assert call_release == "1.8.6"
