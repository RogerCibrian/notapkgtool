"""
Integration tests for NAPT.

Tests end-to-end workflows combining multiple modules:
- Full recipe validation workflow
- Config loading + discovery + download
- CLI command execution
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests_mock

from notapkgtool.core import discover_recipe
from notapkgtool.exceptions import NetworkError
from notapkgtool.versioning import DiscoveredVersion


class TestEndToEndWorkflow:
    """Integration tests for complete workflows."""

    def test_discover_recipe_end_to_end(self, tmp_test_dir, create_yaml_file):
        """Test complete discover_recipe workflow with mocked network."""
        # Create directory structure with defaults
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()
        recipes_dir = tmp_test_dir / "recipes" / "TestVendor"
        recipes_dir.mkdir(parents=True)

        # Create org defaults
        org_defaults = {
            "apiVersion": "napt/v1",
            "defaults": {
                "comparator": "semver",
                "psadt": {"release": "latest", "cache_dir": "cache/psadt"},
            },
        }
        org_path = defaults_dir / "org.yaml"
        import yaml

        with org_path.open("w") as f:
            yaml.dump(org_defaults, f)

        # Create recipe
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "Test App",
                "id": "test-app",
                "source": {
                    "strategy": "url_download",
                    "url": "https://example.com/installer.msi",
                },
            },
        }
        recipe_path = recipes_dir / "testapp.yaml"
        with recipe_path.open("w") as f:
            yaml.dump(recipe_data, f)

        output_dir = tmp_test_dir / "downloads"

        # Mock download and version extraction
        fake_msi = b"fake MSI content"
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
                    version="1.2.3", source="msi"
                )

                result = discover_recipe(recipe_path, output_dir)

        # Verify complete workflow results
        assert result.app_name == "Test App"
        assert result.version == "1.2.3"
        assert result.strategy == "url_download"
        assert result.status == "success"

        # Verify file was downloaded
        downloaded_file = output_dir / "installer.msi"
        assert downloaded_file.exists()
        assert downloaded_file.read_bytes() == fake_msi


class TestConfigAndDiscoveryIntegration:
    """Tests integration between config loading and discovery."""

    def test_config_provides_discovery_params(self, tmp_test_dir, create_yaml_file):
        """Test that loaded config provides correct params to discovery."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "App",
                "id": "app-id",
                "source": {
                    "strategy": "url_download",
                    "url": "https://test.com/app.msi",
                },
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with requests_mock.Mocker() as m:
            m.get(
                "https://test.com/app.msi",
                content=b"fake",
                headers={"Content-Length": "4"},
            )

            with patch(
                "notapkgtool.discovery.url_download.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="1.0.0", source="msi"
                )

                result = discover_recipe(recipe_path, tmp_test_dir)

                # Verify config was properly passed to discovery
                assert result.version == "1.0.0"


class TestErrorPropagation:
    """Tests that errors propagate correctly through the stack."""

    def test_download_error_propagates(self, tmp_test_dir, create_yaml_file):
        """Test that download errors propagate with context."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "App",
                "source": {
                    "strategy": "url_download",
                    "url": "https://test.com/app.msi",
                },
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with requests_mock.Mocker() as m:
            m.get("https://test.com/app.msi", status_code=404)

            from notapkgtool.exceptions import NetworkError

            with pytest.raises(NetworkError, match="download failed"):
                discover_recipe(recipe_path, tmp_test_dir)

    def test_version_extraction_error_propagates(self, tmp_test_dir, create_yaml_file):
        """Test that version extraction errors propagate with context."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "app": {
                "name": "App",
                "source": {
                    "strategy": "url_download",
                    "url": "https://test.com/app.msi",
                },
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with requests_mock.Mocker() as m:
            m.get(
                "https://test.com/app.msi",
                content=b"bad msi",
                headers={"Content-Length": "7"},
            )

            with patch(
                "notapkgtool.discovery.url_download.version_from_msi_product_version"
            ) as mock_extract:
                mock_extract.side_effect = NetworkError("Invalid MSI")

                with pytest.raises(NetworkError, match="Failed to extract"):
                    discover_recipe(recipe_path, tmp_test_dir)
