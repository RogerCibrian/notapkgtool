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

"""Explicit registry of discovery strategies.

Maps each ``discovery.strategy`` recipe value to the class implementing
it. Dispatch is a plain table lookup: nothing registers itself at import
time, and this module's imports are what pull in the strategy
implementations.

Adding a strategy:
    1. Implement [DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy]
        in a new module under ``napt/discovery/``.
    2. Import the class here and add it to the table.

Note:
    ``url_download`` is intentionally absent from the table. It
    downloads the file before it can determine the version, which does
    not fit the version-first contract, so the discovery orchestrator
    dispatches to
    [run_url_download][napt.discovery.url_download.run_url_download]
    directly.

"""

from __future__ import annotations

from napt.discovery.api_github import ApiGithubStrategy
from napt.discovery.api_json import ApiJsonStrategy
from napt.discovery.base import DiscoveryStrategy
from napt.discovery.web_scrape import WebScrapeStrategy
from napt.exceptions import ConfigError

_STRATEGIES: dict[str, type[DiscoveryStrategy]] = {
    "api_github": ApiGithubStrategy,
    "api_json": ApiJsonStrategy,
    "web_scrape": WebScrapeStrategy,
}


def get_strategy(name: str) -> DiscoveryStrategy:
    """Returns a discovery strategy instance by name.

    Strategies are stateless, so a fresh instance is created on every
    call.

    Args:
        name: Strategy name as written in recipe YAML under
            ``discovery.strategy``. Case-sensitive.

    Returns:
        New instance of the requested strategy.

    Raises:
        ConfigError: If the name is not in the registry. The message
            lists the available strategies for troubleshooting.

    """
    strategy_class = _STRATEGIES.get(name)
    if strategy_class is None:
        available = ", ".join(sorted(_STRATEGIES))
        raise ConfigError(
            f"Unknown discovery strategy: {name!r}. Available: {available}"
        )
    return strategy_class()
