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

r"""Web scraping discovery strategy.

Fetches a vendor download page, locates a download link, and extracts
the version from that link's URL. Use this when a vendor has neither a
JSON API nor a GitHub releases feed.

Recipe Example (CSS selector — recommended):
    ```yaml
    discovery:
      strategy: web_scrape
      page_url: "https://www.7-zip.org/download.html"
      link_selector: 'a[href$="-x64.msi"]'
      version_pattern: "7z(\\d{2})(\\d{2})-x64"
      version_format: "{0}.{1}"     # transforms ("25", "01") -> "25.01"
    ```

Recipe Example (regex fallback):
    ```yaml
    discovery:
      strategy: web_scrape
      page_url: "https://vendor.example.com/downloads"
      link_pattern: 'href="(/files/app-v[0-9.]+-x64\\.msi)"'
      version_pattern: "app-v([0-9.]+)-x64"
    ```

Configuration Fields:
    - **page_url** (required): URL of the page to scrape.
    - **link_selector** (optional): CSS selector identifying the download
        link's ``<a>`` element. Recommended over regex.
    - **link_pattern** (optional): Regex with one capture group around
        the link URL. Used when a CSS selector cannot pin the link down.
        Exactly one of ``link_selector`` / ``link_pattern`` is required.
    - **version_pattern** (required): Regex applied to the discovered
        link URL to extract the version. Capture groups are pulled out
        and combined with ``version_format``.
    - **version_format** (optional, default ``"{0}"``): Python format
        string referencing capture groups by index (``{0}``, ``{1}``,
        ...). Use this when a single version field needs to be assembled
        from multiple captures.

Finding a CSS Selector:
    1. Open the download page in Chrome / Edge / Firefox.
    2. Right-click the download link -> Inspect.
    3. Right-click the highlighted element -> Copy -> Copy selector.
    4. Simplify the result. Common shapes:
        - ``a[href$=".msi"]`` (links ending in .msi)
        - ``a[href*="x64"]`` (links containing "x64")
        - ``a.download`` (links with ``class="download"``)

Note:
    The selector / pattern is expected to match exactly one link; the
    first match is used. Relative URLs in the page are resolved against
    ``page_url``. CSS selector support requires BeautifulSoup4; the
    regex fallback does not.

"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

from napt.discovery.base import RemoteVersion
from napt.exceptions import ConfigError, NetworkError

from .base import register_strategy

# Strategy-specific defaults for optional recipe fields.
_DEFAULT_VERSION_FORMAT = "{0}"


class WebScrapeStrategy:
    """Discovery strategy for scraping vendor download pages."""

    def discover(self, app_config: dict[str, Any]) -> RemoteVersion:
        r"""Discovers version and download URL by scraping a vendor page.

        Fetches ``discovery.page_url``, locates a download link with
        either ``link_selector`` (CSS) or ``link_pattern`` (regex),
        and extracts the version from the matched link using
        ``version_pattern``.

        Args:
            app_config: Merged recipe configuration dict containing
                ``discovery.page_url``, exactly one of
                ``discovery.link_selector`` or ``discovery.link_pattern``,
                and ``discovery.version_pattern``.

        Returns:
            Discovered version, the matched link's URL, and
            ``"web_scrape"`` as the source identifier.

        Raises:
            ConfigError: On missing required configuration or when
                a selector / pattern matches nothing.
            NetworkError: On page fetch failure.

        """
        from napt.logging import get_global_logger

        logger = get_global_logger()
        # Validate configuration
        source = app_config.get("discovery", {})
        page_url = source.get("page_url")
        if not page_url:
            raise ConfigError(
                "web_scrape strategy requires 'discovery.page_url' in config"
            )

        link_selector = source.get("link_selector")
        link_pattern = source.get("link_pattern")

        if not link_selector and not link_pattern:
            raise ConfigError(
                "web_scrape strategy requires either 'discovery.link_selector' or "
                "'discovery.link_pattern' in config"
            )

        version_pattern = source.get("version_pattern")
        if not version_pattern:
            raise ConfigError(
                "web_scrape strategy requires 'discovery.version_pattern' in config"
            )

        version_format = source.get("version_format", _DEFAULT_VERSION_FORMAT)

        logger.verbose("DISCOVERY", "Strategy: web_scrape (version-first)")
        logger.verbose("DISCOVERY", f"Page URL: {page_url}")
        if link_selector:
            logger.verbose("DISCOVERY", f"Link selector (CSS): {link_selector}")
        if link_pattern:
            logger.verbose("DISCOVERY", f"Link pattern (regex): {link_pattern}")
        logger.verbose("DISCOVERY", f"Version pattern: {version_pattern}")

        # Download the HTML page
        logger.verbose("DISCOVERY", f"Fetching page: {page_url}")
        try:
            response = requests.get(page_url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            raise NetworkError(
                f"Failed to fetch page: {response.status_code} {response.reason}"
            ) from err
        except requests.exceptions.RequestException as err:
            raise NetworkError(f"Failed to fetch page: {err}") from err

        html_content = response.text
        logger.verbose("DISCOVERY", f"Page fetched ({len(html_content)} bytes)")

        # Find download link using CSS selector or regex
        download_url = None

        if link_selector:
            # Use CSS selector with BeautifulSoup4
            soup = BeautifulSoup(html_content, "html.parser")
            element = soup.select_one(link_selector)

            if not element:
                raise ConfigError(
                    f"CSS selector {link_selector!r} did not match any elements on page"
                )

            # Get href attribute
            href = element.get("href")
            if not href:
                raise ConfigError(
                    f"Element matched by {link_selector!r} has no href attribute"
                )

            logger.verbose("DISCOVERY", f"Found link via CSS: {href}")

            # Build absolute URL
            download_url = urljoin(page_url, href)

        elif link_pattern:
            # Use regex fallback
            try:
                pattern = re.compile(link_pattern)
                match = pattern.search(html_content)

                if not match:
                    raise ConfigError(
                        f"Regex pattern {link_pattern!r} did not match anything on page"
                    )

                # Get first capture group or full match
                if pattern.groups > 0:
                    href = match.group(1)
                else:
                    href = match.group(0)

                logger.verbose("DISCOVERY", f"Found link via regex: {href}")

                # Build absolute URL
                download_url = urljoin(page_url, href)

            except re.error as err:
                raise ConfigError(
                    f"Invalid link_pattern regex: {link_pattern!r}"
                ) from err

        logger.verbose("DISCOVERY", f"Download URL: {download_url}")

        # Extract version from the download URL
        try:
            version_regex = re.compile(version_pattern)
            match = version_regex.search(download_url)

            if not match:
                raise ConfigError(
                    f"Version pattern {version_pattern!r} did not match "
                    f"URL {download_url!r}"
                )

            # Get captured groups
            groups = match.groups()

            if not groups:
                # No capture groups, use full match
                version_str = match.group(0)
            else:
                # Format using captured groups
                try:
                    version_str = version_format.format(*groups)
                except (IndexError, KeyError) as err:
                    raise ConfigError(
                        f"version_format {version_format!r} failed with "
                        f"groups {groups}: {err}"
                    ) from err

        except re.error as err:
            raise ConfigError(
                f"Invalid version_pattern regex: {version_pattern!r}"
            ) from err

        logger.verbose("DISCOVERY", f"Extracted version: {version_str}")

        return RemoteVersion(
            version=version_str,
            download_url=download_url,
            source="web_scrape",
        )

    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """Validate web_scrape strategy configuration.

        Checks for required fields and correct types without making network calls.

        Args:
            app_config: The app configuration from the recipe.

        Returns:
            List of error messages (empty if valid).

        """
        errors = []
        source = app_config.get("discovery", {})

        # Check page_url
        if "page_url" not in source:
            errors.append("Missing required field: discovery.page_url")
        elif not isinstance(source["page_url"], str):
            errors.append("discovery.page_url must be a string")
        elif not source["page_url"].strip():
            errors.append("discovery.page_url cannot be empty")

        # Check that at least one link finding method is provided
        link_selector = source.get("link_selector")
        link_pattern = source.get("link_pattern")

        if not link_selector and not link_pattern:
            errors.append(
                "Missing required field: must provide either "
                "discovery.link_selector or discovery.link_pattern"
            )

        # Validate link_selector if provided
        if link_selector:
            if not isinstance(link_selector, str):
                errors.append("discovery.link_selector must be a string")
            elif not link_selector.strip():
                errors.append("discovery.link_selector cannot be empty")
            else:
                # Try to validate CSS selector syntax
                try:
                    # Test if selector is parseable
                    soup = BeautifulSoup("<html></html>", "html.parser")
                    soup.select_one(link_selector)  # Will raise if invalid
                except Exception as err:
                    errors.append(f"Invalid CSS selector: {err}")

        # Validate link_pattern if provided
        if link_pattern:
            if not isinstance(link_pattern, str):
                errors.append("discovery.link_pattern must be a string")
            elif not link_pattern.strip():
                errors.append("discovery.link_pattern cannot be empty")
            else:
                # Validate regex compiles
                try:
                    re.compile(link_pattern)
                except re.error as err:
                    errors.append(f"Invalid link_pattern regex: {err}")

        # Check version_pattern
        if "version_pattern" not in source:
            errors.append("Missing required field: discovery.version_pattern")
        elif not isinstance(source["version_pattern"], str):
            errors.append("discovery.version_pattern must be a string")
        elif not source["version_pattern"].strip():
            errors.append("discovery.version_pattern cannot be empty")
        else:
            # Validate regex compiles
            try:
                re.compile(source["version_pattern"])
            except re.error as err:
                errors.append(f"Invalid version_pattern regex: {err}")

        # Validate version_format if provided
        if "version_format" in source:
            if not isinstance(source["version_format"], str):
                errors.append("discovery.version_format must be a string")
            elif not source["version_format"].strip():
                errors.append("discovery.version_format cannot be empty")

        return errors


# Register this strategy when the module is imported
register_strategy("web_scrape", WebScrapeStrategy)
