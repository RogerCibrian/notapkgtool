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

"""Discovery pipeline orchestration.

This module owns the top-level [discover_recipe][napt.discovery.manager.discover_recipe]
entry point used by ``napt discover``. It loads the merged configuration,
picks a flow based on the recipe's ``discovery.strategy`` value, persists
the discovery cache for the next run, records the release as a pending
publication candidate in deployment state, and returns the public
[DiscoverResult][napt.results.DiscoverResult].

Two Flows:
    Two flows feed into the same orchestration:

    - **Version-first** (api_github, api_json, web_scrape and any other
        registered [DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy]):
        the strategy returns a
        [RemoteVersion][napt.discovery.base.RemoteVersion], and
        [resolve_with_cache][napt.discovery.base.resolve_with_cache]
        decides whether to skip the download (version unchanged + file
        present) or fetch fresh.
    - **url_download** (handled by
        [run_url_download][napt.discovery.url_download.run_url_download]):
        downloads the file with HTTP conditional headers (``ETag`` /
        ``Last-Modified``) and extracts the version from the file's
        metadata. Not a registered strategy because it cannot determine
        the version without the file.

Both flows return a [StrategyResult][napt.discovery.base.StrategyResult],
which this module unwraps into state-cache fields and the public result.

"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from napt import __version__
from napt.config.loader import load_effective_config
from napt.discovery.base import (
    StrategyResult,
    get_strategy,
    resolve_with_cache,
)
from napt.discovery.url_download import run_url_download
from napt.exceptions import ConfigError
from napt.logging import get_global_logger
from napt.results import DiscoverResult
from napt.state import (
    deployment_state_path,
    load_cache,
    load_deployment_state,
    record_pending,
    save_cache,
    save_deployment_state,
)


def discover_recipe(
    recipe_path: Path,
    output_dir: Path | None = None,
    cache_file: Path | None = None,
    state_dir: Path | None = None,
    stateless: bool = False,
) -> DiscoverResult:
    """Discovers the latest version of an app and resolves its installer.

    Loads the recipe configuration, dispatches to the appropriate
    discovery flow (version-first registered strategy or ``url_download``),
    persists the result to the discovery cache, records the release as the
    pending publication candidate in deployment state when it differs from
    the deployed version, and returns the public discovery result.

    Args:
        recipe_path: Path to the recipe YAML file. Must exist and be
            readable.
        output_dir: Directory to download the installer into. When
            omitted, falls back to ``directories.discover`` from the
            merged configuration. Created if it does not exist.
        cache_file: Path to the discovery cache file. When omitted,
            falls back to ``<directories.cache>/discovery.json`` from
            the merged configuration.
        state_dir: Directory holding per-app deployment state files.
            When omitted, falls back to ``<directories.state>/deployment``
            from the merged configuration.
        stateless: When True, skips loading and saving the discovery
            cache and deployment state entirely. Forces every run to
            behave as if no prior cache existed.

    Returns:
        Public discovery result containing the resolved version,
        file path, and SHA-256 hash.

    Raises:
        ConfigError: On missing or invalid configuration, including
            an unknown ``discovery.strategy`` value or a corrupted
            deployment state file.
        NetworkError: On download or version-extraction failures from
            either flow.

    """
    logger = get_global_logger()

    logger.step(1, 4, "Loading configuration...")
    config = load_effective_config(recipe_path)
    if output_dir is None:
        output_dir = Path(config["directories"]["discover"])
    if cache_file is None:
        cache_file = Path(config["directories"]["cache"]) / "discovery.json"
    if state_dir is None:
        state_dir = Path(config["directories"]["state"]) / "deployment"

    cache_data = _load_cache(cache_file, stateless, logger)

    app_name = config["name"]
    app_id = config["id"]

    discovery = config.get("discovery", {})
    strategy_name = discovery.get("strategy")
    if not strategy_name:
        raise ConfigError(f"No 'discovery.strategy' defined for app: {app_name}")

    cache = _get_cache_for_app(cache_data, app_id, logger)

    logger.step(2, 4, "Discovering version...")
    if strategy_name == "url_download":
        logger.step(3, 4, "Fetching installer...")
        result = run_url_download(config, output_dir, cache=cache)
    else:
        strategy = get_strategy(strategy_name)
        info = strategy.discover(config)
        logger.info("DISCOVERY", f"Version discovered: {info.version}")
        logger.step(3, 4, "Resolving installer...")
        result = resolve_with_cache(info, config, output_dir, cache)

    logger.step(4, 4, "Updating state...")
    if not stateless and app_id:
        if cache_data is not None:
            _save_app_cache(
                cache_data, cache_file, app_id, strategy_name, result, logger
            )
        _record_pending_release(state_dir, app_id, result, logger)

    return DiscoverResult(
        app_name=app_name,
        app_id=app_id,
        strategy=strategy_name,
        version=result.version,
        version_source=result.version_source,
        file_path=result.file_path,
        sha256=result.sha256,
        status="success",
    )


def _load_cache(
    cache_file: Path | None, stateless: bool, logger: Any
) -> dict[str, Any] | None:
    """Loads the discovery cache, or returns a fresh cache dict if missing."""
    if stateless or not cache_file:
        return None
    try:
        cache_data = load_cache(cache_file)
        logger.verbose("STATE", f"Loaded discovery cache from {cache_file}")
        return cache_data
    except FileNotFoundError:
        logger.verbose("STATE", f"Cache file not found, will create: {cache_file}")
        return {
            "metadata": {"napt_version": __version__, "schema_version": "2"},
            "apps": {},
        }
    except Exception as err:
        logger.warning("STATE", f"Failed to load discovery cache: {err}")
        logger.verbose("STATE", "Continuing without cache tracking")
        return None


def _get_cache_for_app(
    state: dict[str, Any] | None, app_id: str, logger: Any
) -> dict[str, Any] | None:
    """Pulls the per-app cache entry from state, logging what we found."""
    if not state or not app_id:
        return None
    cache = state.get("apps", {}).get(app_id)
    if not cache:
        return None
    logger.verbose("STATE", f"Using cache for {app_id}")
    if cache.get("known_version"):
        logger.verbose("STATE", f"  Cached version: {cache.get('known_version')}")
    if cache.get("etag"):
        logger.verbose("STATE", f"  Cached ETag: {cache.get('etag')}")
    return cache


def _save_app_cache(
    cache_data: dict[str, Any],
    cache_file: Path,
    app_id: str,
    strategy_name: str,
    result: StrategyResult,
    logger: Any,
) -> None:
    """Writes the resolved discovery result back to the discovery cache."""
    etag = result.headers.get("ETag")
    last_modified = result.headers.get("Last-Modified")
    if etag:
        logger.verbose("STATE", f"Saving ETag for next run: {etag}")
    if last_modified:
        logger.verbose("STATE", f"Saving Last-Modified for next run: {last_modified}")

    cache_entry: dict[str, Any] = {
        "url": result.download_url,
        "etag": etag,
        "last_modified": last_modified,
        "sha256": result.sha256,
        "file_path": str(result.file_path),
        "known_version": result.version,
        "strategy": strategy_name,
    }

    cache_data.setdefault("apps", {})[app_id] = cache_entry
    cache_data["metadata"] = {
        "napt_version": __version__,
        "last_updated": datetime.now(UTC).isoformat(),
        "schema_version": "2",
    }

    try:
        save_cache(cache_data, cache_file)
        logger.verbose("STATE", f"Updated discovery cache: {cache_file}")
    except Exception as err:
        logger.warning("STATE", f"Failed to save discovery cache: {err}")


def _record_pending_release(
    state_dir: Path,
    app_id: str,
    result: StrategyResult,
    logger: Any,
) -> None:
    """Records the discovered release in the app's deployment state.

    Updates the pending publication candidate when the discovered release
    differs from the deployed version (single slot, newest wins). Unlike
    the discovery cache, deployment state failures are not swallowed —
    a corrupted authoritative file must surface to the caller.
    """
    state_path = deployment_state_path(state_dir, app_id)
    state = load_deployment_state(state_path)

    action = record_pending(
        state,
        version=result.version,
        sha256=result.sha256,
        url=result.download_url,
    )

    if action is None:
        logger.verbose("STATE", "Pending release unchanged")
        return

    save_deployment_state(state, state_path)
    if action == "cleared":
        logger.info(
            "STATE",
            "Pending release cleared (vendor serves the deployed version)",
        )
    elif action == "replaced":
        logger.info(
            "STATE",
            f"Pending release replaced with {result.version} (newest wins)",
        )
    else:
        logger.info(
            "STATE",
            f"Recorded pending release {result.version} in {state_path}",
        )
