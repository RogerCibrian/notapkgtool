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

"""GitHub API discovery strategy for NAPT.

This is a VERSION-FIRST strategy that queries the GitHub API to get version
and download URL WITHOUT downloading the installer. This enables fast version
checks and efficient caching.

Key Advantages:

- Fast version discovery (GitHub API call ~100ms)
- Can skip downloads entirely when version unchanged
- Direct access to latest releases via stable GitHub API
- Version extraction from Git tags (semantic versioning friendly)
- Asset pattern matching for multi-platform releases
- Optional authentication for higher rate limits
- No web scraping required
- Ideal for CI/CD with scheduled checks

Supported Version Extraction:

- Tag-based: Extract version from release tag names
    - Supports named capture groups: (?P<version>...)
    - Default pattern strips "v" prefix: v1.2.3 -> 1.2.3
    - Falls back to full tag if no pattern match

Use Cases:

- Open-source projects (Git, VS Code, Node.js, etc.)
- Projects with GitHub releases (Firefox, Chrome alternatives)
- Vendors who publish installers as release assets
- Projects with semantic versioned tags
- CI/CD pipelines with frequent version checks

Recipe Configuration:
    ```yaml
    source:
        strategy: api_github
        repo: "git-for-windows/git"                    # Required: owner/repo
        asset_pattern: "Git-.*-64-bit\\.exe$"          # Required: regex for asset
        version_pattern: "v?([0-9.]+)"                 # Optional: version extraction
        prerelease: false                              # Optional: include prereleases
        token: "${GITHUB_TOKEN}"                       # Optional: auth token
    ```

Configuration Fields:

- **repo** (str, required): GitHub repository in "owner/name" format
    (e.g., "git-for-windows/git")
- **asset_pattern** (str, required): Regular expression to match asset
    filename. If multiple assets match, the first match is used. Example:
    ".*-x64\\.msi$" matches assets ending with "-x64.msi"
- **version_pattern** (str, optional): Regular expression to extract version
    from the release tag name. Use a named capture group (?P<version>...) or
    the entire match. Default: "v?([0-9.]+)" strips optional "v" prefix.
    Example: "release-([0-9.]+)" for tags like "release-1.2.3".
    - **prerelease** (bool, optional): If True, include pre-release versions. If False
      (default), only stable releases are considered. Uses GitHub's prerelease flag.
    - **token** (str, optional): GitHub personal access token for authentication.
      Increases rate limit from 60 to 5000 requests per hour. Can use environment
      variable substitution: "${GITHUB_TOKEN}". No special permissions needed for
      public repositories.

Error Handling:

- ValueError: Missing or invalid configuration fields
- RuntimeError: API failures, no releases, no matching assets
- Errors are chained with 'from err' for better debugging

Rate Limits:

- Unauthenticated: 60 requests/hour per IP
- Authenticated: 5000 requests/hour per token
- Tip: Use a token for production use or frequent checks

Example:
    In a recipe YAML:
        ```yaml
        apps:
          - name: "Git for Windows"
            id: "git"
            source:
              strategy: api_github
              repo: "git-for-windows/git"
              asset_pattern: "Git-.*-64-bit\\.exe$"
        ```

    From Python (version-first approach):
        ```python
        from notapkgtool.discovery.api_github import ApiGithubStrategy
        from notapkgtool.io import download_file

        strategy = ApiGithubStrategy()
        app_config = {
            "source": {
                "repo": "git-for-windows/git",
                "asset_pattern": ".*-64-bit\\.exe$",
            }
        }

        # Get version WITHOUT downloading
        version_info = strategy.get_version_info(app_config)
        print(f"Latest version: {version_info.version}")

        # Download only if needed
        if need_to_download:
            file_path, sha256, headers = download_file(
                version_info.download_url, Path("./downloads")
            )
            print(f"Downloaded to {file_path}")
        ```

    From Python (using core orchestration):
        ```python
        from pathlib import Path
        from notapkgtool.core import discover_recipe

        # Automatically uses version-first optimization
        result = discover_recipe(Path("recipe.yaml"), Path("./downloads"))
        print(f"Version {result.version} at {result.file_path}")
        ```

Note:
    Version discovery via API only (no download required).
    Core orchestration automatically skips download if version unchanged.
    The GitHub API is stable and well-documented. Releases are fetched in order
    (latest first). Asset matching is case-sensitive by default (use (?i) for
    case-insensitive). Consider url_download if you need a direct download URL instead.

"""

from __future__ import annotations

import os
import re
from typing import Any

import requests

from notapkgtool.exceptions import ConfigError, NetworkError
from notapkgtool.versioning.keys import VersionInfo

from .base import register_strategy


class ApiGithubStrategy:
    """Discovery strategy for GitHub releases.

    Configuration example:
        source:
          strategy: api_github
          repo: "owner/repository"
          asset_pattern: ".*\\.msi$"
          version_pattern: "v?([0-9.]+)"
          prerelease: false
          token: "${GITHUB_TOKEN}"
    """

    def get_version_info(
        self,
        app_config: dict[str, Any],
        verbose: bool = False,
        debug: bool = False,
    ) -> VersionInfo:
        """Fetch latest release from GitHub API without downloading
        (version-first path).

        This method queries the GitHub API for the latest release and extracts
        the version from the tag name and the download URL from matching assets.
        If the version matches cached state, the download can be skipped entirely.

        Args:
            app_config: App configuration containing source.repo and
                optional fields.
            verbose: If True, print verbose logging messages.
                Default is False.
            debug: If True, print debug logging messages.
                Default is False.

        Returns:
            Version info with version string, download URL, and
                source name.

        Raises:
            ValueError: If required config fields are missing, invalid, or if
                no matching assets are found.
            RuntimeError: If API call fails or release has no assets.

        Example:
            Get version from GitHub releases:
                ```python
                strategy = ApiGithubStrategy()
                config = {
                    "source": {
                        "repo": "owner/repo",
                        "asset_pattern": ".*\\.msi$"
                    }
                }
                version_info = strategy.get_version_info(config)
                # version_info.version returns: '1.0.0'
                ```

        """
        from notapkgtool.logging import get_global_logger

        logger = get_global_logger()
        # Validate configuration
        source = app_config.get("source", {})
        repo = source.get("repo")
        if not repo:
            raise ConfigError("api_github strategy requires 'source.repo' in config")

        # Validate repo format
        if "/" not in repo or repo.count("/") != 1:
            raise ConfigError(
                f"Invalid repo format: {repo!r}. Expected 'owner/repository'"
            )

        # Optional configuration
        asset_pattern = source.get("asset_pattern")
        if not asset_pattern:
            raise ConfigError(
                "api_github strategy requires 'source.asset_pattern' in config"
            )

        version_pattern = source.get("version_pattern", r"v?([0-9.]+)")
        prerelease = source.get("prerelease", False)
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
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            if response.status_code == 404:
                raise NetworkError(
                    f"Repository {repo!r} not found or has no releases"
                ) from err
            elif response.status_code == 403:
                raise NetworkError(
                    f"GitHub API rate limit exceeded. Consider using a token. "
                    f"Status: {response.status_code}"
                ) from err
            else:
                raise NetworkError(
                    f"GitHub API request failed: {response.status_code} "
                    f"{response.reason}"
                ) from err
        except requests.exceptions.RequestException as err:
            raise NetworkError(f"Failed to fetch GitHub release: {err}") from err

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

        return VersionInfo(
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
        source = app_config.get("source", {})

        # Check required fields
        if "repo" not in source:
            errors.append("Missing required field: source.repo")
        elif not isinstance(source["repo"], str):
            errors.append("source.repo must be a string")
        elif not source["repo"].strip():
            errors.append("source.repo cannot be empty")
        else:
            # Validate repo format
            repo = source["repo"]
            if repo.count("/") != 1:
                errors.append(
                    "source.repo must be in format 'owner/repo' (e.g., 'git/git')"
                )

        if "asset_pattern" not in source:
            errors.append("Missing required field: source.asset_pattern")
        elif not isinstance(source["asset_pattern"], str):
            errors.append("source.asset_pattern must be a string")
        elif not source["asset_pattern"].strip():
            errors.append("source.asset_pattern cannot be empty")
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
                errors.append("source.version_pattern must be a string")
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
