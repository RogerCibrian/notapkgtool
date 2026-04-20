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

"""Discovery package: registry, strategies, and orchestration.

Two flows feed into
[discover_recipe][napt.discovery.manager.discover_recipe]:

- **Registered strategies** (api_github, api_json, web_scrape) implement
    [DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy] — they
    discover a version and its download URL without touching the file.
    The orchestrator runs the result through
    [resolve_with_cache][napt.discovery.base.resolve_with_cache] to
    decide whether to skip the download.
- **url_download** is a separate flow at
    [run_url_download][napt.discovery.url_download.run_url_download]. It
    downloads the file with HTTP conditional requests and extracts the
    version from the file's metadata. It is not a registered strategy
    because it cannot determine the version without the file.

The discovery orchestrator dispatches to one of the two flows based
on the recipe's ``discovery.strategy`` value.

Built-in strategies:
    - [api_github][napt.discovery.api_github.ApiGithubStrategy]:
        queries the GitHub releases API for the latest tag.
    - [api_json][napt.discovery.api_json.ApiJsonStrategy]:
        extracts version and download URL from a JSON endpoint.
    - [web_scrape][napt.discovery.web_scrape.WebScrapeStrategy]:
        parses a vendor download page for both fields.

"""

from . import (
    api_github,  # noqa: F401
    api_json,  # noqa: F401
    web_scrape,  # noqa: F401
)
from .base import DiscoveryStrategy, get_strategy
from .manager import discover_recipe

__all__ = ["DiscoveryStrategy", "discover_recipe", "get_strategy"]
