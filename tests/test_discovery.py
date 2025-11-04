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

from notapkgtool.discovery.base import get_strategy, register_strategy
from notapkgtool.discovery.github_release import GithubReleaseStrategy
from notapkgtool.discovery.http_json import HttpJsonStrategy
from notapkgtool.discovery.http_static import HttpStaticStrategy
from notapkgtool.versioning import DiscoveredVersion


class TestStrategyRegistry:
    """Tests for discovery strategy registration and lookup."""

    def test_get_http_static_strategy(self):
        """Test that http_static strategy can be retrieved."""
        strategy = get_strategy("http_static")
        assert isinstance(strategy, HttpStaticStrategy)

    def test_get_github_release_strategy(self):
        """Test that github_release strategy can be retrieved."""
        strategy = get_strategy("github_release")
        assert isinstance(strategy, GithubReleaseStrategy)

    def test_get_unknown_strategy_raises(self):
        """Test that unknown strategy name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown discovery strategy"):
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


class TestHttpStaticStrategy:
    """Tests for HTTP static download strategy."""

    def test_discover_version_with_msi(self, tmp_test_dir):
        """Test discovering version from MSI file."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        strategy = HttpStaticStrategy()

        # Mock the download and MSI extraction
        fake_msi_content = b"fake MSI content"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_msi_content,
                headers={"Content-Length": str(len(fake_msi_content))},
            )

            with patch(
                "notapkgtool.discovery.http_static.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="1.2.3", source="msi_product_version_from_file"
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    app_config, tmp_test_dir
                )

        assert discovered.version == "1.2.3"
        assert discovered.source == "msi_product_version_from_file"
        assert file_path.exists()
        assert file_path.name == "installer.msi"
        assert isinstance(sha256, str)
        assert len(sha256) == 64  # SHA-256 hex length

    def test_discover_version_missing_url_raises(self, tmp_test_dir):
        """Test that missing URL raises ValueError."""
        app_config = {
            "source": {
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        strategy = HttpStaticStrategy()

        with pytest.raises(ValueError, match="requires 'source.url'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_missing_version_type_raises(self, tmp_test_dir):
        """Test that missing version type raises ValueError."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
            }
        }

        strategy = HttpStaticStrategy()

        with pytest.raises(ValueError, match="requires 'source.version.type'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_unsupported_type_raises(self, tmp_test_dir):
        """Test that unsupported version type raises ValueError."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "unsupported_type"},
            }
        }

        strategy = HttpStaticStrategy()

        fake_content = b"fake content"
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_content,
                headers={"Content-Length": str(len(fake_content))},
            )

            with pytest.raises(ValueError, match="Unsupported version type"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_download_failure_raises(self, tmp_test_dir):
        """Test that download failures raise RuntimeError."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        strategy = HttpStaticStrategy()

        with requests_mock.Mocker() as m:
            m.get("https://example.com/installer.msi", status_code=404)

            with pytest.raises(RuntimeError, match="Failed to download"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_extraction_failure_raises(self, tmp_test_dir):
        """Test that version extraction failures raise RuntimeError."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        strategy = HttpStaticStrategy()

        fake_content = b"not a real MSI"
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_content,
                headers={"Content-Length": str(len(fake_content))},
            )

            with patch(
                "notapkgtool.discovery.http_static.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.side_effect = RuntimeError("Invalid MSI")

                with pytest.raises(
                    RuntimeError, match="Failed to extract MSI ProductVersion"
                ):
                    strategy.discover_version(app_config, tmp_test_dir)


class TestGithubReleaseStrategy:
    """Tests for GitHub release discovery strategy."""

    def test_discover_version_basic(self, tmp_test_dir):
        """Test discovering version from GitHub release with basic config."""
        app_config = {
            "source": {
                "repo": "owner/repo",
            }
        }

        strategy = GithubReleaseStrategy()

        # Mock GitHub API response
        mock_release = {
            "tag_name": "v1.2.3",
            "prerelease": False,
            "assets": [
                {
                    "name": "installer.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.2.3/installer.msi",
                }
            ],
        }

        fake_installer = b"fake installer content"

        with requests_mock.Mocker() as m:
            # Mock GitHub API
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )
            # Mock asset download
            m.get(
                "https://github.com/owner/repo/releases/download/v1.2.3/installer.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "1.2.3"
        assert discovered.source == "github_release"
        assert file_path.exists()
        assert file_path.name == "installer.msi"
        assert isinstance(sha256, str)
        assert len(sha256) == 64  # SHA-256 hex length

    def test_discover_version_with_asset_pattern(self, tmp_test_dir):
        """Test asset pattern matching with multiple assets."""
        app_config = {
            "source": {
                "repo": "owner/repo",
                "asset_pattern": ".*-x64\\.msi$",
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "v2.0.0",
            "prerelease": False,
            "assets": [
                {
                    "name": "installer-x86.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v2.0.0/installer-x86.msi",
                },
                {
                    "name": "installer-x64.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v2.0.0/installer-x64.msi",
                },
            ],
        }

        fake_installer = b"fake x64 installer"

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )
            m.get(
                "https://github.com/owner/repo/releases/download/v2.0.0/installer-x64.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "2.0.0"
        assert file_path.name == "installer-x64.msi"

    def test_discover_version_custom_version_pattern(self, tmp_test_dir):
        """Test custom version extraction pattern."""
        app_config = {
            "source": {
                "repo": "owner/repo",
                "version_pattern": r"release-([0-9.]+)",
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "release-3.5.7",
            "prerelease": False,
            "assets": [
                {
                    "name": "app.exe",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/release-3.5.7/app.exe",
                }
            ],
        }

        fake_installer = b"fake exe"

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )
            m.get(
                "https://github.com/owner/repo/releases/download/release-3.5.7/app.exe",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "3.5.7"

    def test_discover_version_tag_without_v_prefix(self, tmp_test_dir):
        """Test version extraction from tag without 'v' prefix."""
        app_config = {
            "source": {
                "repo": "owner/repo",
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "1.0.0",  # No 'v' prefix
            "prerelease": False,
            "assets": [
                {
                    "name": "app.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/1.0.0/app.msi",
                }
            ],
        }

        fake_installer = b"fake msi"

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )
            m.get(
                "https://github.com/owner/repo/releases/download/1.0.0/app.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "1.0.0"

    def test_discover_version_missing_repo_raises(self, tmp_test_dir):
        """Test that missing repo raises ValueError."""
        app_config = {"source": {}}

        strategy = GithubReleaseStrategy()

        with pytest.raises(ValueError, match="requires 'source.repo'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_invalid_repo_format_raises(self, tmp_test_dir):
        """Test that invalid repo format raises ValueError."""
        app_config = {
            "source": {
                "repo": "invalid-repo-format",
            }
        }

        strategy = GithubReleaseStrategy()

        with pytest.raises(ValueError, match="Invalid repo format"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_repo_not_found_raises(self, tmp_test_dir):
        """Test that 404 from GitHub API raises RuntimeError."""
        app_config = {
            "source": {
                "repo": "owner/nonexistent",
            }
        }

        strategy = GithubReleaseStrategy()

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/nonexistent/releases/latest",
                status_code=404,
            )

            with pytest.raises(RuntimeError, match="not found or has no releases"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_rate_limit_raises(self, tmp_test_dir):
        """Test that rate limit error raises RuntimeError."""
        app_config = {
            "source": {
                "repo": "owner/repo",
            }
        }

        strategy = GithubReleaseStrategy()

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                status_code=403,
            )

            with pytest.raises(RuntimeError, match="rate limit exceeded"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_no_assets_raises(self, tmp_test_dir):
        """Test that release with no assets raises RuntimeError."""
        app_config = {
            "source": {
                "repo": "owner/repo",
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "assets": [],  # No assets
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )

            with pytest.raises(RuntimeError, match="has no assets"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_no_matching_assets_raises(self, tmp_test_dir):
        """Test that no matching assets raises ValueError."""
        app_config = {
            "source": {
                "repo": "owner/repo",
                "asset_pattern": ".*\\.dmg$",  # Looking for DMG
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "assets": [
                {
                    "name": "installer.msi",  # Only MSI available
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.0.0/installer.msi",
                }
            ],
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )

            with pytest.raises(ValueError, match="No assets matched pattern"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_invalid_version_pattern_raises(self, tmp_test_dir):
        """Test that invalid version pattern raises ValueError."""
        app_config = {
            "source": {
                "repo": "owner/repo",
                "version_pattern": "[invalid(regex",  # Invalid regex
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "assets": [
                {
                    "name": "app.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.0.0/app.msi",
                }
            ],
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )

            with pytest.raises(ValueError, match="Invalid version_pattern regex"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_pattern_no_match_raises(self, tmp_test_dir):
        """Test that version pattern with no match raises ValueError."""
        app_config = {
            "source": {
                "repo": "owner/repo",
                "version_pattern": r"release-([0-9.]+)",  # Won't match 'v1.0.0'
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "assets": [
                {
                    "name": "app.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.0.0/app.msi",
                }
            ],
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )

            with pytest.raises(ValueError, match="did not match tag"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_with_authentication_token(self, tmp_test_dir):
        """Test that authentication token is included in request."""
        app_config = {
            "source": {
                "repo": "owner/repo",
                "token": "ghp_faketoken123",
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "assets": [
                {
                    "name": "app.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.0.0/app.msi",
                }
            ],
        }

        fake_installer = b"fake content"

        with requests_mock.Mocker() as m:
            api_mock = m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )
            m.get(
                "https://github.com/owner/repo/releases/download/v1.0.0/app.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

            # Verify token was sent in authorization header
            assert api_mock.called
            assert "Authorization" in api_mock.last_request.headers
            assert (
                api_mock.last_request.headers["Authorization"]
                == "token ghp_faketoken123"
            )

        assert discovered.version == "1.0.0"

    def test_discover_version_prerelease_excluded_by_default(self, tmp_test_dir):
        """Test that prereleases are excluded by default."""
        app_config = {
            "source": {
                "repo": "owner/repo",
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "v2.0.0-beta",
            "prerelease": True,  # This is a prerelease
            "assets": [
                {
                    "name": "app.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v2.0.0-beta/app.msi",
                }
            ],
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )

            with pytest.raises(RuntimeError, match="pre-release and prerelease=false"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_prerelease_included_when_enabled(self, tmp_test_dir):
        """Test that prereleases are included when enabled."""
        app_config = {
            "source": {
                "repo": "owner/repo",
                "prerelease": True,
                # Use pattern that captures prerelease suffix
                "version_pattern": r"v?([0-9.]+-[a-z0-9]+)",
            }
        }

        strategy = GithubReleaseStrategy()

        mock_release = {
            "tag_name": "v2.0.0-rc1",
            "prerelease": True,
            "assets": [
                {
                    "name": "app.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v2.0.0-rc1/app.msi",
                }
            ],
        }

        fake_installer = b"fake rc content"

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )
            m.get(
                "https://github.com/owner/repo/releases/download/v2.0.0-rc1/app.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "2.0.0-rc1"


class TestHttpJsonStrategy:
    """Tests for HTTP JSON API discovery strategy."""

    def test_discover_version_simple_json(self, tmp_test_dir):
        """Test discovering version from simple flat JSON response."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
            }
        }

        strategy = HttpJsonStrategy()

        mock_api_response = {
            "version": "1.2.3",
            "download_url": "https://cdn.vendor.com/app-1.2.3.msi",
        }

        fake_installer = b"fake installer content"

        with requests_mock.Mocker() as m:
            # Mock API
            m.get("https://api.vendor.com/latest", json=mock_api_response)
            # Mock download
            m.get(
                "https://cdn.vendor.com/app-1.2.3.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "1.2.3"
        assert discovered.source == "http_json"
        assert file_path.exists()
        assert isinstance(sha256, str)
        assert len(sha256) == 64

    def test_discover_version_nested_json(self, tmp_test_dir):
        """Test discovering version from nested JSON structure."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/releases",
                "version_path": "release.stable.version",
                "download_url_path": "release.stable.platforms.windows.x64",
            }
        }

        strategy = HttpJsonStrategy()

        mock_api_response = {
            "release": {
                "stable": {
                    "version": "2024.10.28",
                    "platforms": {
                        "windows": {"x64": "https://cdn.vendor.com/win-x64.msi"}
                    },
                }
            }
        }

        fake_installer = b"fake nested installer"

        with requests_mock.Mocker() as m:
            m.get("https://api.vendor.com/releases", json=mock_api_response)
            m.get(
                "https://cdn.vendor.com/win-x64.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "2024.10.28"

    def test_discover_version_array_indexing(self, tmp_test_dir):
        """Test extracting from JSON arrays using array indexing."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/releases",
                "version_path": "releases[0].version",
                "download_url_path": "releases[0].url",
            }
        }

        strategy = HttpJsonStrategy()

        mock_api_response = {
            "releases": [
                {"version": "3.0.0", "url": "https://cdn.vendor.com/v3.msi"},
                {"version": "2.9.9", "url": "https://cdn.vendor.com/v2.msi"},
            ]
        }

        fake_installer = b"fake v3 installer"

        with requests_mock.Mocker() as m:
            m.get("https://api.vendor.com/releases", json=mock_api_response)
            m.get(
                "https://cdn.vendor.com/v3.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "3.0.0"

    def test_discover_version_with_custom_headers(self, tmp_test_dir):
        """Test that custom headers are sent with API request."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
                "headers": {
                    "Authorization": "Bearer test_token_123",
                    "Accept": "application/json",
                },
            }
        }

        strategy = HttpJsonStrategy()

        mock_api_response = {
            "version": "1.0.0",
            "download_url": "https://cdn.vendor.com/app.msi",
        }

        fake_installer = b"fake content"

        with requests_mock.Mocker() as m:
            api_mock = m.get("https://api.vendor.com/latest", json=mock_api_response)
            m.get(
                "https://cdn.vendor.com/app.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

            # Verify headers were sent
            assert api_mock.called
            assert "Authorization" in api_mock.last_request.headers
            assert (
                api_mock.last_request.headers["Authorization"]
                == "Bearer test_token_123"
            )
            assert api_mock.last_request.headers["Accept"] == "application/json"

        assert discovered.version == "1.0.0"

    def test_discover_version_post_request(self, tmp_test_dir):
        """Test POST requests with JSON body."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/query",
                "version_path": "version",
                "download_url_path": "url",
                "method": "POST",
                "body": {"platform": "windows", "arch": "x64"},
            }
        }

        strategy = HttpJsonStrategy()

        mock_api_response = {
            "version": "2.0.0",
            "url": "https://cdn.vendor.com/win-x64.msi",
        }

        fake_installer = b"fake post installer"

        with requests_mock.Mocker() as m:
            api_mock = m.post("https://api.vendor.com/query", json=mock_api_response)
            m.get(
                "https://cdn.vendor.com/win-x64.msi",
                content=fake_installer,
                headers={"Content-Length": str(len(fake_installer))},
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir
            )

            # Verify POST body was sent
            assert api_mock.called
            assert api_mock.last_request.json() == {
                "platform": "windows",
                "arch": "x64",
            }

        assert discovered.version == "2.0.0"

    def test_discover_version_missing_api_url_raises(self, tmp_test_dir):
        """Test that missing api_url raises ValueError."""
        app_config = {"source": {}}

        strategy = HttpJsonStrategy()

        with pytest.raises(ValueError, match="requires 'source.api_url'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_missing_version_path_raises(self, tmp_test_dir):
        """Test that missing version_path raises ValueError."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/latest",
            }
        }

        strategy = HttpJsonStrategy()

        with pytest.raises(ValueError, match="requires 'source.version_path'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_missing_download_url_path_raises(self, tmp_test_dir):
        """Test that missing download_url_path raises ValueError."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/latest",
                "version_path": "version",
            }
        }

        strategy = HttpJsonStrategy()

        with pytest.raises(ValueError, match="requires 'source.download_url_path'"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_invalid_method_raises(self, tmp_test_dir):
        """Test that invalid HTTP method raises ValueError."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
                "method": "DELETE",
            }
        }

        strategy = HttpJsonStrategy()

        with pytest.raises(ValueError, match="Invalid method"):
            strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_api_404_raises(self, tmp_test_dir):
        """Test that API 404 error raises RuntimeError."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/nonexistent",
                "version_path": "version",
                "download_url_path": "download_url",
            }
        }

        strategy = HttpJsonStrategy()

        with requests_mock.Mocker() as m:
            m.get("https://api.vendor.com/nonexistent", status_code=404)

            with pytest.raises(RuntimeError, match="API request failed"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_invalid_json_raises(self, tmp_test_dir):
        """Test that invalid JSON response raises RuntimeError."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
            }
        }

        strategy = HttpJsonStrategy()

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.vendor.com/latest",
                text="This is not JSON",
                headers={"Content-Type": "text/html"},
            )

            with pytest.raises(RuntimeError, match="Invalid JSON response"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_version_path_not_found_raises(self, tmp_test_dir):
        """Test that missing version path in response raises ValueError."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/latest",
                "version_path": "nonexistent.version",
                "download_url_path": "download_url",
            }
        }

        strategy = HttpJsonStrategy()

        mock_api_response = {
            "version": "1.0.0",
            "download_url": "https://cdn.vendor.com/app.msi",
        }

        with requests_mock.Mocker() as m:
            m.get("https://api.vendor.com/latest", json=mock_api_response)

            with pytest.raises(ValueError, match="did not match anything"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_discover_version_download_url_path_not_found_raises(self, tmp_test_dir):
        """Test that missing download URL path in response raises ValueError."""
        app_config = {
            "source": {
                "api_url": "https://api.vendor.com/latest",
                "version_path": "version",
                "download_url_path": "nonexistent.url",
            }
        }

        strategy = HttpJsonStrategy()

        mock_api_response = {
            "version": "1.0.0",
            "download_url": "https://cdn.vendor.com/app.msi",
        }

        with requests_mock.Mocker() as m:
            m.get("https://api.vendor.com/latest", json=mock_api_response)

            with pytest.raises(ValueError, match="did not match anything"):
                strategy.discover_version(app_config, tmp_test_dir)

    def test_get_http_json_strategy(self):
        """Test that http_json strategy can be retrieved from registry."""
        strategy = get_strategy("http_json")
        assert isinstance(strategy, HttpJsonStrategy)


class TestCacheAndETagSupport:
    """Tests for cache parameter and ETag-based conditional downloads."""

    def test_http_static_with_cache_not_modified(self, tmp_test_dir):
        """Test http_static with cache when file not modified (HTTP 304)."""
        from notapkgtool.io import NotModifiedError

        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        strategy = HttpStaticStrategy()

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
                "notapkgtool.discovery.http_static.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="1.0.0", source="msi_product_version_from_file"
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    app_config, tmp_test_dir, cache=cache
                )

        # Should use cached file
        assert file_path == cached_file
        assert sha256 == "cached_sha256"
        assert discovered.version == "1.0.0"

    def test_github_release_with_cache_not_modified(self, tmp_test_dir):
        """Test github_release with cache when asset not modified."""
        from notapkgtool.io import NotModifiedError

        app_config = {
            "source": {
                "repo": "owner/repo",
            }
        }

        strategy = GithubReleaseStrategy()

        # Create cached file
        cached_file = tmp_test_dir / "installer.msi"
        cached_file.write_bytes(b"fake cached installer")

        cache = {
            "version": "1.2.3",
            "etag": 'W/"xyz789"',
            "file_path": str(cached_file),
            "sha256": "cached_sha_for_github",
        }

        mock_release = {
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
            # Mock GitHub API
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=mock_release,
            )
            # Mock 304 for asset download
            m.get(
                "https://github.com/owner/repo/releases/download/v1.2.3/installer.msi",
                status_code=304,
            )

            discovered, file_path, sha256, headers = strategy.discover_version(
                app_config, tmp_test_dir, cache=cache
            )

        # Should use cached file
        assert file_path == cached_file
        assert sha256 == "cached_sha_for_github"
        assert discovered.version == "1.2.3"

    def test_http_static_with_cache_modified(self, tmp_test_dir):
        """Test http_static downloads when file modified (HTTP 200)."""
        app_config = {
            "source": {
                "url": "https://example.com/installer.msi",
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        strategy = HttpStaticStrategy()

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
                "notapkgtool.discovery.http_static.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="2.0.0", source="msi_product_version_from_file"
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
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        strategy = HttpStaticStrategy()

        fake_msi = b"fake MSI no cache"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_msi,
                headers={"Content-Length": str(len(fake_msi))},
            )

            with patch(
                "notapkgtool.discovery.http_static.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="1.0.0", source="msi_product_version_from_file"
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
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        strategy = HttpStaticStrategy()

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

            with pytest.raises(RuntimeError, match="Cached file.*not found"):
                strategy.discover_version(app_config, tmp_test_dir, cache=cache)
