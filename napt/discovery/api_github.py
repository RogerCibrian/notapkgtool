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
      token: "${GITHUB_TOKEN}"               # optional
    ```

The [recipe reference](../recipe-reference.md#api_github-strategy) defines
each field.

Note:
    The request goes to the latest-release endpoint, which never returns a
    pre-release or a draft. If no asset matches, discovery raises an error
    rather than walking back through history. ``${VAR}`` in ``token`` is
    replaced with that environment variable, provided ``defaults/org.yaml``
    declares it under ``secrets`` and binds it to ``api.github.com`` (see
    [napt.secrets][]); an undeclared or unset variable stops discovery.

"""

from __future__ import annotations

import re
from typing import Any

from napt.discovery.base import RemoteVersion, bounded, first_capture
from napt.download.download import make_session
from napt.exceptions import ConfigError, NetworkError
from napt.github import API_BASE, API_HOST, asset_url, latest_release, release_tag
from napt.secrets import bound_hosts, check_secret_use, expand_secrets

# Strategy-specific defaults for optional recipe fields.
_DEFAULT_VERSION_PATTERN = r"v?([0-9.]+)"


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
                plus optional ``version_pattern`` and ``token`` fields.

        Returns:
            Latest version, the matched asset's download URL, and
            ``"api_github"`` as the source identifier.

        Raises:
            ConfigError: On missing or malformed required configuration, a
                token secret org.yaml does not declare, binds to another
                host, or that is not set, or when patterns do not match the
                release.
            NetworkError: On API failure, missing assets, or a tag or
                asset name too long to match a pattern on.

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
        raw_token = source.get("token")

        api_url = f"{API_BASE}/repos/{repo}/releases/latest"

        # Expand ${VAR} in the token; an undeclared or unset variable stops
        # discovery rather than sending the request unauthenticated. A
        # literal token is bound to api.github.com like a declared one, so
        # no redirect carries it elsewhere.
        token = None
        hosts: set[str] | None = None
        if raw_token:
            token = expand_secrets(
                app_config, str(raw_token), api_url, "discovery.token"
            )
            hosts = bound_hosts(app_config, [str(raw_token)])
            if hosts is None:
                hosts = {API_HOST}
            logger.verbose("DISCOVERY", "Using authenticated API request")

        logger.verbose("DISCOVERY", "Strategy: api_github (version-first)")
        logger.verbose("DISCOVERY", f"Repository: {repo}")
        logger.verbose("DISCOVERY", f"Version pattern: {version_pattern}")
        if asset_pattern:
            logger.verbose("DISCOVERY", f"Asset pattern: {asset_pattern}")

        with make_session() as session:
            release_data = latest_release(session, repo, token=token, hosts=hosts)

        # Extract version from tag name
        tag_name = bounded(release_tag(release_data), "The release tag")

        logger.verbose("DISCOVERY", f"Release tag: {tag_name}")

        try:
            pattern = re.compile(version_pattern)
            version_str = first_capture(pattern, tag_name)
            if version_str is None:
                raise ConfigError(
                    f"Version pattern {version_pattern!r} did not match "
                    f"tag {tag_name!r}"
                )

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
            asset_name = bounded(str(asset.get("name", "")), "An asset name")
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

        download_url = asset_url(matched_asset)
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

        token = source.get("token")
        if token is not None:
            if not isinstance(token, str):
                errors.append("discovery.token: Must be a string")
            else:
                errors.extend(
                    check_secret_use(
                        app_config,
                        token,
                        f"https://{API_HOST}/",
                        "discovery.token",
                    )
                )

        return errors
