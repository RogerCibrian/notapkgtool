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

"""Discovery strategy protocol and shared helpers.

A *discovery strategy* answers a single question: "what is the latest
version of this app, and where can it be downloaded from?" Strategies
return that answer as a [RemoteVersion][napt.discovery.base.RemoteVersion]
dataclass. They do not download files themselves; the orchestrator does.

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
    - Strategies are pure functions of configuration. They have no state
        and no I/O of files.
    - Dispatch is an explicit name-to-class table in
        [napt.discovery.registry][].
    - [resolve_installer][napt.discovery.resolve.resolve_installer]
        turns a [RemoteVersion][napt.discovery.base.RemoteVersion]
        into a [StrategyResult][napt.discovery.base.StrategyResult] by
        reusing the previous download or fetching a new one. Strategies
        don't call it themselves; the orchestrator does.

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Protocol

from napt.exceptions import ConfigError
from napt.paths import is_safe_path_component


@dataclass(frozen=True)
class RemoteVersion:
    """Version and download URL discovered from a remote source.

    Returned by every [DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy]
    implementation. The orchestrator passes this to
    [resolve_installer][napt.discovery.resolve.resolve_installer] to decide
    whether the file needs to be downloaded.

    Attributes:
        version: Raw version string extracted from the remote source
            (for example, ``"140.0.7339.128"``). The trigger for a
            download; an MSI or MSIX installer's own version is what gets
            recorded.
        download_url: URL the installer can be fetched from.
        source: Name of the strategy that produced this result, used
            for logging and result reporting (for example, ``"api_github"``).
    """

    version: str
    download_url: str
    source: str


@dataclass(frozen=True)
class StrategyResult:
    """Resolved discovery result, ready to be recorded in deployment state.

    Returned by [resolve_installer][napt.discovery.resolve.resolve_installer]
    for every flow. Captures everything the orchestrator needs to record
    the pending release and build a public
    [DiscoverResult][napt.results.DiscoverResult].

    Attributes:
        version: Version string for the resolved file.
        version_source: Where the version came from: ``"msi"`` or
            ``"msix"`` when read from the installer, otherwise the name of
            the strategy that reported it (for example, ``"api_github"``).
        file_path: Path to the resolved installer on disk. This is either
            a freshly downloaded file or one an earlier run downloaded.
        sha256: SHA-256 hex digest of the resolved file.
        download_url: URL the file came from, recorded with the pending
            release.
        cached: True when a file from an earlier run was reused; False
            when it was downloaded.
    """

    version: str
    version_source: str
    file_path: Path
    sha256: str
    download_url: str
    cached: bool


class DiscoveryStrategy(Protocol):
    """Protocol for version discovery strategies.

    A strategy queries a remote source (API, web page, etc.) and returns
    the latest version plus its download URL. Strategies do not download
    files or write to disk. Those concerns belong to the orchestrator.

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


def require_usable_version(version: str) -> None:
    """Rejects a version that cannot name a folder or that a device would misread.

    The version names the download folder (``downloads/<id>/<version>``)
    and later the build folder, so a value with a path separator or ``..``
    is refused before any folder is created from it.

    It is also what the detection and requirements scripts compare on a
    device, and they take each part's leading digits with a part that has
    none counting as 0. A version whose first part has no digits (``v2.0``,
    ``latest``) therefore reads as version 0 there: every device would
    report it installed and no device would ever upgrade to it. Such a
    version is refused so the recipe gets fixed instead.

    Args:
        version: Version read from the installer, or reported by a
            strategy for an installer that carries no version of its own.

    Raises:
        ConfigError: If the version is not a plain folder name, or does
            not start with a digit.
    """
    if not is_safe_path_component(version):
        raise ConfigError(
            f"Discovered version {version!a} cannot be used as a folder name. "
            "Versions may contain only letters, digits, '.', '-', '_', and '+'. "
            "Check the recipe's version pattern, or the installer's metadata."
        )
    if not version[0].isdigit():
        # The part from the first digit onward is what a pattern should keep.
        digits = re.search(r"\d.*", version)
        hint = (
            f"Tighten the recipe's version_pattern so it captures only "
            f"{digits.group()!a}."
            if digits
            else "Check the recipe's version_path or version_pattern."
        )
        raise ConfigError(
            f"Version {version!a} does not start with a number. Devices compare "
            "versions numerically and would read it as 0, which blocks "
            f"upgrades. {hint}"
        )
