"""
Tests for napt.core module.

Tests core orchestration including:
- Recipe validation workflow
- discover_recipe function
- Error handling
"""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
import requests_mock

from napt.discovery.manager import discover_recipe
from napt.exceptions import ConfigError


class TestDiscoverRecipe:
    """Tests for discover_recipe orchestration function."""

    def test_discover_recipe_success(self, tmp_test_dir, create_yaml_file):
        """Tests the successful url_download discovery workflow end to end."""
        from napt.discovery.base import StrategyResult

        recipe_data = {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {
                "strategy": "url_download",
                "url": "https://example.com/test.msi",
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with patch("napt.discovery.manager.run_url_download") as mock_run:
            mock_run.return_value = StrategyResult(
                version="1.2.3",
                version_source="url_download",
                file_path=tmp_test_dir / "test.msi",
                sha256="abc123" * 8,
                download_url="https://example.com/test.msi",
                cached=False,
            )
            result = discover_recipe(
                recipe_path,
                tmp_test_dir,
                state_dir=tmp_test_dir / "state",
            )

        assert result.app_name == "Test App"
        assert result.app_id == "test-app"
        assert result.strategy == "url_download"
        assert result.version == "1.2.3"
        assert result.version_source == "url_download"
        assert result.status == "success"

    def test_discover_recipe_missing_strategy_in_empty_recipe_raises(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that recipe without discovery section raises ConfigError."""
        recipe_data = {"apiVersion": "napt/v1", "name": "Test", "id": "test"}
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="Missing required field: discovery"):
            discover_recipe(
                recipe_path,
                tmp_test_dir,
                state_dir=tmp_test_dir / "state",
            )

    def test_discover_recipe_missing_strategy_raises(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that missing strategy raises ConfigError."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {},  # No strategy
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="strategy"):
            discover_recipe(
                recipe_path,
                tmp_test_dir,
                state_dir=tmp_test_dir / "state",
            )

    def test_discover_recipe_unknown_strategy_raises(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that unknown strategy raises ConfigError."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {"strategy": "nonexistent_strategy"},
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="Unknown discovery strategy"):
            discover_recipe(
                recipe_path,
                tmp_test_dir,
                state_dir=tmp_test_dir / "state",
            )

    def test_discover_recipe_missing_file_raises(self, tmp_test_dir):
        """Test that missing recipe file raises error."""
        nonexistent = tmp_test_dir / "nonexistent.yaml"

        with pytest.raises(ConfigError):
            discover_recipe(nonexistent, tmp_test_dir)


def _web_scrape_recipe(create_yaml_file, version_pattern=r"app-v([0-9.]+)-installer"):
    """Creates a web_scrape recipe whose version comes from the link's filename."""
    return create_yaml_file(
        "recipe.yaml",
        {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {
                "strategy": "web_scrape",
                "page_url": "https://example.com/download.html",
                "link_selector": 'a[href$=".msi"]',
                "version_pattern": version_pattern,
            },
        },
    )


class TestVersionFirstInstallerReuse:
    """Tests that version-first discovery reuses a version's download folder."""

    def test_existing_version_folder_skips_download(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that an installer already in the version folder is reused."""
        recipe_path = _web_scrape_recipe(create_yaml_file)
        installer = tmp_test_dir / "test-app" / "1.2.3" / "any-name.msi"
        installer.parent.mkdir(parents=True)
        installer.write_bytes(b"fake installer content")

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/download.html",
                text='<a href="/app-v1.2.3-installer.msi">Download</a>',
            )
            with patch("napt.discovery.base.download_file") as mock_download:
                result = discover_recipe(
                    recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                )

        mock_download.assert_not_called()
        assert result.version == "1.2.3"
        assert result.file_path == installer
        assert result.sha256 == hashlib.sha256(b"fake installer content").hexdigest()

    def test_older_version_is_downloaded_not_relabelled(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a vendor rollback never reuses the newer version's file."""
        recipe_path = _web_scrape_recipe(create_yaml_file)
        newer = tmp_test_dir / "test-app" / "2.0.0" / "app-v2.0.0-installer.msi"
        newer.parent.mkdir(parents=True)
        newer.write_bytes(b"the 2.0.0 installer")
        older_content = b"the 1.9.0 installer"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/download.html",
                text='<a href="/app-v1.9.0-installer.msi">Download</a>',
            )
            m.get(
                "https://example.com/app-v1.9.0-installer.msi",
                content=older_content,
                headers={"Content-Length": str(len(older_content))},
            )
            result = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )

        assert result.version == "1.9.0"
        assert result.file_path == (
            tmp_test_dir / "test-app" / "1.9.0" / "app-v1.9.0-installer.msi"
        )
        assert result.sha256 == hashlib.sha256(older_content).hexdigest()
        assert newer.read_bytes() == b"the 2.0.0 installer"

    def test_unfinished_download_is_not_reused(self, tmp_test_dir, create_yaml_file):
        """Tests that a leftover .part file does not count as the installer."""
        recipe_path = _web_scrape_recipe(create_yaml_file)
        leftover = tmp_test_dir / "test-app" / "1.2.3" / "app-v1.2.3-installer.msi.part"
        leftover.parent.mkdir(parents=True)
        leftover.write_bytes(b"half a file")
        content = b"the whole installer"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/download.html",
                text='<a href="/app-v1.2.3-installer.msi">Download</a>',
            )
            m.get(
                "https://example.com/app-v1.2.3-installer.msi",
                content=content,
                headers={"Content-Length": str(len(content))},
            )
            result = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )

        assert result.file_path.name == "app-v1.2.3-installer.msi"
        assert result.file_path.read_bytes() == content

    def test_ambiguous_version_folder_downloads_again(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a folder with several files is not guessed from."""
        recipe_path = _web_scrape_recipe(create_yaml_file)
        version_dir = tmp_test_dir / "test-app" / "1.2.3"
        version_dir.mkdir(parents=True)
        (version_dir / "one.msi").write_bytes(b"one")
        (version_dir / "two.msi").write_bytes(b"two")
        content = b"the real installer"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/download.html",
                text='<a href="/app-v1.2.3-installer.msi">Download</a>',
            )
            m.get(
                "https://example.com/app-v1.2.3-installer.msi",
                content=content,
                headers={"Content-Length": str(len(content))},
            )
            result = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )

        assert result.file_path == version_dir / "app-v1.2.3-installer.msi"
        assert result.sha256 == hashlib.sha256(content).hexdigest()

    def test_unusable_discovered_version_stops_before_download(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a version with path segments is refused before any write."""
        # Captures everything between the markers, separators included.
        recipe_path = _web_scrape_recipe(
            create_yaml_file, version_pattern=r"app-v(.+)-installer"
        )
        html_content = '<a href="/app-v2.0/stable-installer.msi">Download</a>'
        state_dir = tmp_test_dir / "state"

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)
            with patch("napt.discovery.base.download_file") as mock_download:
                with pytest.raises(ConfigError, match="cannot be used as a folder"):
                    discover_recipe(
                        recipe_path,
                        tmp_test_dir,
                        stateless=True,
                        state_dir=state_dir,
                    )

        mock_download.assert_not_called()
        assert not state_dir.exists()
