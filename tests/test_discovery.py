"""
Tests for napt.discovery module.

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

from napt.discovery.api_github import ApiGithubStrategy
from napt.discovery.api_json import ApiJsonStrategy
from napt.discovery.base import RemoteVersion, get_strategy, register_strategy
from napt.discovery.url_download import UrlDownloadStrategy
from napt.discovery.web_scrape import WebScrapeStrategy
from napt.exceptions import ConfigError, NetworkError
from napt.versioning.msi import MSIMetadata


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

        with pytest.raises(ConfigError, match="Unknown discovery strategy"):
            get_strategy("nonexistent_strategy")

    def test_register_custom_strategy(self):
        """Test registering a custom strategy."""

        class CustomStrategy:
            def discover_version(self, app_config, output_dir):
                return (
                    RemoteVersion(version="1.0.0", source="custom"),
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
            "id": "test-app",
            "discovery": {
                "url": "https://example.com/installer.msi",
            },
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
                "napt.discovery.url_download.extract_msi_metadata"
            ) as mock_extract:
                mock_extract.return_value = MSIMetadata(
                    product_name="", product_version="1.2.3", architecture="x64"
                )

                version, version_source, file_path, sha256, headers = (
                    strategy.discover_version(app_config, tmp_test_dir)
                )

        assert version == "1.2.3"
        assert version_source == "url_download"
        assert file_path == tmp_test_dir / "test-app" / "installer.msi"
        assert file_path.exists()
        assert isinstance(sha256, str)
        assert len(sha256) == 64  # SHA-256 hex length

    def test_discover_version_missing_url_raises(self, tmp_test_dir):
        """Test that missing URL raises ValueError."""
        app_config = {"discovery": {}}

        strategy = UrlDownloadStrategy()

        with pytest.raises(ConfigError, match="requires 'discovery.url'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_download_failure_raises(self, tmp_test_dir):
        """Test that download failures raise NetworkError."""
        app_config = {
            "discovery": {
                "url": "https://example.com/installer.msi",
            }
        }

        strategy = UrlDownloadStrategy()

        with requests_mock.Mocker() as m:
            m.get("https://example.com/installer.msi", status_code=404)

            from napt.exceptions import NetworkError

            with pytest.raises(NetworkError, match="download failed"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_extraction_failure_raises(self, tmp_test_dir):
        """Test that version extraction failures raise NetworkError."""
        app_config = {
            "discovery": {
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
                "napt.discovery.url_download.extract_msi_metadata"
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
            "id": "test-app",
            "discovery": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            },
        }

        strategy = UrlDownloadStrategy()

        # Create a fake cached file in the app-scoped directory
        app_dir = tmp_test_dir / "test-app"
        app_dir.mkdir()
        cached_file = app_dir / "installer.msi"
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
                "napt.discovery.url_download.extract_msi_metadata"
            ) as mock_extract:
                mock_extract.return_value = MSIMetadata(
                    product_name="", product_version="1.0.0", architecture="x64"
                )

                version, version_source, file_path, sha256, headers = (
                    strategy.discover_version(app_config, tmp_test_dir, cache=cache)
                )

        # Should use cached file from app-scoped directory
        assert file_path == cached_file
        assert sha256 == "cached_sha256"
        assert version == "1.0.0"

    # test_api_github_with_cache_not_modified removed -
    # discover_version() no longer exists

    def test_url_download_with_cache_modified(self, tmp_test_dir):
        """Test url_download downloads when file modified (HTTP 200)."""
        app_config = {
            "id": "test-app",
            "discovery": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            },
        }

        strategy = UrlDownloadStrategy()

        cache = {
            "version": "1.0.0",
            "etag": 'W/"old_etag"',
            "file_path": str(tmp_test_dir / "test-app" / "old_installer.msi"),
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
                "napt.discovery.url_download.extract_msi_metadata"
            ) as mock_extract:
                mock_extract.return_value = MSIMetadata(
                    product_name="", product_version="2.0.0", architecture="x64"
                )

                version, version_source, file_path, sha256, headers = (
                    strategy.discover_version(app_config, tmp_test_dir, cache=cache)
                )

        # Should download new file into app-scoped directory
        assert file_path == tmp_test_dir / "test-app" / "installer.msi"
        assert file_path.exists()
        assert version == "2.0.0"
        assert len(sha256) == 64

    def test_strategy_without_cache_works(self, tmp_test_dir):
        """Test that strategies work without cache (backward compatible)."""
        app_config = {
            "id": "test-app",
            "discovery": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            },
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
                "napt.discovery.url_download.extract_msi_metadata"
            ) as mock_extract:
                mock_extract.return_value = MSIMetadata(
                    product_name="", product_version="1.0.0", architecture="x64"
                )

                # Call without cache parameter (None is default)
                version, version_source, file_path, sha256, headers = (
                    strategy.discover_version(app_config, tmp_test_dir)
                )

        assert version == "1.0.0"
        assert file_path == tmp_test_dir / "test-app" / "installer.msi"
        assert file_path.exists()

    def test_cache_with_missing_file_raises(self, tmp_test_dir):
        """Test that cache with missing file raises helpful error."""
        app_config = {
            "id": "test-app",
            "discovery": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi"},
            },
        }

        strategy = UrlDownloadStrategy()

        # Cache points to non-existent file
        cache = {
            "version": "1.0.0",
            "etag": 'W/"abc123"',
            "file_path": str(tmp_test_dir / "test-app" / "nonexistent.msi"),
            "sha256": "cached_sha",
        }

        with requests_mock.Mocker() as m:
            # Mock 304 response
            m.get("https://example.com/installer.msi", status_code=304)

            from napt.exceptions import NetworkError

            with pytest.raises(NetworkError, match="Cached file.*not found"):
                strategy.discover_version(app_config, tmp_test_dir, cache=cache)


class TestVersionFirstStrategies:
    """Tests for version-first strategies (web_scrape, api_github, api_json)."""

    def test_web_scrape_with_css_selector(self):
        """Test web_scrape.get_version_info() with CSS selector."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
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

        assert isinstance(version_info, RemoteVersion)
        assert version_info.version == "25.01"
        assert version_info.download_url == "https://example.com/a/7z2501-x64.msi"
        assert version_info.source == "web_scrape"

    def test_web_scrape_with_regex_pattern(self):
        """Test web_scrape.get_version_info() with regex fallback."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/download.html",
                "link_pattern": r'href="(/files/app-v[0-9.]+-installer\.msi)"',
                "version_pattern": r"app-v([0-9.]+)-installer",
            }
        }

        html_content = '<a href="/files/app-v1.2.3-installer.msi">Download</a>'

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)

            version_info = strategy.get_version_info(app_config)

        assert isinstance(version_info, RemoteVersion)
        assert version_info.version == "1.2.3"
        assert (
            version_info.download_url
            == "https://example.com/files/app-v1.2.3-installer.msi"
        )
        assert version_info.source == "web_scrape"

    def test_api_github_get_version_info(self):
        """Test api_github.get_version_info() returns RemoteVersion without
        downloading."""
        strategy = ApiGithubStrategy()
        app_config = {
            "discovery": {
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

        assert isinstance(version_info, RemoteVersion)
        assert version_info.version == "1.2.3"
        assert "github.com" in version_info.download_url
        assert version_info.source == "api_github"

    def test_api_json_get_version_info(self):
        """Test api_json.get_version_info() returns RemoteVersion without downloading."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
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

        assert isinstance(version_info, RemoteVersion)
        assert version_info.version == "1.2.3"
        assert version_info.download_url == "https://example.com/installer.msi"
        assert version_info.source == "api_json"


# =============================================================================
# WebScrapeStrategy — error cases and validate_config
# =============================================================================


class TestWebScrapeStrategyErrors:
    """Tests error handling in WebScrapeStrategy.get_version_info()."""

    def test_missing_page_url_raises(self):
        """Tests that missing page_url raises ConfigError."""
        strategy = WebScrapeStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.page_url'"):
            strategy.get_version_info(
                {"discovery": {"link_selector": "a", "version_pattern": "."}}
            )

    def test_missing_link_finding_method_raises(self):
        """Tests that omitting both link_selector and link_pattern raises ConfigError."""
        strategy = WebScrapeStrategy()
        with pytest.raises(ConfigError, match="link_selector.*link_pattern"):
            strategy.get_version_info(
                {
                    "discovery": {
                        "page_url": "https://example.com",
                        "version_pattern": r"(\d+)",
                    }
                }
            )

    def test_missing_version_pattern_raises(self):
        """Tests that missing version_pattern raises ConfigError."""
        strategy = WebScrapeStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.version_pattern'"):
            strategy.get_version_info(
                {
                    "discovery": {
                        "page_url": "https://example.com",
                        "link_selector": "a",
                    }
                }
            )

    def test_page_fetch_failure_raises(self):
        """Tests that a non-2xx page response raises NetworkError."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": "a",
                "version_pattern": r"(\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get("https://example.com/dl.html", status_code=503)
            with pytest.raises(NetworkError, match="Failed to fetch page"):
                strategy.get_version_info(app_config)

    def test_css_selector_not_found_raises(self):
        """Tests that a CSS selector matching nothing raises ConfigError."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": 'a[href$=".msi"]',
                "version_pattern": r"(\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/dl.html",
                text="<html><body>no links here</body></html>",
            )
            with pytest.raises(ConfigError, match="did not match any elements"):
                strategy.get_version_info(app_config)

    def test_regex_link_pattern_not_found_raises(self):
        """Tests that a regex link_pattern matching nothing raises ConfigError."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_pattern": r'href="(/files/nomatch\.msi)"',
                "version_pattern": r"(\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/dl.html", text="<html><body>nothing</body></html>"
            )
            with pytest.raises(ConfigError, match="did not match anything"):
                strategy.get_version_info(app_config)

    def test_version_pattern_no_match_raises(self):
        """Tests that a version_pattern not matching the URL raises ConfigError."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": "a",
                "version_pattern": r"no_match_here(\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/dl.html",
                text='<a href="/files/installer.msi">Download</a>',
            )
            with pytest.raises(ConfigError, match="did not match"):
                strategy.get_version_info(app_config)

    def test_version_format_with_multiple_groups(self):
        """Tests that version_format combines multiple capture groups correctly."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": "a",
                "version_pattern": r"v(\d+)\.(\d+)\.(\d+)",
                "version_format": "{0}.{1}.{2}",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/dl.html",
                text='<a href="/app-v3.14.1-x64.msi">Download</a>',
            )
            version_info = strategy.get_version_info(app_config)
        assert version_info.version == "3.14.1"
        assert version_info.source == "web_scrape"


class TestWebScrapeValidateConfig:
    """Tests for WebScrapeStrategy.validate_config()."""

    def test_valid_config_returns_empty(self):
        """Tests that a fully valid config returns no errors."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "page_url": "https://example.com",
                    "link_selector": "a",
                    "version_pattern": r"v([0-9.]+)",
                }
            }
        )
        assert errors == []

    def test_missing_page_url(self):
        """Tests that missing page_url is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {"discovery": {"link_selector": "a", "version_pattern": "."}}
        )
        assert any("page_url" in e for e in errors)

    def test_missing_link_methods(self):
        """Tests that missing both link fields is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "page_url": "https://example.com",
                    "version_pattern": ".",
                }
            }
        )
        assert any("link_selector" in e or "link_pattern" in e for e in errors)

    def test_missing_version_pattern(self):
        """Tests that missing version_pattern is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {"discovery": {"page_url": "https://example.com", "link_selector": "a"}}
        )
        assert any("version_pattern" in e for e in errors)

    def test_invalid_version_pattern_regex(self):
        """Tests that an invalid version_pattern regex is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "page_url": "https://example.com",
                    "link_selector": "a",
                    "version_pattern": "[unclosed",
                }
            }
        )
        assert any("regex" in e.lower() or "Invalid" in e for e in errors)

    def test_invalid_link_pattern_regex(self):
        """Tests that an invalid link_pattern regex is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "page_url": "https://example.com",
                    "link_pattern": "[unclosed",
                    "version_pattern": r"(\d+)",
                }
            }
        )
        assert any("regex" in e.lower() or "Invalid" in e for e in errors)


# =============================================================================
# ApiGithubStrategy — error cases and validate_config
# =============================================================================


class TestApiGithubStrategyErrors:
    """Tests error handling in ApiGithubStrategy.get_version_info()."""

    def test_missing_repo_raises(self):
        """Tests that missing repo raises ConfigError."""
        strategy = ApiGithubStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.repo'"):
            strategy.get_version_info({"discovery": {"asset_pattern": ".*"}})

    def test_invalid_repo_format_raises(self):
        """Tests that repo without slash raises ConfigError."""
        strategy = ApiGithubStrategy()
        with pytest.raises(ConfigError, match="Invalid repo format"):
            strategy.get_version_info(
                {"discovery": {"repo": "noslash", "asset_pattern": ".*"}}
            )

    def test_missing_asset_pattern_raises(self):
        """Tests that missing asset_pattern raises ConfigError."""
        strategy = ApiGithubStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.asset_pattern'"):
            strategy.get_version_info({"discovery": {"repo": "owner/repo"}})

    def test_repo_not_found_raises(self):
        """Tests that a 404 API response raises NetworkError."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": ".*"}}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                status_code=404,
            )
            with pytest.raises(NetworkError, match="not found"):
                strategy.get_version_info(app_config)

    def test_rate_limited_raises(self):
        """Tests that a 403 API response raises NetworkError mentioning rate limit."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": ".*"}}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                status_code=403,
            )
            with pytest.raises(NetworkError, match="rate limit"):
                strategy.get_version_info(app_config)

    def test_prerelease_rejected_when_flag_false(self):
        """Tests that a prerelease latest release is rejected when prerelease=False."""
        strategy = ApiGithubStrategy()
        app_config = {
            "discovery": {
                "repo": "owner/repo",
                "asset_pattern": r".*\.msi$",
                "prerelease": False,
            }
        }
        release_data = {
            "tag_name": "v2.0.0-beta",
            "prerelease": True,
            "assets": [
                {
                    "name": "installer.msi",
                    "browser_download_url": "https://example.com/installer.msi",
                }
            ],
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )
            with pytest.raises(NetworkError, match="pre-release"):
                strategy.get_version_info(app_config)

    def test_no_assets_raises(self):
        """Tests that a release with no assets raises NetworkError."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": r".*\.msi$"}}
        release_data = {"tag_name": "v1.0.0", "prerelease": False, "assets": []}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )
            with pytest.raises(NetworkError, match="has no assets"):
                strategy.get_version_info(app_config)

    def test_no_matching_asset_raises(self):
        """Tests that no asset matching the pattern raises ConfigError."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": r".*\.msi$"}}
        release_data = {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "assets": [
                {
                    "name": "installer.exe",
                    "browser_download_url": "https://example.com/installer.exe",
                }
            ],
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )
            with pytest.raises(ConfigError, match="No assets matched"):
                strategy.get_version_info(app_config)

    def test_named_version_capture_group(self):
        """Tests that a named 'version' capture group is used correctly."""
        strategy = ApiGithubStrategy()
        app_config = {
            "discovery": {
                "repo": "owner/repo",
                "asset_pattern": r".*\.msi$",
                "version_pattern": r"release-(?P<version>[0-9.]+)",
            }
        }
        release_data = {
            "tag_name": "release-3.5.0",
            "prerelease": False,
            "assets": [
                {
                    "name": "installer.msi",
                    "browser_download_url": "https://example.com/installer.msi",
                }
            ],
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )
            version_info = strategy.get_version_info(app_config)
        assert version_info.version == "3.5.0"
        assert version_info.source == "api_github"


class TestApiGithubValidateConfig:
    """Tests for ApiGithubStrategy.validate_config()."""

    def test_valid_config_returns_empty(self):
        """Tests that a fully valid config returns no errors."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config(
            {"discovery": {"repo": "owner/repo", "asset_pattern": r".*\.msi$"}}
        )
        assert errors == []

    def test_missing_repo(self):
        """Tests that missing repo is reported."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config({"discovery": {"asset_pattern": r".*\.msi$"}})
        assert any("repo" in e for e in errors)

    def test_invalid_repo_format(self):
        """Tests that repo without slash is reported."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config(
            {"discovery": {"repo": "noslash", "asset_pattern": r".*\.msi$"}}
        )
        assert any("owner/repo" in e for e in errors)

    def test_missing_asset_pattern(self):
        """Tests that missing asset_pattern is reported."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config({"discovery": {"repo": "owner/repo"}})
        assert any("asset_pattern" in e for e in errors)

    def test_invalid_version_pattern_regex(self):
        """Tests that an invalid version_pattern regex is reported."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "repo": "owner/repo",
                    "asset_pattern": r".*",
                    "version_pattern": "[unclosed",
                }
            }
        )
        assert any("regex" in e.lower() or "Invalid" in e for e in errors)


# =============================================================================
# ApiJsonStrategy — error cases and validate_config
# =============================================================================


class TestApiJsonStrategyErrors:
    """Tests error handling in ApiJsonStrategy.get_version_info()."""

    def test_missing_api_url_raises(self):
        """Tests that missing api_url raises ConfigError."""
        strategy = ApiJsonStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.api_url'"):
            strategy.get_version_info(
                {
                    "discovery": {
                        "version_path": "version",
                        "download_url_path": "url",
                    }
                }
            )

    def test_missing_version_path_raises(self):
        """Tests that missing version_path raises ConfigError."""
        strategy = ApiJsonStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.version_path'"):
            strategy.get_version_info(
                {
                    "discovery": {
                        "api_url": "https://api.example.com",
                        "download_url_path": "url",
                    }
                }
            )

    def test_missing_download_url_path_raises(self):
        """Tests that missing download_url_path raises ConfigError."""
        strategy = ApiJsonStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.download_url_path'"):
            strategy.get_version_info(
                {
                    "discovery": {
                        "api_url": "https://api.example.com",
                        "version_path": "version",
                    }
                }
            )

    def test_http_error_raises(self):
        """Tests that a non-2xx API response raises NetworkError."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "url",
            }
        }
        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/latest", status_code=500)
            with pytest.raises(NetworkError, match="API request failed"):
                strategy.get_version_info(app_config)

    def test_invalid_json_response_raises(self):
        """Tests that a non-JSON response raises NetworkError."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "url",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                text="not json at all",
                status_code=200,
            )
            with pytest.raises(NetworkError, match="Invalid JSON"):
                strategy.get_version_info(app_config)

    def test_version_path_not_found_raises(self):
        """Tests that a version_path that matches nothing raises ConfigError."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "nonexistent_field",
                "download_url_path": "download_url",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                json={"version": "1.0.0", "download_url": "https://example.com/f.msi"},
            )
            with pytest.raises(ConfigError, match="did not match"):
                strategy.get_version_info(app_config)

    def test_post_method(self):
        """Tests that method=POST sends a POST request."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/query",
                "version_path": "version",
                "download_url_path": "download_url",
                "method": "POST",
                "body": {"platform": "windows"},
            }
        }
        with requests_mock.Mocker() as m:
            m.post(
                "https://api.example.com/query",
                json={
                    "version": "2.0.0",
                    "download_url": "https://example.com/v2.msi",
                },
            )
            version_info = strategy.get_version_info(app_config)
        assert version_info.version == "2.0.0"
        assert version_info.source == "api_json"

    def test_env_var_header_expansion(self, monkeypatch):
        """Tests that ${VAR} placeholders in headers are expanded from env."""
        monkeypatch.setenv("TEST_API_TOKEN", "secret123")
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
                "headers": {"Authorization": "${TEST_API_TOKEN}"},
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                json={
                    "version": "1.0.0",
                    "download_url": "https://example.com/file.msi",
                },
            )
            version_info = strategy.get_version_info(app_config)
            assert m.last_request.headers.get("Authorization") == "secret123"
        assert version_info.version == "1.0.0"

    def test_nested_json_path(self):
        """Tests that nested JSONPath expressions extract values correctly."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "release.version",
                "download_url_path": "release.windows.x64",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                json={
                    "release": {
                        "version": "3.1.4",
                        "windows": {"x64": "https://example.com/app-3.1.4-x64.msi"},
                    }
                },
            )
            version_info = strategy.get_version_info(app_config)
        assert version_info.version == "3.1.4"
        assert "3.1.4" in version_info.download_url


class TestApiJsonValidateConfig:
    """Tests for ApiJsonStrategy.validate_config()."""

    def test_valid_config_returns_empty(self):
        """Tests that a fully valid config returns no errors."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com/latest",
                    "version_path": "version",
                    "download_url_path": "download_url",
                }
            }
        )
        assert errors == []

    def test_missing_api_url(self):
        """Tests that missing api_url is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "version_path": "version",
                    "download_url_path": "url",
                }
            }
        )
        assert any("api_url" in e for e in errors)

    def test_missing_version_path(self):
        """Tests that missing version_path is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "download_url_path": "url",
                }
            }
        )
        assert any("version_path" in e for e in errors)

    def test_missing_download_url_path(self):
        """Tests that missing download_url_path is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "version_path": "version",
                }
            }
        )
        assert any("download_url_path" in e for e in errors)

    def test_invalid_method(self):
        """Tests that an invalid HTTP method is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "version_path": "version",
                    "download_url_path": "url",
                    "method": "DELETE",
                }
            }
        )
        assert any("method" in e for e in errors)

    def test_headers_not_dict_reported(self):
        """Tests that a non-dict headers value is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "version_path": "version",
                    "download_url_path": "url",
                    "headers": "not-a-dict",
                }
            }
        )
        assert any("headers" in e for e in errors)
