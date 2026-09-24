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
picks a flow based on the recipe's ``discovery.strategy`` value, records
the release as a pending publication candidate in deployment state, and
returns the public [DiscoverResult][napt.results.DiscoverResult].

Two Flows:
    Two flows feed into the same orchestration:

    - **Version-first** (api_github, api_json, web_scrape and any other
        registered [DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy]):
        the strategy returns a
        [RemoteVersion][napt.discovery.base.RemoteVersion], whose version
        is the trigger: a run that finds the same version as last time
        reuses the previous download without a request.
    - **url_download** (handled by
        [run_url_download][napt.discovery.url_download.run_url_download]):
        has no version to compare, so it sends HTTP conditional headers
        (``ETag`` / ``Last-Modified``) and reuses the file on HTTP 304.
        Not a registered strategy because it cannot determine the
        version without the file.

Both flows end in [resolve_installer][napt.discovery.resolve.resolve_installer],
which downloads when needed, reads the version from an MSI or MSIX
installer, and returns a [StrategyResult][napt.discovery.base.StrategyResult]
that this module unwraps into the pending release and the public result.

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from napt.config.loader import load_effective_config
from napt.discovery.base import StrategyResult
from napt.discovery.registry import get_strategy
from napt.discovery.resolve import resolve_installer
from napt.discovery.url_download import run_url_download
from napt.exceptions import ConfigError
from napt.logging import get_global_logger
from napt.results import DiscoverResult
from napt.state.deployment import (
    deployment_state_path,
    load_deployment_state,
    record_pending,
    save_deployment_state,
)
from napt.versioning.ordering import is_downgrade


def discover_recipe(
    recipe_path: Path,
    output_dir: Path | None = None,
    state_dir: Path | None = None,
    stateless: bool = False,
) -> DiscoverResult:
    """Discovers the latest version of an app and resolves its installer.

    Loads the recipe configuration, dispatches to the appropriate
    discovery flow (version-first registered strategy or ``url_download``),
    records the release as the pending publication candidate in deployment
    state when it differs from the published version, and returns the
    public discovery result.

    Args:
        recipe_path: Path to the recipe YAML file. Must exist and be
            readable.
        output_dir: Directory to download the installer into. When
            omitted, falls back to ``directories.discover`` from the
            merged configuration. Created if it does not exist.
        state_dir: State root; per-app deployment state files live in its
            ``deployment/`` subfolder, the same layout ``napt build``,
            ``napt promote``, and ``napt status`` read. When omitted, falls
            back to ``directories.state`` from the merged configuration.
        stateless: When True, deployment state is neither read nor
            written, so no pending release is recorded.

    Returns:
        Public discovery result containing the resolved version,
        file path, and SHA-256 hash.

    Raises:
        ConfigError: On missing or invalid configuration, including
            an unknown ``discovery.strategy`` value.
        NetworkError: On download or version-extraction failures from
            either flow.
        StateError: On a corrupted deployment state file.

    """
    logger = get_global_logger()

    logger.step(1, 4, "Loading configuration...")
    config = load_effective_config(recipe_path)
    if output_dir is None:
        output_dir = Path(config["directories"]["discover"])
    if state_dir is None:
        state_dir = Path(config["directories"]["state"])
    deployment_dir = state_dir / "deployment"

    app_name = config["name"]
    app_id = config["id"]

    discovery = config.get("discovery", {})
    strategy_name = discovery.get("strategy")
    if not strategy_name:
        raise ConfigError(f"No 'discovery.strategy' defined for app: {app_name}")

    logger.step(2, 4, "Discovering version...")
    if strategy_name == "url_download":
        logger.step(3, 4, "Fetching installer...")
        result = run_url_download(config, output_dir)
    else:
        strategy = get_strategy(strategy_name)
        info = strategy.discover(config)
        logger.info("DISCOVERY", f"Version discovered: {info.version}")
        logger.step(3, 4, "Resolving installer...")
        result = resolve_installer(
            info.download_url,
            output_dir / app_id,
            source=info.source,
            discovered_version=info.version,
        )

    logger.step(4, 4, "Updating state...")
    if not stateless:
        _record_pending_release(deployment_dir, app_id, app_name, result, logger)

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


def _record_pending_release(
    state_dir: Path,
    app_id: str,
    name: str,
    result: StrategyResult,
    logger: Any,
) -> None:
    """Records the discovered release as the app's pending candidate."""
    state_path = deployment_state_path(state_dir, app_id)
    state = load_deployment_state(state_path)

    action = record_pending(
        state,
        version=result.version,
        sha256=result.sha256,
        url=result.download_url,
    )

    published_version = (state.get("published") or {}).get("version")
    if state.get("pending") and is_downgrade(result.version, published_version):
        logger.warning(
            "STATE",
            f"Pending release {result.version} is LOWER than the published "
            f"{published_version}. Devices already on {published_version} "
            "will not move to it; publishing affects new installs only.",
        )

    if action is None:
        logger.verbose("STATE", "Pending release unchanged")
        return

    state["name"] = name
    save_deployment_state(state, state_path)
    if action == "cleared":
        logger.info(
            "STATE",
            "Pending release cleared (vendor serves the published version)",
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
