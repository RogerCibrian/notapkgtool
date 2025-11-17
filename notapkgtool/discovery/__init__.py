# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Discovery strategies for NAPT.

This package provides a pluggable strategy pattern for discovering application
versions and downloading installers from various sources. Strategies are divided
into two types: version-first (can determine version without downloading) and
file-first (must download to extract version).

Strategy Pattern:
    Discovery strategies implement one of two approaches:

VERSION-FIRST (api_github, api_json, web_scrape):
  - Implement get_version_info() -> VersionInfo
  - Can determine version and download URL without downloading installer
  - Core orchestration checks version first, then decides whether to download
  - Enables zero-bandwidth update checks when version unchanged

FILE-FIRST (url_download):
  - Implement discover_version() -> tuple[DiscoveredVersion, Path, str, dict]
  - Must download installer to extract version from file metadata
  - Uses HTTP ETag conditional requests for efficiency

The strategy registry allows dynamic lookup based on the strategy name
in the recipe configuration.

Available Strategies:
    url_download : UrlDownloadStrategy (FILE-FIRST)
        Download from a fixed URL and extract version from the file itself.
        Supports MSI ProductVersion extraction. Uses ETag caching.
    api_github : ApiGithubStrategy (VERSION-FIRST)
        Fetch from GitHub releases API and extract version from tags.
        Fast API-based version checks (~100ms).
    api_json : ApiJsonStrategy (VERSION-FIRST)
        Query JSON API endpoints for version and download URL.
        Fast API-based version checks (~100ms).
    web_scrape : WebScrapeStrategy (VERSION-FIRST)
        Scrape vendor download pages to find links and extract versions.
        Works for vendors without APIs or static URLs.

Example:
    Register and use a custom strategy:

        from notapkgtool.discovery import get_strategy
        from pathlib import Path

        # Get a strategy by name (auto-registered on import)
        strategy = get_strategy("url_download")

        # Use it to discover a version
        app_config = {
            "source": {
                "strategy": "url_download",
                "url": "https://example.com/app.msi",
                "version": {"type": "msi"},
            }
        }

        discovered, file_path, sha256 = strategy.discover_version(
            app_config, Path("./downloads")
        )
        print(f"Version: {discovered.version}")

"""

# Import strategy modules to trigger self-registration
from . import (
    api_github,  # noqa: F401
    api_json,  # noqa: F401
    url_download,  # noqa: F401
    web_scrape,  # noqa: F401
)
from .base import DiscoveryStrategy, get_strategy

__all__ = ["DiscoveryStrategy", "get_strategy"]
