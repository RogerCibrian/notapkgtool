"""
Pytest configuration and shared fixtures for NAPT tests.

This module provides reusable fixtures and test utilities used across
the test suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


@pytest.fixture
def tmp_test_dir(tmp_path: Path) -> Path:
    """
    Provide a temporary directory for test artifacts.
    
    Automatically cleaned up after test completion.
    """
    return tmp_path


@pytest.fixture
def fixtures_dir() -> Path:
    """Provide path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_yaml_path(fixtures_dir: Path) -> Path:
    """Provide path to sample YAML fixture."""
    return fixtures_dir / "test.yaml"


@pytest.fixture
def sample_recipe_data() -> dict[str, Any]:
    """
    Provide sample recipe configuration data.
    
    Returns a complete recipe structure for testing.
    """
    return {
        "apiVersion": "napt/v1",
        "project": "Test Project",
        "apps": [
            {
                "name": "Test App",
                "id": "test-app",
                "source": {
                    "strategy": "http_static",
                    "url": "https://example.com/installer.msi",
                    "version": {
                        "type": "msi_product_version_from_file",
                    },
                },
                "psadt": {
                    "app_vars": {
                        "AppName": "Test App",
                        "AppVersion": "${discovered_version}",
                    },
                },
            }
        ],
    }


@pytest.fixture
def sample_org_defaults() -> dict[str, Any]:
    """Provide sample organization defaults."""
    return {
        "apiVersion": "napt/v1",
        "defaults": {
            "comparator": "semver",
            "psadt": {
                "template_version": "4.1.5",
            },
        },
    }


@pytest.fixture
def create_yaml_file(tmp_test_dir: Path):
    """
    Factory fixture for creating temporary YAML files.
    
    Usage:
        yaml_path = create_yaml_file("test.yaml", {"key": "value"})
    """
    def _create(filename: str, data: dict[str, Any]) -> Path:
        path = tmp_test_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
        return path
    
    return _create


@pytest.fixture
def mock_download_response():
    """
    Provide mock data for download responses.
    
    Returns common test data for HTTP download testing.
    """
    return {
        "content": b"test file content",
        "headers": {
            "Content-Length": "17",
            "ETag": '"abc123"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
        },
    }

