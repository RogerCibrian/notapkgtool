"""
Tests for napt.psadt.release module.

Tests PSADT release management including:
- Fetching latest version from GitHub
- Downloading and caching releases
- Version resolution
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from napt.psadt import (
    fetch_latest_psadt_version,
    get_psadt_release,
    is_psadt_cached,
)


class TestFetchLatestPSADTVersion:
    """Tests for fetching latest PSADT version from GitHub."""

    def test_fetch_latest_success(self, requests_mock):
        """Test successful fetch of latest version."""
        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/latest",
            json={"tag_name": "4.1.7"},
        )

        version = fetch_latest_psadt_version()

        assert version == "4.1.7"

    def test_fetch_latest_with_v_prefix(self, requests_mock):
        """Test version extraction with 'v' prefix."""
        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/latest",
            json={"tag_name": "v4.1.7"},
        )

        version = fetch_latest_psadt_version()

        assert version == "4.1.7"

    def test_fetch_latest_api_error(self, requests_mock):
        """Test handling of GitHub API errors."""
        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/latest",
            status_code=404,
        )

        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="Failed to fetch latest PSADT release"):
            fetch_latest_psadt_version()

    def test_fetch_latest_missing_tag(self, requests_mock):
        """Test handling of missing tag_name in response."""
        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/latest",
            json={},
        )

        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="missing 'tag_name'"):
            fetch_latest_psadt_version()

    def test_fetch_latest_invalid_tag_format(self, requests_mock):
        """Test handling of invalid tag format."""
        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/latest",
            json={"tag_name": "invalid-tag"},
        )

        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="Could not extract version from tag"):
            fetch_latest_psadt_version()


class TestIsPSADTCached:
    """Tests for checking if PSADT is cached."""

    def test_is_cached_true(self, tmp_path):
        """Test detection of cached PSADT."""
        cache_dir = tmp_path / "cache"
        version_dir = cache_dir / "4.1.7"
        psadt_dir = version_dir / "PSAppDeployToolkit"
        manifest = psadt_dir / "PSAppDeployToolkit.psd1"

        # Create structure
        manifest.parent.mkdir(parents=True)
        manifest.write_text("# manifest")

        assert is_psadt_cached("4.1.7", cache_dir) is True

    def test_is_cached_false_no_directory(self, tmp_path):
        """Test when cache directory doesn't exist."""
        cache_dir = tmp_path / "cache"

        assert is_psadt_cached("4.1.7", cache_dir) is False

    def test_is_cached_false_no_manifest(self, tmp_path):
        """Test when directory exists but manifest missing."""
        cache_dir = tmp_path / "cache"
        version_dir = cache_dir / "4.1.7"
        psadt_dir = version_dir / "PSAppDeployToolkit"
        psadt_dir.mkdir(parents=True)

        assert is_psadt_cached("4.1.7", cache_dir) is False


class TestGetPSADTRelease:
    """Tests for downloading and caching PSADT releases."""

    def test_get_release_already_cached(self, tmp_path):
        """Test using already cached release."""
        cache_dir = tmp_path / "cache"
        version_dir = cache_dir / "4.1.7"
        psadt_dir = version_dir / "PSAppDeployToolkit"
        manifest = psadt_dir / "PSAppDeployToolkit.psd1"

        # Create cached structure
        manifest.parent.mkdir(parents=True)
        manifest.write_text("# manifest")

        result = get_psadt_release("4.1.7", cache_dir)

        assert result == version_dir

    @patch("napt.psadt.release.fetch_latest_psadt_version")
    def test_get_release_resolves_latest(self, mock_fetch, tmp_path):
        """Test that 'latest' is resolved to actual version."""
        cache_dir = tmp_path / "cache"
        mock_fetch.return_value = "4.1.7"

        # Create cached structure so we don't try to download
        version_dir = cache_dir / "4.1.7"
        psadt_dir = version_dir / "PSAppDeployToolkit"
        manifest = psadt_dir / "PSAppDeployToolkit.psd1"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("# manifest")

        result = get_psadt_release("latest", cache_dir)

        assert result == version_dir
        mock_fetch.assert_called_once()

    def test_get_release_download_and_extract(self, tmp_path, requests_mock):
        """Test downloading and extracting a release."""
        import io
        import zipfile

        cache_dir = tmp_path / "cache"

        # Mock GitHub release API
        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/tags/4.1.7",
            json={
                "tag_name": "4.1.7",
                "assets": [
                    {
                        "name": "PSAppDeployToolkit_v4.1.7.zip",
                        "browser_download_url": "https://github.com/test/download.zip",
                    }
                ],
            },
        )

        # Create a minimal zip file with PSADT structure
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("PSAppDeployToolkit/PSAppDeployToolkit.psd1", "# manifest")
            zf.writestr("Invoke-AppDeployToolkit.ps1", "# script")

        # Mock zip download
        requests_mock.get(
            "https://github.com/test/download.zip", content=zip_buffer.getvalue()
        )

        result = get_psadt_release("4.1.7", cache_dir)

        assert result == cache_dir / "4.1.7"
        assert (result / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").exists()

    def test_get_release_no_assets(self, tmp_path, requests_mock):
        """Test handling of release with no assets."""
        cache_dir = tmp_path / "cache"

        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/tags/4.1.7",
            json={"tag_name": "4.1.7", "assets": []},
        )

        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="No .zip asset found"):
            get_psadt_release("4.1.7", cache_dir)

    def test_get_release_api_404(self, tmp_path, requests_mock):
        """Test handling of missing release (404)."""
        cache_dir = tmp_path / "cache"

        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/tags/9.9.9",
            status_code=404,
        )

        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="Failed to fetch PSADT release"):
            get_psadt_release("9.9.9", cache_dir)
