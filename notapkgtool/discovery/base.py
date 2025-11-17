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

"""Discovery strategy base protocol and registry for NAPT.

This module defines the foundational components for the discovery system:

- DiscoveryStrategy protocol: Interface that all strategies must implement
- Strategy registry: Global dict mapping strategy names to implementations
- Registration and lookup functions: register_strategy() and get_strategy()

The discovery system uses a strategy pattern to support multiple ways
of obtaining application installers and their versions:

- url_download: Direct download from a static URL (FILE-FIRST)
- web_scrape: Scrape vendor download pages to find links and extract versions
    (VERSION-FIRST)
- api_github: Fetch from GitHub releases API (VERSION-FIRST)
- api_json: Query JSON API endpoints for version and download URL (VERSION-FIRST)

Design Philosophy:
    - Strategies are Protocol classes (structural subtyping, not inheritance)
    - Registration happens at module import time (strategies self-register)
    - Registry is a simple dict (no complex dependency injection needed)
    - Each strategy is stateless and can be instantiated on-demand

Protocol Benefits:

Using typing.Protocol instead of ABC allows:

- Duck typing: Classes don't need explicit inheritance
- Better IDE support: Type checkers verify interface compliance
- Flexibility: Third-party code can add strategies without touching base

Example:
    Implementing a custom strategy:
        ```python
        from notapkgtool.discovery.base import register_strategy, DiscoveryStrategy
        from pathlib import Path
        from typing import Any
        from notapkgtool.versioning.keys import DiscoveredVersion

        class MyCustomStrategy:
            def discover_version(
                self, app_config: dict[str, Any], output_dir: Path
            ) -> tuple[DiscoveredVersion, Path, str]:
                # Implement your discovery logic here
                ...

        # Register it (typically at module import)
        register_strategy("my_custom", MyCustomStrategy)

        # Now it can be used in recipes:
        # source:
        #   strategy: my_custom
        #   ...
        ```

"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from notapkgtool.exceptions import ConfigError
from notapkgtool.versioning.keys import DiscoveredVersion

# -------------------------------
# Strategy Protocol
# -------------------------------


class DiscoveryStrategy(Protocol):
    """Protocol for version discovery strategies.

    Each strategy must implement discover_version() which downloads
    and extracts version information based on the app config.

    Strategies may optionally implement validate_config() to provide
    strategy-specific configuration validation without network calls.
    """

    def discover_version(
        self, app_config: dict[str, Any], output_dir: Path
    ) -> tuple[DiscoveredVersion, Path, str, dict]:
        """Discover and download an application version.

        Args:
            app_config: The app configuration from the recipe
                (`config["apps"][0]`).
            output_dir: Directory to download the installer to.

        Returns:
            A tuple (discovered_version, file_path, sha256, headers), where
                discovered_version is the version information, file_path is
                the path to the downloaded file, sha256 is the SHA-256 hash,
                and headers contains HTTP response headers for caching.

        Raises:
            ValueError: On discovery or download failures.
            RuntimeError: On discovery or download failures.

        """
        ...

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """Validate strategy-specific configuration (optional).

        This method validates the app configuration for strategy-specific
        requirements without making network calls or downloading files.
        Useful for quick feedback during recipe development.

        Args:
            app_config: The app configuration from the recipe
                (`config["apps"][0]`).

        Returns:
            List of error messages. Empty list if configuration is valid.
            Each error should be a human-readable description of the issue.

        Example:
            Check required fields:
                ```python
                def validate_config(self, app_config):
                    errors = []
                    source = app_config.get("source", {})
                    if "url" not in source:
                        errors.append("Missing required field: source.url")
                    return errors
                ```

        Note:
            This method is optional; strategies without it will skip validation.
            Should NOT make network calls or download files. Should check field
            presence, types, and format only. Used by 'napt validate' command
            for fast recipe checking.

        """
        ...


# -------------------------------
# Strategy Registry
# -------------------------------

_STRATEGY_REGISTRY: dict[str, type[DiscoveryStrategy]] = {}


def register_strategy(name: str, strategy_class: type[DiscoveryStrategy]) -> None:
    """Register a discovery strategy by name in the global registry.

    This function should be called when a strategy module is imported,
    typically at module level. Registering the same name twice will
    overwrite the previous registration (allows monkey-patching for tests).

    Args:
        name: Strategy name (e.g., "url_download"). This is the value
            used in recipe YAML files under source.strategy. Names should be
            lowercase with underscores for readability.
        strategy_class: The strategy class to
            register. Must implement the DiscoveryStrategy protocol (have a
            discover_version method with the correct signature).

    Example:
        Register at module import time:
            ```python
            # In discovery/my_strategy.py
            from .base import register_strategy

            class MyStrategy:
                def discover_version(self, app_config, output_dir):
                    ...

            register_strategy("my_strategy", MyStrategy)
            ```

    Note:
        No validation is performed at registration time. Type checkers will
        verify protocol compliance at static analysis time. Runtime errors
        occur at strategy instantiation or invocation.

    """
    _STRATEGY_REGISTRY[name] = strategy_class


def get_strategy(name: str) -> DiscoveryStrategy:
    """Get a discovery strategy instance by name from the global registry.

    The strategy is instantiated on-demand (strategies are stateless, so
    a new instance is created for each call). The strategy module must
    have been imported first for registration to occur.

    Args:
        name: Strategy name (e.g., "url_download"). Must exactly match
            a name registered via register_strategy(). Case-sensitive.

    Returns:
        A new instance of the requested strategy, ready
            to use.

    Raises:
        ConfigError: If the strategy name is not registered. The error message
            includes a list of available strategies for troubleshooting.

    Example:
        Get and use a strategy:
            ```python
            from notapkgtool.discovery import get_strategy
            strategy = get_strategy("url_download")
            # Use strategy.discover_version(...)
            ```

        Handle unknown strategy:
            ```python
            try:
                strategy = get_strategy("nonexistent")
            except ConfigError as e:
                print(f"Strategy not found: {e}")
            ```

    Note:
        Strategies must be registered before they can be retrieved. The
        url_download strategy is auto-registered when imported. New strategies
        can be added by creating a module and registering.

    """
    if name not in _STRATEGY_REGISTRY:
        available = ", ".join(_STRATEGY_REGISTRY.keys())
        raise ConfigError(
            f"Unknown discovery strategy: {name!r}. Available: {available or '(none)'}"
        )
    return _STRATEGY_REGISTRY[name]()
