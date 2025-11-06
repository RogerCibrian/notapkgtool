"""
Discovery strategies for NAPT.

This package provides a pluggable strategy pattern for discovering application
versions and downloading installers from various sources. Each strategy knows
how to fetch a specific type of source (static URL, GitHub releases, JSON API,
etc.) and extract version information.

Strategy Pattern
----------------
Discovery strategies implement the DiscoveryStrategy protocol which defines
a single method: discover_version(app_config, output_dir). The strategy
registry allows dynamic lookup and instantiation based on the strategy name
in the recipe configuration.

Available Strategies
--------------------
http_static : HttpStaticStrategy
    Download from a fixed URL and extract version from the file itself.
    Supports MSI ProductVersion extraction.
url_regex : UrlRegexStrategy
    Extract version from URL patterns using regex, then download.
    Fast version discovery without downloading first.
github_release : GithubReleaseStrategy
    Fetch from GitHub releases API and extract version from tags.
    Supports asset pattern matching and authentication.
http_json : HttpJsonStrategy
    Query JSON API endpoints for version and download URL.
    Supports JSONPath navigation and custom headers.

Public API
----------
DiscoveryStrategy : Protocol
    Protocol that all discovery strategies must implement.
get_strategy : function
    Get a discovery strategy instance by name from the registry.

Example
-------
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
