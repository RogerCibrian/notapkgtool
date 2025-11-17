"""
Tests for notapkgtool.discovery module.

Tests discovery strategies including:
- Strategy registry
- HTTP static strategy
- Version extraction from downloaded files
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import requests_mock

from notapkgtool.discovery.api_github import ApiGithubStrategy
from notapkgtool.discovery.api_json import ApiJsonStrategy
from notapkgtool.discovery.base import get_strategy, register_strategy
from notapkgtool.discovery.url_download import UrlDownloadStrategy
from notapkgtool.exceptions import ConfigError, NetworkError
from notapkgtool.versioning import DiscoveredVersion


class TestStrategyRegistry:
    """Tests for discovery strategy registration and lookup."""

    def test_get_url_download_strategy(self):
        """Test that url_download strategy can be retrieved."""
        strategy = get_strategy("url_download")
        assert isinstance(strategy, UrlDownloadStrategy)

    def test_get_api_github_strategy(self):
        """Test that api_github strategy can be retrieved."""
        strategy = get_strategy("api_github")
        assert isinstance(strategy, ApiGithubStrategy)

    def test_get_unknown_strategy_raises(self):
        """Test that unknown strategy name raises ValueError."""
        from notapkgtool.exceptions import ConfigError

        with pytest.raises(ConfigError, match="Unknown discovery strategy"):
            get_strategy("nonexistent_strategy")

    def test_register_custom_strategy(self):
        """Test registering a custom strategy."""

        class CustomStrategy:
            def discover_version(self, app_config, output_dir):
                return (
                    DiscoveredVersion(version="1.0.0", source="custom"),
                    Path("/fake/path"),
                    "fakehash",
                    {},  # HTTP headers
                )

        register_strategy("custom_test", CustomStrategy)
        strategy = get_strategy("custom_test")
        assert isinstance(strategy, CustomStrategy)


class TestUrlDownloadStrategy:
    """Tests for URL download strategy."""

    def test_discover_version_with_msi(self, tmp_test_dir):
        """Test discovering version from MSI file."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            }
        }

        strategy = UrlDownloadStrategy()

        # Mock the download and MSI extraction
        fake_msi_content = b"fake MSI content"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_msi_content,
                headers={"Content-Length": str(len(fake_msi_content))},
            )

            with patch(
                "notapkgtool.discovery.url_download.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="1.2.3", source="msi"
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    app_config, tmp_test_dir
                )

        assert discovered.version == "1.2.3"
        assert discovered.source == "msi"
        assert file_path.exists()
        assert file_path.name == "installer.msi"
        assert isinstance(sha256, str)
        assert len(sha256) == 64  # SHA-256 hex length

    def test_discover_version_missing_url_raises(self, tmp_test_dir):
        """Test that missing URL raises ValueError."""
        app_config = {
            "source": {
                "version": {"type": "msi"},
            }
        }

        strategy = UrlDownloadStrategy()

        from notapkgtool.exceptions import ConfigError

        with pytest.raises(ConfigError, match="requires 'source.url'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_missing_version_type_raises(self, tmp_test_dir):
        """Test that missing version type raises ValueError."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
            }
        }

        strategy = UrlDownloadStrategy()

        from notapkgtool.exceptions import ConfigError

        with pytest.raises(ConfigError, match="requires 'source.version.type'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_unsupported_type_raises(self, tmp_test_dir):
        """Test that unsupported version type raises ValueError."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "unsupported_type"},
            }
        }

        strategy = UrlDownloadStrategy()

        fake_content = b"fake content"
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_content,
                headers={"Content-Length": str(len(fake_content))},
            )

            with pytest.raises(ConfigError, match="Unsupported version type"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_download_failure_raises(self, tmp_test_dir):
        """Test that download failures raise NetworkError."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            }
        }

        strategy = UrlDownloadStrategy()

        with requests_mock.Mocker() as m:
            m.get("https://example.com/installer.msi", status_code=404)

            from notapkgtool.exceptions import NetworkError

            with pytest.raises(NetworkError, match="download failed"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_extraction_failure_raises(self, tmp_test_dir):
        """Test that version extraction failures raise NetworkError."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            }
        }

        strategy = UrlDownloadStrategy()

        fake_content = b"not a real MSI"
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_content,
                headers={"Content-Length": str(len(fake_content))},
            )

            with patch(
                "notapkgtool.discovery.url_download.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.side_effect = NetworkError("Invalid MSI")

                with pytest.raises(
                    NetworkError, match="Failed to extract MSI ProductVersion"
                ):
                    strategy.discover_version(app_config, tmp_test_dir)


# TestApiGithubStrategy removed - discover_version() method no longer exists
# Strategy now only has get_version_info() which is tested in TestVersionFirstStrategies
# Integration testing covered by TestVersionFirstFastPath in test_core.py


# TestApiJsonStrategy removed - discover_version() method no longer exists
# Strategy now only has get_version_info() which is tested in TestVersionFirstStrategies
# Integration testing covered by TestVersionFirstFastPath in test_core.py


class TestCacheAndETagSupport:
    """Tests for cache parameter and ETag-based conditional downloads."""

    def test_url_download_with_cache_not_modified(self, tmp_test_dir):
        """Test url_download with cache when file not modified (HTTP 304)."""

        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            }
        }

        strategy = UrlDownloadStrategy()

        # Create a fake cached file
        cached_file = tmp_test_dir / "installer.msi"
        cached_file.write_bytes(b"fake cached msi")

        cache = {
            "version": "1.0.0",
            "etag": 'W/"abc123"',
            "file_path": str(cached_file),
            "sha256": "cached_sha256",
        }

        with requests_mock.Mocker() as m:
            # Mock 304 Not Modified response
            m.get("https://example.com/installer.msi", status_code=304)

            with patch(
                "notapkgtool.discovery.url_download.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="1.0.0", source="msi"
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    app_config, tmp_test_dir, cache=cache
                )

        # Should use cached file
        assert file_path == cached_file
        assert sha256 == "cached_sha256"
        assert discovered.version == "1.0.0"

    # test_api_github_with_cache_not_modified removed -
    # discover_version() no longer exists

    def test_url_download_with_cache_modified(self, tmp_test_dir):
        """Test url_download downloads when file modified (HTTP 200)."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            }
        }

        strategy = UrlDownloadStrategy()

        cache = {
            "version": "1.0.0",
            "etag": 'W/"old_etag"',
            "file_path": str(tmp_test_dir / "old_installer.msi"),
            "sha256": "old_sha256",
        }

        fake_msi = b"new fake MSI content"

        with requests_mock.Mocker() as m:
            # Mock 200 response (file changed)
            m.get(
                "https://example.com/installer.msi",
                content=fake_msi,
                headers={
                    "Content-Length": str(len(fake_msi)),
                    "ETag": 'W/"new_etag"',
                },
            )

            with patch(
                "notapkgtool.discovery.url_download.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="2.0.0", source="msi"
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    app_config, tmp_test_dir, cache=cache
                )

        # Should download new file
        assert file_path.exists()
        assert file_path.name == "installer.msi"
        assert discovered.version == "2.0.0"
        assert len(sha256) == 64

    def test_strategy_without_cache_works(self, tmp_test_dir):
        """Test that strategies work without cache (backward compatible)."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            }
        }

        strategy = UrlDownloadStrategy()

        fake_msi = b"fake MSI no cache"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_msi,
                headers={"Content-Length": str(len(fake_msi))},
            )

            with patch(
                "notapkgtool.discovery.url_download.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="1.0.0", source="msi"
                )

                # Call without cache parameter (None is default)
                discovered, file_path, sha256, headers = strategy.discover_version(
                    app_config, tmp_test_dir
                )

        assert discovered.version == "1.0.0"
        assert file_path.exists()

    def test_cache_with_missing_file_raises(self, tmp_test_dir):
        """Test that cache with missing file raises helpful error."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            }
        }

        strategy = UrlDownloadStrategy()

        # Cache points to non-existent file
        cache = {
            "version": "1.0.0",
            "etag": 'W/"abc123"',
            "file_path": str(tmp_test_dir / "nonexistent.msi"),
            "sha256": "cached_sha",
        }

        with requests_mock.Mocker() as m:
            # Mock 304 response
            m.get("https://example.com/installer.msi", status_code=304)

            from notapkgtool.exceptions import NetworkError

            with pytest.raises(NetworkError, match="Cached file.*not found"):
                strategy.discover_version(app_config, tmp_test_dir, cache=cache)


class TestVersionFirstStrategies:
    """Tests for version-first strategies (web_scrape, api_github, api_json)."""

    def test_web_scrape_with_css_selector(self):
        """Test web_scrape.get_version_info() with CSS selector."""
        from notapkgtool.discovery.web_scrape import WebScrapeStrategy
        from notapkgtool.versioning.keys import VersionInfo

        strategy = WebScrapeStrategy()
        app_config = {
            "source": {
                "page_url": "https://example.com/download.html",
                "link_selector": 'a[href$="-x64.msi"]',
                "version_pattern": r"7z(\d{2})(\d{2})-x64",
                "version_format": "{0}.{1}",
            }
        }

        # Mock HTML page
        html_content = """
        <html>
            <body>
                <div class="downloads">
                    <a href="/a/7z2501-x64.msi">Download 64-bit</a>
                    <a href="/a/7z2501.msi">Download 32-bit</a>
                </div>
            </body>
        </html>
        """

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)

            version_info = strategy.get_version_info(app_config)

        assert isinstance(version_info, VersionInfo)
        assert version_info.version == "25.01"
        assert version_info.download_url == "https://example.com/a/7z2501-x64.msi"
        assert version_info.source == "web_scrape"

    def test_web_scrape_with_regex_pattern(self):
        """Test web_scrape.get_version_info() with regex fallback."""
        from notapkgtool.discovery.web_scrape import WebScrapeStrategy
        from notapkgtool.versioning.keys import VersionInfo

        strategy = WebScrapeStrategy()
        app_config = {
            "source": {
                "page_url": "https://example.com/download.html",
                "link_pattern": r'href="(/files/app-v[0-9.]+-installer\.msi)"',
                "version_pattern": r"app-v([0-9.]+)-installer",
            }
        }

        html_content = '<a href="/files/app-v1.2.3-installer.msi">Download</a>'

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)

            version_info = strategy.get_version_info(app_config)

        assert isinstance(version_info, VersionInfo)
        assert version_info.version == "1.2.3"
        assert (
            version_info.download_url
            == "https://example.com/files/app-v1.2.3-installer.msi"
        )
        assert version_info.source == "web_scrape"

    def test_api_github_get_version_info(self):
        """Test api_github.get_version_info() returns VersionInfo without
        downloading."""
        from notapkgtool.versioning.keys import VersionInfo

        strategy = ApiGithubStrategy()
        app_config = {
            "source": {
                "repo": "owner/repo",
                "asset_pattern": r".*\.msi$",
                "version_pattern": r"v?([0-9.]+)",
            }
        }

        release_data = {
            "tag_name": "v1.2.3",
            "prerelease": False,
            "assets": [
                {
                    "name": "installer.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.2.3/installer.msi",
                }
            ],
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )

            version_info = strategy.get_version_info(app_config)

        assert isinstance(version_info, VersionInfo)
        assert version_info.version == "1.2.3"
        assert "github.com" in version_info.download_url
        assert version_info.source == "api_github"

    def test_api_json_get_version_info(self):
        """Test api_json.get_version_info() returns VersionInfo without downloading."""
        from notapkgtool.versioning.keys import VersionInfo

        strategy = ApiJsonStrategy()
        app_config = {
            "source": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
            }
        }

        api_response = {
            "version": "1.2.3",
            "download_url": "https://example.com/installer.msi",
        }

        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/latest", json=api_response)

            version_info = strategy.get_version_info(app_config)

        assert isinstance(version_info, VersionInfo)
        assert version_info.version == "1.2.3"
        assert version_info.download_url == "https://example.com/installer.msi"
        assert version_info.source == "api_json"
