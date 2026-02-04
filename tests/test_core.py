"""
Tests for napt.core module.

Tests core orchestration including:
- Recipe validation workflow
- discover_recipe function
- Error handling
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from napt.core import discover_recipe
from napt.exceptions import ConfigError
from napt.versioning import DiscoveredVersion


class TestDiscoverRecipe:
    """Tests for discover_recipe orchestration function."""

    def test_discover_recipe_success(self, tmp_test_dir, create_yaml_file):
        """Test successful recipe check workflow."""
        # Create a minimal recipe
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "Test App",
                "id": "test-app",
                "source": {
                    "strategy": "url_download",
                    "url": "https://example.com/test.msi",
                },
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        # Mock the discovery strategy (url_download - file-first)
        with patch("napt.core.get_strategy") as mock_get_strategy:
            mock_strategy = mock_get_strategy.return_value
            # Ensure it doesn't have get_version_info (file-first strategy)
            del mock_strategy.get_version_info
            mock_strategy.discover_version.return_value = (
                DiscoveredVersion(version="1.2.3", source="msi"),
                tmp_test_dir / "test.msi",
                "abc123" * 8,  # fake SHA-256
                {"ETag": 'W/"test123"'},  # HTTP headers
            )

            result = discover_recipe(recipe_path, tmp_test_dir)

        assert result.app_name == "Test App"
        assert result.app_id == "test-app"
        assert result.strategy == "url_download"
        assert result.version == "1.2.3"
        assert result.version_source == "msi"
        assert result.status == "success"
        assert hasattr(result, "file_path")
        assert hasattr(result, "sha256")

    def test_discover_recipe_no_app_raises(self, tmp_test_dir, create_yaml_file):
        """Test that recipe with no app raises ConfigError."""
        recipe_data = {"apiVersion": "napt/v1"}
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="No app defined"):
            discover_recipe(recipe_path, tmp_test_dir)

    def test_discover_recipe_missing_strategy_raises(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that missing strategy raises ConfigError."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "Test App",
                "source": {},  # No strategy
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="No 'source.strategy' defined"):
            discover_recipe(recipe_path, tmp_test_dir)

    def test_discover_recipe_unknown_strategy_raises(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that unknown strategy raises ConfigError."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "Test App",
                "source": {"strategy": "nonexistent_strategy"},
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="Unknown discovery strategy"):
            discover_recipe(recipe_path, tmp_test_dir)

    def test_discover_recipe_missing_file_raises(self, tmp_test_dir):
        """Test that missing recipe file raises error."""
        nonexistent = tmp_test_dir / "nonexistent.yaml"

        with pytest.raises(ConfigError):
            discover_recipe(nonexistent, tmp_test_dir)


class TestVersionFirstFastPath:
    """Tests for version-first fast path in discover_recipe."""

    def test_version_first_cache_hit_skips_download(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that version-first strategies skip download when version
        matches cache."""
        from pathlib import Path

        # Create a minimal recipe with web_scrape strategy
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "Test App",
                "id": "test-app",
                "source": {
                    "strategy": "web_scrape",
                    "page_url": "https://example.com/download.html",
                    "link_selector": 'a[href$=".msi"]',
                    "version_pattern": r"app-v([0-9.]+)-installer",
                },
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        # Create cached file
        cached_file = tmp_test_dir / "app-v1.2.3-installer.msi"
        cached_file.write_bytes(b"fake installer content")

        # Mock HTML page for web_scrape
        html_content = '<a href="/app-v1.2.3-installer.msi">Download</a>'

        # Mock state with matching version
        state = {
            "metadata": {"napt_version": "0.1.0", "schema_version": "2"},
            "apps": {
                "test-app": {
                    "url": "https://example.com/app-v1.2.3-installer.msi",
                    "known_version": "1.2.3",
                    "sha256": "abc123" * 8,
                }
            },
        }

        import requests_mock

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)

            with patch("napt.core.load_state") as mock_load_state:
                mock_load_state.return_value = state

                with patch("napt.core.save_state"):
                    with patch("napt.core.download_file") as mock_download:
                        result = discover_recipe(
                            recipe_path, tmp_test_dir, state_file=Path("state.json")
                        )

                        # Verify download was NOT called (fast path)
                        mock_download.assert_not_called()

        # Verify result uses cached version
        assert result.version == "1.2.3"
        assert result.app_id == "test-app"
        assert result.status == "success"

    def test_version_first_cache_miss_downloads(self, tmp_test_dir, create_yaml_file):
        """Test that version-first strategies download when version changes."""
        from pathlib import Path

        # Create a minimal recipe with web_scrape strategy
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "Test App",
                "id": "test-app",
                "source": {
                    "strategy": "web_scrape",
                    "page_url": "https://example.com/download.html",
                    "link_selector": 'a[href$=".msi"]',
                    "version_pattern": r"app-v([0-9.]+)-installer",
                },
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        # Mock HTML page for web_scrape (new version)
        html_content = '<a href="/app-v2.0.0-installer.msi">Download</a>'

        # Mock state with OLD version
        state = {
            "metadata": {"napt_version": "0.1.0", "schema_version": "2"},
            "apps": {
                "test-app": {
                    "url": "https://example.com/app-v1.2.3-installer.msi",
                    "known_version": "1.2.3",
                    "sha256": "old_hash" * 8,
                }
            },
        }

        fake_file = tmp_test_dir / "app-v2.0.0-installer.msi"
        fake_file.write_bytes(b"new installer content")

        import requests_mock

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)

            with patch("napt.core.load_state") as mock_load_state:
                mock_load_state.return_value = state

                with patch("napt.core.save_state"):
                    with patch("napt.core.download_file") as mock_download:
                        mock_download.return_value = (
                            fake_file,
                            "new_hash" * 8,
                            {"ETag": 'W/"new123"'},
                        )

                        result = discover_recipe(
                            recipe_path, tmp_test_dir, state_file=Path("state.json")
                        )

                        # Verify download WAS called (version changed)
                        mock_download.assert_called_once()

            # Verify result has new version
            assert result.version == "2.0.0"
            assert result.app_id == "test-app"
            assert result.status == "success"

    def test_version_first_missing_cached_file_redownloads(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that missing cached file triggers re-download even if
        version matches."""
        from pathlib import Path

        import requests_mock

        # Create a minimal recipe with web_scrape strategy
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "Test App",
                "id": "test-app",
                "source": {
                    "strategy": "web_scrape",
                    "page_url": "https://example.com/download.html",
                    "link_selector": 'a[href$=".msi"]',
                    "version_pattern": r"app-v([0-9.]+)-installer",
                },
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        # Mock HTML page for web_scrape
        html_content = '<a href="/app-v1.2.3-installer.msi">Download</a>'

        # Mock state with matching version BUT no cached file exists
        state = {
            "metadata": {"napt_version": "0.1.0", "schema_version": "2"},
            "apps": {
                "test-app": {
                    "url": "https://example.com/app-v1.2.3-installer.msi",
                    "known_version": "1.2.3",
                    "sha256": "abc123" * 8,
                }
            },
        }

        fake_content = b"redownloaded installer content"

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)
            m.get(
                "https://example.com/app-v1.2.3-installer.msi",
                content=fake_content,
                headers={"Content-Length": str(len(fake_content))},
            )

            with patch("napt.core.load_state") as mock_load_state:
                mock_load_state.return_value = state

                with patch("napt.core.save_state"):
                    result = discover_recipe(
                        recipe_path, tmp_test_dir, state_file=Path("state.json")
                    )

        # Verify result and that file was downloaded
        assert result.version == "1.2.3"
        assert result.status == "success"
        fake_file = tmp_test_dir / "app-v1.2.3-installer.msi"
        assert fake_file.exists()
