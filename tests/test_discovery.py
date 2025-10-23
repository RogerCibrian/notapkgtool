"""
Tests for notapkgtool.discovery module.

Tests discovery strategies including:
- Strategy registry
- HTTP static strategy
- Version extraction from downloaded files
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests_mock

from notapkgtool.discovery.base import get_strategy, register_strategy
from notapkgtool.discovery.http_static import HttpStaticStrategy
from notapkgtool.versioning import DiscoveredVersion


class TestStrategyRegistry:
    """Tests for discovery strategy registration and lookup."""

    def test_get_http_static_strategy(self):
        """Test that http_static strategy can be retrieved."""
        strategy = get_strategy("http_static")
        assert isinstance(strategy, HttpStaticStrategy)

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
            
            with patch("notapkgtool.discovery.http_static.version_from_msi_product_version") as mock_extract:
                mock_extract.return_value = DiscoveredVersion(
                    version="1.2.3",
                    source="msi_product_version_from_file"
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
            
            with patch("notapkgtool.discovery.http_static.version_from_msi_product_version") as mock_extract:
                mock_extract.side_effect = RuntimeError("Invalid MSI")
                
                with pytest.raises(RuntimeError, match="Failed to extract MSI ProductVersion"):
                    strategy.discover_version(app_config, tmp_test_dir)

