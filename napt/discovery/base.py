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

"""Discovery strategy protocol, registry, and shared helpers.

A *discovery strategy* answers a single question: "what is the latest
version of this app, and where can it be downloaded from?" Strategies
return that answer as a [RemoteVersion][napt.discovery.base.RemoteVersion]
dataclass. They do not download files or touch the cache themselves;
the orchestrator does.

Built-in strategies:
    - api_github: queries the GitHub releases API for the latest tag.
    - api_json: extracts version and download URL from a JSON endpoint.
    - web_scrape: parses a vendor download page for both fields.

The fourth flow (``url_download``) is *not* a registered strategy. It
downloads a fixed URL and extracts the version from the file itself,
which is a different shape than the strategies in this module. The
discovery orchestrator dispatches to that flow directly when a recipe
uses ``strategy: url_download``.

Design Philosophy:
    - Strategies are ``typing.Protocol`` types. Implementations are
        matched structurally; no inheritance is required.
    - Strategies are pure functions of configuration. They have no state,
        no I/O of files, and no awareness of the cache.
    - Registration is a side effect of importing each strategy module.
    - The [resolve_with_cache][napt.discovery.base.resolve_with_cache]
        helper turns a [RemoteVersion][napt.discovery.base.RemoteVersion]
        into a [StrategyResult][napt.discovery.base.StrategyResult] by
        checking the cache and downloading if needed. Strategies don't
        call it themselves; the orchestrator does.

Example:
    Adding a new strategy to the codebase:
        ```python
        from napt.discovery.base import (
            RemoteVersion, register_strategy,
        )

        class GitlabReleasesStrategy:
            def discover(self, app_config):
                # Query GitLab API and parse the response...
                return RemoteVersion(
                    version="1.2.3",
                    download_url="https://gitlab.example.com/.../installer.msi",
                    source="gitlab_releases",
                )

            def validate_config(self, app_config):
                errors = []
                if "project" not in app_config.get("discovery", {}):
                    errors.append("Missing required field: discovery.project")
                return errors

        register_strategy("gitlab_releases", GitlabReleasesStrategy)
        ```

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from napt.download import download_file
from napt.exceptions import ConfigError
from napt.logging import get_global_logger
from napt.versioning import is_newer


@dataclass(frozen=True)
class RemoteVersion:
    """Version and download URL discovered from a remote source.

    Returned by every [DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy]
    implementation. The orchestrator passes this to
    [resolve_with_cache][napt.discovery.base.resolve_with_cache] to decide
    whether the file needs to be re-downloaded.

    Attributes:
        version: Raw version string extracted from the remote source
            (for example, ``"140.0.7339.128"``).
        download_url: URL the installer can be fetched from.
        source: Name of the strategy that produced this result, used
            for logging and result reporting (for example, ``"api_github"``).
    """

    version: str
    download_url: str
    source: str


@dataclass(frozen=True)
class StrategyResult:
    """Resolved discovery result, ready to be saved to state.

    Returned by both the version-first flow (via
    [resolve_with_cache][napt.discovery.base.resolve_with_cache]) and the
    url_download flow. Captures everything the orchestrator needs to
    update the state cache and build a public
    [DiscoverResult][napt.results.DiscoverResult].

    Attributes:
        version: Version string for the resolved file.
        version_source: Strategy name that produced this version
            (for example, ``"api_github"`` or ``"url_download"``).
        file_path: Path to the resolved installer on disk. This is either
            a freshly downloaded file or a previously cached file when the
            cache was reused.
        sha256: SHA-256 hex digest of the resolved file.
        headers: HTTP response headers from the download. Empty when the
            cache was reused without a network call. Used to persist
            ``ETag`` / ``Last-Modified`` for the next conditional request.
        download_url: URL the file came from. Stored in state so that
            future runs know where to re-fetch from if needed.
        cached: True when the file was reused from cache; False when it
            was downloaded.
    """

    version: str
    version_source: str
    file_path: Path
    sha256: str
    headers: dict[str, str]
    download_url: str
    cached: bool


class DiscoveryStrategy(Protocol):
    """Protocol for version discovery strategies.

    A strategy queries a remote source (API, web page, etc.) and returns
    the latest version plus its download URL. Strategies do not download
    files, touch the cache, or write to disk. Those concerns belong to
    the orchestrator.

    Implementations need only a ``discover`` and a ``validate_config``
    method with the signatures below.
    """

    def discover(self, app_config: dict[str, Any]) -> RemoteVersion:
        """Discovers the latest version and its download URL.

        Args:
            app_config: Merged recipe configuration dict.

        Returns:
            Latest version, the URL it can be downloaded from, and the
            strategy's own name as the source identifier.

        Raises:
            ConfigError: On missing or invalid required configuration.
            NetworkError: On HTTP failures or version-extraction errors.

        """
        ...

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """Validates strategy-specific configuration fields without network calls.

        Implementations should check field presence, types, and format only.

        Args:
            app_config: Merged recipe configuration dict.

        Returns:
            Human-readable error messages. Empty when configuration is valid.

        """
        ...


_STRATEGY_REGISTRY: dict[str, type[DiscoveryStrategy]] = {}


def register_strategy(name: str, strategy_class: type[DiscoveryStrategy]) -> None:
    """Registers a discovery strategy by name in the global registry.

    Strategies call this at module import time so they're available when
    the orchestrator looks them up. Registering the same name twice
    overwrites the previous entry (intentional, to allow test
    monkey-patching).

    Args:
        name: Strategy name. This is the value used in recipe YAML files
            under ``discovery.strategy``. Use lowercase with underscores.
        strategy_class: Class implementing
            [DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy].
            Type checkers verify protocol compliance statically.

    Note:
        ``url_download`` is intentionally not registered here. It runs
        through a separate code path in the orchestrator because it
        downloads the file before it can determine the version, which
        does not fit the version-first contract.

    """
    _STRATEGY_REGISTRY[name] = strategy_class


def get_strategy(name: str) -> DiscoveryStrategy:
    """Returns a discovery strategy instance by name from the registry.

    Strategies are instantiated on-demand because they are stateless. The
    strategy's module must already be imported for registration to have
    happened.

    Args:
        name: Registered strategy name. Case-sensitive.

    Returns:
        New instance of the requested strategy.

    Raises:
        ConfigError: If the name is not registered. The message lists
            the available strategies for troubleshooting.

    """
    if name not in _STRATEGY_REGISTRY:
        available = ", ".join(_STRATEGY_REGISTRY.keys())
        raise ConfigError(
            f"Unknown discovery strategy: {name!r}. Available: {available or '(none)'}"
        )
    return _STRATEGY_REGISTRY[name]()


def resolve_with_cache(
    info: RemoteVersion,
    app_config: dict[str, Any],
    output_dir: Path,
    cache: dict[str, Any] | None,
) -> StrategyResult:
    """Resolves a [RemoteVersion][napt.discovery.base.RemoteVersion] to a [StrategyResult][napt.discovery.base.StrategyResult].

    Implements the version-first fast path: when the discovered version
    matches the cached version and the cached file still exists on disk,
    the download is skipped entirely. Otherwise the file is downloaded
    fresh from ``info.download_url``.

    Args:
        info: Version and download URL produced by a strategy's
            [discover][napt.discovery.base.DiscoveryStrategy.discover] call.
        app_config: Merged recipe configuration. Used to read ``id``
            for the per-app download subdirectory.
        output_dir: Base directory to download into. Files land in
            ``output_dir / app_id``.
        cache: Cached state for this recipe (``known_version``,
            ``file_path``, ``sha256``), or ``None`` when no prior state
            exists or stateless mode is on.

    Returns:
        Resolved version, file path, and download metadata. The
        ``cached`` field indicates whether the download was skipped.

    Raises:
        NetworkError: On download failures.

    """
    logger = get_global_logger()
    app_id = app_config["id"]

    if cache and not is_newer(info.version, cache.get("known_version")):
        cached_path_str = cache.get("file_path")
        cached_sha = cache.get("sha256")
        if cached_path_str and cached_sha:
            cached_path = Path(cached_path_str)
            if cached_path.exists():
                logger.info(
                    "CACHE",
                    f"Version {info.version} unchanged, using cached file",
                )
                return StrategyResult(
                    version=info.version,
                    version_source=info.source,
                    file_path=cached_path,
                    sha256=cached_sha,
                    headers={},
                    download_url=info.download_url,
                    cached=True,
                )
            logger.warning(
                "CACHE",
                f"Cached file {cached_path} not found, re-downloading",
            )

    if cache and cache.get("known_version"):
        logger.info(
            "DISCOVERY",
            f"Version changed: {cache.get('known_version')} -> {info.version}",
        )

    dl = download_file(info.download_url, output_dir / app_id)
    return StrategyResult(
        version=info.version,
        version_source=info.source,
        file_path=dl.file_path,
        sha256=dl.sha256,
        headers=dl.headers,
        download_url=info.download_url,
        cached=False,
    )
