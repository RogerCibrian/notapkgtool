"""
Discovery strategy base protocol and registry for NAPT.

This module defines the foundational components for the discovery system:
  - DiscoveryStrategy protocol: Interface that all strategies must implement
  - Strategy registry: Global dict mapping strategy names to implementations
  - Registration and lookup functions: register_strategy() and get_strategy()

The discovery system uses a strategy pattern to support multiple ways
of obtaining application installers and their versions:
  - http_static: Direct download from a static URL
  - url_regex: Parse version from URL patterns (future)
  - github_release: Fetch from GitHub releases (future)
  - http_json: Query JSON API endpoints (future)

Design Philosophy
-----------------
- Strategies are Protocol classes (structural subtyping, not inheritance)
- Registration happens at module import time (strategies self-register)
- Registry is a simple dict (no complex dependency injection needed)
- Each strategy is stateless and can be instantiated on-demand

Protocol Benefits
-----------------
Using typing.Protocol instead of ABC allows:
  - Duck typing: Classes don't need explicit inheritance
  - Better IDE support: Type checkers verify interface compliance
  - Flexibility: Third-party code can add strategies without touching base

Example
-------
Implementing a custom strategy:

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
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from notapkgtool.versioning.keys import DiscoveredVersion

# -------------------------------
# Strategy Protocol
# -------------------------------


class DiscoveryStrategy(Protocol):
    """
    Protocol for version discovery strategies.

    Each strategy must implement discover_version() which downloads
    and extracts version information based on the app config.
    """

    def discover_version(
        self, app_config: dict[str, Any], output_dir: Path
    ) -> tuple[DiscoveredVersion, Path, str, dict]:
        """
        Discover and download an application version.

        Parameters
        ----------
        app_config : dict
            The app configuration from the recipe (config["apps"][0]).
        output_dir : Path
            Directory to download the installer to.

        Returns
        -------
        tuple[DiscoveredVersion, Path, str, dict]
            - DiscoveredVersion: version info
            - Path: path to downloaded file
            - str: SHA-256 hash of the file
            - dict: HTTP response headers (for ETag/Last-Modified caching)

        Raises
        ------
        ValueError, RuntimeError
            On discovery or download failures.
        """
        ...


# -------------------------------
# Strategy Registry
# -------------------------------

_STRATEGY_REGISTRY: dict[str, type[DiscoveryStrategy]] = {}


def register_strategy(name: str, strategy_class: type[DiscoveryStrategy]) -> None:
    """
    Register a discovery strategy by name in the global registry.

    This function should be called when a strategy module is imported,
    typically at module level. Registering the same name twice will
    overwrite the previous registration (allows monkey-patching for tests).

    Parameters
    ----------
    name : str
        Strategy name (e.g., "http_static"). This is the value used in
        recipe YAML files under source.strategy. Names should be lowercase
        with underscores for readability.
    strategy_class : type[DiscoveryStrategy]
        The strategy class to register. Must implement the DiscoveryStrategy
        protocol (have a discover_version method with the correct signature).

    Examples
    --------
    Register at module import time:

        # In discovery/my_strategy.py
        from .base import register_strategy

        class MyStrategy:
            def discover_version(self, app_config, output_dir):
                ...

        register_strategy("my_strategy", MyStrategy)

    Notes
    -----
    - No validation is performed at registration time
    - Type checkers will verify protocol compliance at static analysis time
    - Runtime errors occur at strategy instantiation or invocation
    """
    _STRATEGY_REGISTRY[name] = strategy_class


def get_strategy(name: str) -> DiscoveryStrategy:
    """
    Get a discovery strategy instance by name from the global registry.

    The strategy is instantiated on-demand (strategies are stateless, so
    a new instance is created for each call). The strategy module must
    have been imported first for registration to occur.

    Parameters
    ----------
    name : str
        Strategy name (e.g., "http_static"). Must exactly match a name
        registered via register_strategy(). Case-sensitive.

    Returns
    -------
    DiscoveryStrategy
        A new instance of the requested strategy, ready to use.

    Raises
    ------
    ValueError
        If the strategy name is not registered. The error message includes
        a list of available strategies for troubleshooting.

    Examples
    --------
    Get and use a strategy:

        >>> from notapkgtool.discovery import get_strategy
        >>> strategy = get_strategy("http_static")
        >>> # Use strategy.discover_version(...)

    Handle unknown strategy:

        >>> try:
        ...     strategy = get_strategy("nonexistent")
        ... except ValueError as e:
        ...     print(f"Strategy not found: {e}")

    Notes
    -----
    - Strategies must be registered before they can be retrieved
    - The http_static strategy is auto-registered when imported
    - New strategies can be added by creating a module and registering
    """
    if name not in _STRATEGY_REGISTRY:
        available = ", ".join(_STRATEGY_REGISTRY.keys())
        raise ValueError(
            f"Unknown discovery strategy: {name!r}. Available: {available or '(none)'}"
        )
    return _STRATEGY_REGISTRY[name]()
