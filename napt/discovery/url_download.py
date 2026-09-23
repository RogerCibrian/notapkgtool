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

"""url_download discovery flow.

This module is intentionally not a
[DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy]. The
strategies in [napt.discovery.base][] produce a
[RemoteVersion][napt.discovery.base.RemoteVersion] from configuration
alone (version-first). ``url_download`` cannot do that: it has no
remote endpoint to query for the version, so it must download the
installer and read the version from the file itself. The discovery
orchestrator special-cases ``strategy: url_download`` and dispatches to
[run_url_download][napt.discovery.url_download.run_url_download] directly.

The download, the version read, and the reuse of an unchanged file all
happen in [napt.discovery.resolve][], shared with the version-first
strategies. With no version to compare, this flow relies on the server's
``ETag`` / ``Last-Modified`` to learn whether the file changed.

Supported File Types:
    - ``.msi``: version is read from the MSI ProductVersion property.
    - ``.msix``: version is read from the package's Identity element.
    - Other extensions raise [ConfigError][napt.exceptions.ConfigError].
        For those installers, use a version-first strategy.

Recipe Example:
    ```yaml
    discovery:
      strategy: url_download
      url: "https://vendor.example.com/installer.msi"
    ```

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from napt.exceptions import ConfigError
from napt.logging import get_global_logger

from .base import StrategyResult
from .resolve import resolve_installer


def run_url_download(
    app_config: dict[str, Any],
    output_dir: Path,
) -> StrategyResult:
    """Downloads a fixed URL and reads the version from the resulting file.

    Args:
        app_config: Merged recipe configuration dict containing
            ``discovery.url`` and ``id``.
        output_dir: Base directory to download into. The file lands
            in ``output_dir / app_id / version``.

    Returns:
        Resolved version, file path, and SHA-256 hash. The ``cached``
        field is True when HTTP 304 was used to reuse the previously
        downloaded file.

    Raises:
        ConfigError: If ``discovery.url`` is missing, or if the
            downloaded file is not an MSI or MSIX.
        NetworkError: On download or version-extraction failures.

    """
    logger = get_global_logger()
    url = app_config.get("discovery", {}).get("url")
    if not url:
        raise ConfigError("url_download strategy requires 'discovery.url' in config")

    logger.verbose("DISCOVERY", "Strategy: url_download (file-first)")
    logger.verbose("DISCOVERY", f"Source URL: {url}")

    return resolve_installer(url, output_dir / app_config["id"], source="url_download")


def validate_url_download_config(app_config: dict[str, Any]) -> list[str]:
    """Validates url_download configuration fields.

    Called by [napt.validation.validate_config][] to compose the
    url_download field rules into the overall recipe validation.

    Args:
        app_config: Merged recipe configuration dict.

    Returns:
        Human-readable error messages. Empty when configuration is valid.

    """
    errors: list[str] = []
    source = app_config.get("discovery", {})

    if "url" not in source:
        errors.append("Missing required field: discovery.url")
    elif not isinstance(source["url"], str):
        errors.append("discovery.url must be a string")
    elif not source["url"].strip():
        errors.append("discovery.url cannot be empty")

    return errors
