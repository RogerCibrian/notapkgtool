"""
Pytest configuration and shared fixtures for NAPT tests.

This module provides reusable fixtures and test utilities used across
the test suite.

Fixture Scopes
--------------
- function: Created per test (default) - for unit tests
- session: Created once per test session - for expensive operations like downloads
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
        "app": {
            "name": "Test App",
            "id": "test-app",
            "source": {
                "strategy": "url_download",
                "url": "https://example.com/installer.msi",
            },
            "psadt": {
                "app_vars": {
                    "AppName": "Test App",
                    "AppVersion": "${discovered_version}",
                },
            },
        },
    }


@pytest.fixture
def sample_org_defaults() -> dict[str, Any]:
    """Provide sample organization defaults."""
    return {
        "apiVersion": "napt/v1",
        "defaults": {
            "comparator": "semver",
            "psadt": {
                "release": "latest",
                "cache_dir": "cache/psadt",
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


# =============================================================================
# Unit Test Fixtures (Fast, Mocked)
# =============================================================================


@pytest.fixture
def fake_psadt_template(tmp_path: Path) -> Path:
    """
    Create minimal fake PSADT Template_v4 structure for unit tests.

    Fast fixture for testing logic without real PSADT files.
    Use for: Unit tests that need basic PSADT structure.

    Returns
    -------
    Path
        Path to fake PSADT cache directory (contains PSAppDeployToolkit/).
    """
    cache_dir = tmp_path / "psadt_cache" / "4.1.7"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Create minimal v4 template structure
    (cache_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"fake exe")
    (cache_dir / "Invoke-AppDeployToolkit.ps1").write_text("# fake template")

    # PSAppDeployToolkit module
    psadt_dir = cache_dir / "PSAppDeployToolkit"
    psadt_dir.mkdir(parents=True)
    (psadt_dir / "PSAppDeployToolkit.psd1").write_text("@{}")
    (psadt_dir / "PSAppDeployToolkit.psm1").write_text("# module")

    # Assets
    assets_dir = cache_dir / "Assets"
    assets_dir.mkdir()
    (assets_dir / "AppIcon.png").write_bytes(b"fake icon")
    (assets_dir / "Banner.Classic.png").write_bytes(b"fake banner")

    # Other directories
    (cache_dir / "Files").mkdir()
    (cache_dir / "Config").mkdir()
    (cache_dir / "Strings").mkdir()
    (cache_dir / "SupportFiles").mkdir()
    (cache_dir / "PSAppDeployToolkit.Extensions").mkdir()

    return cache_dir


@pytest.fixture
def fake_brand_pack(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """
    Create fake brand pack for testing branding logic.

    Returns
    -------
    tuple[Path, dict]
        (brand_dir, config) - Brand directory path and matching config dict.
    """
    brand_dir = tmp_path / "brand_pack"
    brand_dir.mkdir()

    # Create brand assets
    (brand_dir / "AppIcon.png").write_bytes(b"custom icon data")
    (brand_dir / "Banner.Classic.png").write_bytes(b"custom banner data")

    config = {
        "defaults": {
            "psadt": {
                "brand_pack": {
                    "path": str(brand_dir),
                    "mappings": [
                        {"source": "AppIcon.*", "target": "Assets/AppIcon"},
                        {
                            "source": "Banner.Classic.*",
                            "target": "Assets/Banner.Classic",
                        },
                    ],
                }
            }
        }
    }

    return brand_dir, config


# =============================================================================
# Integration Test Fixtures (Real Data, Cached)
# =============================================================================


@pytest.fixture(scope="session")
def real_psadt_cache_dir(tmp_path_factory) -> Path:
    """
    Download and cache real PSADT Template_v4 once per test session.

    This fixture downloads actual PSADT from GitHub and caches it for
    all integration tests. Expensive operation runs only once.

    Use for: Integration tests validating against real PSADT structure.
    Requires: Network access, marked with @pytest.mark.integration

    Returns
    -------
    Path
        Path to cache directory containing real PSADT versions.
    """
    cache_dir = tmp_path_factory.mktemp("psadt_real_cache")
    return cache_dir


@pytest.fixture(scope="session")
def real_psadt_template(real_psadt_cache_dir: Path) -> Path:
    """
    Provide real PSADT Template_v4 for integration tests (downloaded once).

    Downloads actual Template_v4 from GitHub on first use, then reuses
    the cached version for all subsequent integration tests.

    Use for: Integration tests that need real v4 structure validation.
    Requires: Network access, marked with @pytest.mark.integration

    Returns
    -------
    Path
        Path to real PSADT 4.1.7 template directory.
    """
    version = "4.1.7"
    version_dir = real_psadt_cache_dir / version

    # Only download if not already cached
    if not version_dir.exists():
        from notapkgtool.psadt import get_psadt_release

        # Download real PSADT (this is expensive, runs once per session)
        get_psadt_release(version, real_psadt_cache_dir)

    return version_dir
