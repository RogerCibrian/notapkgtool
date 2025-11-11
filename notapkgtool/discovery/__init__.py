"""Discovery strategies for NAPT.

This package provides a pluggable strategy pattern for discovering application
versions and downloading installers from various sources. Strategies are divided
into two types: version-first (can determine version without downloading) and
file-first (must download to extract version).

Strategy Pattern:
    Discovery strategies implement one of two approaches:

VERSION-FIRST (url_regex, github_release, http_json):
  - Implement get_version_info() -> VersionInfo
  - Can determine version and download URL without downloading installer
  - Core orchestration checks version first, then decides whether to download
  - Enables zero-bandwidth update checks when version unchanged

FILE-FIRST (http_static):
  - Implement discover_version() -> tuple[DiscoveredVersion, Path, str, dict]
  - Must download installer to extract version from file metadata
  - Uses HTTP ETag conditional requests for efficiency

The strategy registry allows dynamic lookup based on the strategy name
in the recipe configuration.

Available Strategies:
    http_static : HttpStaticStrategy (FILE-FIRST)
        Download from a fixed URL and extract version from the file itself.
        Supports MSI ProductVersion extraction. Uses ETag caching.
    url_regex : UrlRegexStrategy (VERSION-FIRST)
        Extract version from URL patterns using regex.
        Instant version checks with zero network calls.
    github_release : GithubReleaseStrategy (VERSION-FIRST)
        Fetch from GitHub releases API and extract version from tags.
        Fast API-based version checks (~100ms).
    http_json : HttpJsonStrategy (VERSION-FIRST)
        Query JSON API endpoints for version and download URL.
        Fast API-based version checks (~100ms).

Public API:

- DiscoveryStrategy: Protocol that all discovery strategies must implement
- get_strategy: Get a discovery strategy instance by name from the registry

Example:
    Register and use a custom strategy:

        from notapkgtool.discovery import get_strategy
        from pathlib import Path

        # Get a strategy by name (auto-registered on import)
        strategy = get_strategy("http_static")

        # Use it to discover a version
        app_config = {
            "source": {
                "strategy": "http_static",
                "url": "https://example.com/app.msi",
                "version": {"type": "msi_product_version_from_file"},
            }
        }

        discovered, file_path, sha256 = strategy.discover_version(
            app_config, Path("./downloads")
        )
        print(f"Version: {discovered.version}")

"""

# Import strategy modules to trigger self-registration
from . import (
    github_release,  # noqa: F401
    http_json,  # noqa: F401
    http_static,  # noqa: F401
    url_regex,  # noqa: F401
)
from .base import DiscoveryStrategy, get_strategy

__all__ = ["DiscoveryStrategy", "get_strategy"]
