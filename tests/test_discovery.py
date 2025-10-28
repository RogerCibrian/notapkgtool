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

                discovered, file_path, sha256 = strategy.discover_version(
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

            discovered, file_path, sha256 = strategy.discover_version(
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

            discovered, file_path, sha256 = strategy.discover_version(
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

            discovered, file_path, sha256 = strategy.discover_version(
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

            discovered, file_path, sha256 = strategy.discover_version(
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

            discovered, file_path, sha256 = strategy.discover_version(
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

            discovered, file_path, sha256 = strategy.discover_version(
                app_config, tmp_test_dir
            )

        assert discovered.version == "2.0.0-rc1"
