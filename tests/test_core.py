"""
Tests for notapkgtool.core module.

Tests core orchestration including:
- Recipe validation workflow
- check_recipe function
- Error handling
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from notapkgtool.core import check_recipe
from notapkgtool.versioning import DiscoveredVersion


class TestCheckRecipe:
    """Tests for check_recipe orchestration function."""

    def test_check_recipe_success(self, tmp_test_dir, create_yaml_file):
        """Test successful recipe check workflow."""
        # Create a minimal recipe
        recipe_data = {
            "apiVersion": "napt/v1",
            "apps": [
                {
                    "name": "Test App",
                    "id": "test-app",
                    "source": {
                        "strategy": "http_static",
                        "url": "https://example.com/test.msi",
                        "version": {"type": "msi_product_version_from_file"},
                    },
                }
            ],
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)
        
        # Mock the discovery strategy
        with patch("notapkgtool.core.get_strategy") as mock_get_strategy:
            mock_strategy = mock_get_strategy.return_value
            mock_strategy.discover_version.return_value = (
                DiscoveredVersion(version="1.2.3", source="msi_product_version_from_file"),
                tmp_test_dir / "test.msi",
                "abc123" * 8,  # fake SHA-256
            )
            
            result = check_recipe(recipe_path, tmp_test_dir)
        
        assert result["app_name"] == "Test App"
        assert result["app_id"] == "test-app"
        assert result["strategy"] == "http_static"
        assert result["version"] == "1.2.3"
        assert result["version_source"] == "msi_product_version_from_file"
        assert result["status"] == "success"
        assert "file_path" in result
        assert "sha256" in result

    def test_check_recipe_no_apps_raises(self, tmp_test_dir, create_yaml_file):
        """Test that recipe with no apps raises ValueError."""
        recipe_data = {"apiVersion": "napt/v1", "apps": []}
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)
        
        with pytest.raises(ValueError, match="No apps defined"):
            check_recipe(recipe_path, tmp_test_dir)

    def test_check_recipe_missing_strategy_raises(self, tmp_test_dir, create_yaml_file):
        """Test that missing strategy raises ValueError."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "apps": [
                {
                    "name": "Test App",
                    "source": {},  # No strategy
                }
            ],
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)
        
        with pytest.raises(ValueError, match="No 'source.strategy' defined"):
            check_recipe(recipe_path, tmp_test_dir)

    def test_check_recipe_unknown_strategy_raises(self, tmp_test_dir, create_yaml_file):
        """Test that unknown strategy raises ValueError."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "apps": [
                {
                    "name": "Test App",
                    "source": {"strategy": "nonexistent_strategy"},
                }
            ],
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)
        
        with pytest.raises(ValueError, match="Unknown discovery strategy"):
            check_recipe(recipe_path, tmp_test_dir)

    def test_check_recipe_missing_file_raises(self, tmp_test_dir):
        """Test that missing recipe file raises error."""
        nonexistent = tmp_test_dir / "nonexistent.yaml"
        
        with pytest.raises(FileNotFoundError):
            check_recipe(nonexistent, tmp_test_dir)
