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

r"""GitHub releases discovery strategy.

Queries the GitHub releases API for the latest tag and the download URL
of a matching asset. The version comes from the release tag (parsed
with a regex); the download URL comes from the first asset whose
filename matches ``asset_pattern``.

Recipe Example:
    ```yaml
    discovery:
      strategy: api_github
      repo: "git-for-windows/git"            # required, "owner/name"
      asset_pattern: "Git-.*-64-bit\\.exe$"  # required, regex on asset filename
      version_pattern: "v?([0-9.]+)"         # optional, default strips "v"
      prerelease: false                      # optional, default false
      token: "${GITHUB_TOKEN}"               # optional, supports env expansion
    ```

Configuration Fields:
    - **repo** (required): GitHub repo as ``"owner/name"``.
    - **asset_pattern** (required): Regex matched against asset filename.
        First match wins. Case-sensitive by default; prefix with ``(?i)``
        for case-insensitive matching.
    - **version_pattern** (optional): Regex for extracting the version
        from the release tag. Uses a named group ``(?P<version>...)`` or
        capture group 1 if present, otherwise the full match. Default:
        ``v?([0-9.]+)``.
    - **prerelease** (optional, default false): When true, includes
        pre-release versions; otherwise the latest release must be stable.
    - **token** (optional): GitHub personal access token. Raises the API
        rate limit from 60 to 5000 requests/hour. Supports ``${ENV_VAR}``
        expansion. Public repos do not require any special permissions.

Note:
    GitHub returns the most recent release first. If no asset matches,
    or the latest release is a pre-release while ``prerelease: false``,
    discovery raises an error rather than walking back through history.

"""

from __future__ import annotations

import os
import re
from typing import Any

import requests

from napt.discovery.base import RemoteVersion
from napt.exceptions import ConfigError, NetworkError

from .base import register_strategy

# Strategy-specific defaults for optional recipe fields.
_DEFAULT_VERSION_PATTERN = r"v?([0-9.]+)"
_DEFAULT_PRERELEASE = False


class ApiGithubStrategy:
    """Discovery strategy for GitHub releases."""

    def discover(self, app_config: dict[str, Any]) -> RemoteVersion:
        r"""Discovers the latest GitHub release version and asset download URL.

        Queries the GitHub releases API for the latest release of the
        configured repository. Extracts the version from the release tag
        (via ``version_pattern``) and the download URL from the first
        asset matching ``asset_pattern``.

        Args:
            app_config: Merged recipe configuration dict containing
                ``discovery.repo`` and ``discovery.asset_pattern``,
                plus optional ``version_pattern``, ``prerelease``, and
                ``token`` fields.

        Returns:
            Latest version, the matched asset's download URL, and
            ``"api_github"`` as the source identifier.

        Raises:
            ConfigError: On missing or malformed required configuration,
                or when patterns do not match the release.
            NetworkError: On API failure, missing assets, or rejected
                pre-releases.

        """
        from napt.logging import get_global_logger

        logger = get_global_logger()
        # Validate configuration
        source = app_config.get("discovery", {})
        repo = source.get("repo")
        if not repo:
            raise ConfigError("api_github strategy requires 'discovery.repo' in config")

        # Validate repo format
        if "/" not in repo or repo.count("/") != 1:
            raise ConfigError(
                f"Invalid repo format: {repo!r}. Expected 'owner/repository'"
            )

        # Optional configuration
        asset_pattern = source.get("asset_pattern")
        if not asset_pattern:
            raise ConfigError(
                "api_github strategy requires 'discovery.asset_pattern' in config"
            )

        version_pattern = source.get("version_pattern", _DEFAULT_VERSION_PATTERN)
        prerelease = source.get("prerelease", _DEFAULT_PRERELEASE)
        token = source.get("token")

        # Expand environment variables in token (e.g., ${GITHUB_TOKEN})
        if token:
            if token.startswith("${") and token.endswith("}"):
                env_var = token[2:-1]
                token = os.environ.get(env_var)
                if not token:
                    logger.verbose(
                        "DISCOVERY",
                        f"Warning: Environment variable {env_var} not set",
                    )

        logger.verbose("DISCOVERY", "Strategy: api_github (version-first)")
        logger.verbose("DISCOVERY", f"Repository: {repo}")
        logger.verbose("DISCOVERY", f"Version pattern: {version_pattern}")
        if asset_pattern:
            logger.verbose("DISCOVERY", f"Asset pattern: {asset_pattern}")
        if prerelease:
            logger.verbose("DISCOVERY", "Including pre-releases")

        # Fetch latest release from GitHub API
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # Add authentication if token provided
        if token:
            headers["Authorization"] = f"token {token}"
            logger.verbose("DISCOVERY", "Using authenticated API request")

        logger.verbose("DISCOVERY", f"Fetching release from: {api_url}")

        try:
            response = requests.get(api_url, headers=headers, timeout=30)
        except requests.exceptions.RequestException as err:
            raise NetworkError(f"Failed to fetch GitHub release: {err}") from err

        if response.status_code == 404:
            raise NetworkError(f"Repository {repo!r} not found or has no releases")
        elif response.status_code == 403:
            raise NetworkError(
                f"GitHub API rate limit exceeded. Consider using a token. "
                f"Status: {response.status_code}"
            )
        elif not response.ok:
            raise NetworkError(
                f"GitHub API request failed: {response.status_code} "
                f"{response.reason}"
            )

        release_data = response.json()

        # Check if this is a prerelease and we don't want those
        if release_data.get("prerelease", False) and not prerelease:
            raise NetworkError(
                f"Latest release is a pre-release and prerelease=false. "
                f"Tag: {release_data.get('tag_name')}"
            )

        # Extract version from tag name
        tag_name = release_data.get("tag_name", "")
        if not tag_name:
            raise NetworkError("Release has no tag_name field")

        logger.verbose("DISCOVERY", f"Release tag: {tag_name}")

        try:
            pattern = re.compile(version_pattern)
            match = pattern.search(tag_name)
            if not match:
                raise ConfigError(
                    f"Version pattern {version_pattern!r} did not match "
                    f"tag {tag_name!r}"
                )

            # Try to get named capture group 'version' first, else use group 1,
            # else full match
            if "version" in pattern.groupindex:
                version_str = match.group("version")
            elif pattern.groups > 0:
                version_str = match.group(1)
            else:
                version_str = match.group(0)

        except re.error as err:
            raise ConfigError(
                f"Invalid version_pattern regex: {version_pattern!r}"
            ) from err
        except (ValueError, IndexError) as err:
            raise ConfigError(
                f"Failed to extract version from tag {tag_name!r} "
                f"using pattern {version_pattern!r}: {err}"
            ) from err

        logger.verbose("DISCOVERY", f"Extracted version: {version_str}")

        # Find matching asset
        assets = release_data.get("assets", [])
        if not assets:
            raise NetworkError(
                f"Release {tag_name} has no assets. "
                f"Check if assets were uploaded to the release."
            )

        logger.verbose("DISCOVERY", f"Release has {len(assets)} asset(s)")

        # Match asset by pattern
        matched_asset = None
        try:
            pattern = re.compile(asset_pattern)
        except re.error as err:
            raise ConfigError(
                f"Invalid asset_pattern regex: {asset_pattern!r}"
            ) from err

        for asset in assets:
            asset_name = asset.get("name", "")
            if pattern.search(asset_name):
                matched_asset = asset
                logger.verbose("DISCOVERY", f"Matched asset: {asset_name}")
                break

        if not matched_asset:
            available = [a.get("name", "(unnamed)") for a in assets]
            raise ConfigError(
                f"No assets matched pattern {asset_pattern!r}. "
                f"Available assets: {', '.join(available)}"
            )

        # Get download URL
        download_url = matched_asset.get("browser_download_url")
        if not download_url:
            raise NetworkError(f"Asset {matched_asset.get('name')} has no download URL")

        logger.verbose("DISCOVERY", f"Download URL: {download_url}")

        return RemoteVersion(
            version=version_str,
            download_url=download_url,
            source="api_github",
        )

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """Validate api_github strategy configuration.

        Checks for required fields and correct types without making network calls.

        Args:
            app_config: The app configuration from the recipe.

        Returns:
            List of error messages (empty if valid).

        """
        errors = []
        source = app_config.get("discovery", {})

        # Check required fields
        if "repo" not in source:
            errors.append("Missing required field: discovery.repo")
        elif not isinstance(source["repo"], str):
            errors.append("discovery.repo must be a string")
        elif not source["repo"].strip():
            errors.append("discovery.repo cannot be empty")
        else:
            # Validate repo format
            repo = source["repo"]
            if repo.count("/") != 1:
                errors.append(
                    "discovery.repo must be in format 'owner/repo' (e.g., 'git/git')"
                )

        if "asset_pattern" not in source:
            errors.append("Missing required field: discovery.asset_pattern")
        elif not isinstance(source["asset_pattern"], str):
            errors.append("discovery.asset_pattern must be a string")
        elif not source["asset_pattern"].strip():
            errors.append("discovery.asset_pattern cannot be empty")
        else:
            # Validate regex pattern syntax
            pattern = source["asset_pattern"]
            import re

            try:
                re.compile(pattern)
            except re.error as err:
                errors.append(f"Invalid asset_pattern regex: {err}")

        # Optional fields validation
        if "version_pattern" in source:
            if not isinstance(source["version_pattern"], str):
                errors.append("discovery.version_pattern must be a string")
            else:
                pattern = source["version_pattern"]
                import re

                try:
                    re.compile(pattern)
                except re.error as err:
                    errors.append(f"Invalid version_pattern regex: {err}")

        return errors


# Register this strategy when the module is imported
register_strategy("api_github", ApiGithubStrategy)
