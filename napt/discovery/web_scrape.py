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

Recipe Example (CSS selector, recommended):
    ```yaml
    discovery:
      strategy: web_scrape
      page_url: "https://www.7-zip.org/download.html"
      link_selector: 'a[href$="-x64.msi"]'
      version_pattern: "7z(\\d{2})(\\d{2})-x64"
      version_format: "{0}.{1}"     # transforms ("25", "01") -> "25.01"
    ```

The [recipe reference](../recipe-reference.md#web_scrape-strategy) defines
each field, including the ``link_pattern`` regex fallback.

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
    ``page_url``.

"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from napt.discovery.base import RemoteVersion, bounded, first_capture
from napt.discovery.fields import (
    check_format,
    check_regex,
    fetch,
    optional_str,
    require_str,
)
from napt.exceptions import ConfigError, NetworkError
from napt.logging import get_global_logger

# Strategy-specific defaults for optional recipe fields.
_DEFAULT_VERSION_FORMAT = "{0}"

# Largest page NAPT parses. Download pages are tens of kilobytes; the cap
# bounds what a recipe's link_pattern and the HTML parser run over.
_MAX_PAGE_BYTES = 5 * 1024 * 1024


class WebScrapeStrategy:
    """Discovery strategy for scraping vendor download pages."""

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "page_url",
            "link_selector",
            "link_pattern",
            "version_pattern",
            "version_format",
        }
    )

    def discover(self, app_config: dict[str, Any]) -> RemoteVersion:
        r"""Discovers version and download URL by scraping a vendor page.

        Fetches ``discovery.page_url``, locates a download link with
        either ``link_selector`` (CSS) or ``link_pattern`` (regex),
        and extracts the version from the matched link using
        ``version_pattern``.

        Args:
            app_config: Merged and validated recipe configuration dict
                containing ``discovery.page_url``, one of
                ``discovery.link_selector`` or ``discovery.link_pattern``,
                and ``discovery.version_pattern``.

        Returns:
            Discovered version, the matched link's URL, and
            ``"web_scrape"`` as the source identifier.

        Raises:
            ConfigError: When a selector or pattern matches nothing, or
                ``version_format`` cannot take the captured groups.
            NetworkError: On page fetch failure, a page larger than NAPT
                parses, or a matched link too long to match a pattern on.

        """
        logger = get_global_logger()
        source = app_config["discovery"]
        page_url: str = source["page_url"]
        link_selector = source.get("link_selector")
        link_pattern = source.get("link_pattern")
        version_pattern: str = source["version_pattern"]
        version_format: str = source.get("version_format", _DEFAULT_VERSION_FORMAT)

        logger.verbose("DISCOVERY", "Strategy: web_scrape (version-first)")
        logger.verbose("DISCOVERY", f"Page URL: {page_url}")
        if link_selector:
            logger.verbose("DISCOVERY", f"Link selector (CSS): {link_selector}")
        if link_pattern:
            logger.verbose("DISCOVERY", f"Link pattern (regex): {link_pattern}")
        logger.verbose("DISCOVERY", f"Version pattern: {version_pattern}")

        logger.verbose("DISCOVERY", f"Fetching page: {page_url}")
        response = fetch(page_url, what="page")

        if len(response.content) > _MAX_PAGE_BYTES:
            raise NetworkError(
                f"Page is {len(response.content)} bytes; NAPT parses download "
                f"pages of at most {_MAX_PAGE_BYTES} bytes"
            )
        html_content = response.text
        logger.verbose("DISCOVERY", f"Page fetched ({len(response.content)} bytes)")

        if link_selector:
            soup = BeautifulSoup(html_content, "html.parser")
            element = soup.select_one(link_selector)
            if not element:
                raise ConfigError(
                    f"CSS selector {link_selector!r} did not match any elements on page"
                )
            href = element.get("href")
            if not isinstance(href, str) or not href:
                raise ConfigError(
                    f"Element matched by {link_selector!r} has no href attribute"
                )
            logger.verbose("DISCOVERY", f"Found link via CSS: {href}")
        else:
            href = first_capture(re.compile(link_pattern), html_content)
            if href is None:
                raise ConfigError(
                    f"Regex pattern {link_pattern!r} did not match anything on page"
                )
            logger.verbose("DISCOVERY", f"Found link via regex: {href}")

        download_url = bounded(urljoin(page_url, href), "The matched download link")
        logger.verbose("DISCOVERY", f"Download URL: {download_url}")

        match = re.compile(version_pattern).search(download_url)
        if not match:
            raise ConfigError(
                f"Version pattern {version_pattern!r} did not match "
                f"URL {download_url!r}"
            )

        # A group that took no part in the match would format as the text
        # "None", so it counts as no match.
        groups = match.groups()
        if any(group is None for group in groups):
            raise ConfigError(
                f"Version pattern {version_pattern!r} did not match "
                f"URL {download_url!r}: a capture group matched nothing"
            )

        if not groups:
            version_str = match.group(0)
        else:
            try:
                version_str = version_format.format(*groups)
            except (IndexError, KeyError, ValueError) as err:
                raise ConfigError(
                    f"version_format {version_format!r} failed with "
                    f"groups {groups}: {err}"
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
        errors: list[str] = []
        source = app_config.get("discovery", {})

        require_str(source, "page_url", errors)

        if "link_selector" not in source and "link_pattern" not in source:
            errors.append(
                "discovery: Missing required field: link_selector or link_pattern"
            )
        elif "link_selector" in source and "link_pattern" in source:
            errors.append("discovery: Set link_selector or link_pattern, not both")

        link_selector = optional_str(source, "link_selector", errors)
        if link_selector is not None:
            try:
                BeautifulSoup("<html></html>", "html.parser").select_one(link_selector)
            except Exception as err:
                errors.append(f"discovery.link_selector: Invalid CSS selector: {err}")

        link_pattern = optional_str(source, "link_pattern", errors)
        if link_pattern is not None:
            check_regex(link_pattern, "link_pattern", errors)

        version_pattern = require_str(source, "version_pattern", errors)
        if version_pattern is not None:
            check_regex(version_pattern, "version_pattern", errors)

        version_format = optional_str(source, "version_format", errors)
        if version_format is not None:
            check_format(version_format, "version_format", errors)

        return errors
