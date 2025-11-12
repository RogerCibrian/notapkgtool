"""Web scraping discovery strategy for NAPT.

This is a VERSION-FIRST strategy that scrapes vendor download pages to find
download links and extract version information from those links. This enables
version discovery for vendors that don't provide APIs or static URLs.

Key Advantages:

- Discovers versions from vendor download pages
- Works for vendors without APIs or GitHub releases
- Version-first caching (can skip downloads when version unchanged)
- Supports both CSS selectors (recommended) and regex (fallback)
- No dependency on HTML structure stability (with good selectors)
- Handles relative and absolute URLs automatically

Supported Link Finding:

- CSS selectors: Modern, robust, recommended approach
- Regex patterns: Fallback for edge cases or when CSS won't work

Version Extraction:

- Extract version from the discovered download URL using regex
- Support for captured groups with formatting
- Transform version numbers (e.g., "2501" -> "25.01")

Use Cases:

- Vendors with download pages listing multiple versions (7-Zip, etc.)
- Legacy software without modern APIs
- Small vendors with simple download pages
- When GitHub releases and JSON APIs aren't available

Recipe Configuration:

    source:
      strategy: web_scrape
      page_url: "https://www.7-zip.org/download.html"
      link_selector: 'a[href$="-x64.msi"]'        # CSS (recommended)
      version_pattern: "7z(\\d{2})(\\d{2})-x64"   # Extract from URL
      version_format: "{0}.{1}"                    # Transform to "25.01"

Alternative with regex:

    source:
      strategy: web_scrape
      page_url: "https://vendor.com/downloads"
      link_pattern: 'href="(/files/app-v[0-9.]+-x64\\.msi)"'
      version_pattern: "app-v([0-9.]+)-x64"

Configuration Fields:

- **page_url** (str, required): URL of the page to scrape for download links
- **link_selector** (str, optional): CSS selector to find download link. Recommended approach. Example: 'a[href$=".msi"]' finds links ending with .msi
- **link_pattern** (str, optional): Regex pattern as fallback when CSS won't work. Must have one capture group for the URL. Example: 'href="([^"]*\\.msi)"'
- **version_pattern** (str, required): Regex pattern to extract version from the discovered URL. Use capture groups to extract version parts. Example: "app-(\\d+\\.\\d+)" or "7z(\\d{2})(\\d{2})"
- **version_format** (str, optional): Python format string to combine captured groups. Use {0}, {1}, etc. for groups. Example: "{0}.{1}" transforms captures "25", "01" into "25.01". Defaults to "{0}" (first capture group only).

Error Handling:

- ValueError: Missing or invalid configuration fields
- RuntimeError: Page download failures, selector/pattern not found
- Errors are chained with 'from err' for better debugging

Finding CSS Selectors:

    Use browser DevTools:

    1. Open download page in Chrome/Edge/Firefox
    2. Right-click download link -> Inspect
    3. Right-click highlighted element -> Copy -> Copy selector
    4. Simplify selector (e.g., 'a[href$=".msi"]' instead of complex nth-child)

Common CSS Patterns:

- 'a[href$=".msi"]' - Links ending with .msi
- 'a[href*="x64"]' - Links containing "x64"
- 'a.download' - Links with class="download"
- 'a[href$="-x64.msi"]:first-of-type' - First matching link

Example:
In a recipe YAML:

    apps:
      - name: "7-Zip"
        id: "napt-7zip"
        source:
          strategy: web_scrape
          page_url: "https://www.7-zip.org/download.html"
          link_selector: 'a[href$="-x64.msi"]'
          version_pattern: "7z(\\d{2})(\\d{2})-x64"
          version_format: "{0}.{1}"

From Python (version-first approach):

    from notapkgtool.discovery.web_scrape import WebScrapeStrategy
    from notapkgtool.io import download_file

    strategy = WebScrapeStrategy()
    app_config = {
        "source": {
            "page_url": "https://www.7-zip.org/download.html",
            "link_selector": 'a[href$="-x64.msi"]',
            "version_pattern": "7z(\\d{2})(\\d{2})-x64",
            "version_format": "{0}.{1}",
        }
    }

    # Get version WITHOUT downloading installer
    version_info = strategy.get_version_info(app_config)
    print(f"Latest version: {version_info.version}")

    # Download only if needed
    if need_to_download:
        file_path, sha256, headers = download_file(
            version_info.download_url, Path("./downloads")
        )
        print(f"Downloaded to {file_path}")

From Python (using core orchestration):

    from pathlib import Path
    from notapkgtool.core import discover_recipe

    # Automatically uses version-first optimization
    result = discover_recipe(Path("recipe.yaml"), Path("./downloads"))
    print(f"Version {result['version']} at {result['file_path']}")

Note:
    - Version discovery via web scraping (no installer download required)
    - Core orchestration automatically skips download if version unchanged
    - CSS selectors are recommended (more robust than regex)
    - Use browser DevTools to find selectors easily
    - Selector should match exactly one link (first match is used)
    - BeautifulSoup4 required for CSS selectors
    - Regex fallback works without BeautifulSoup

"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

from notapkgtool.versioning.keys import VersionInfo

from .base import register_strategy


class WebScrapeStrategy:
    """Discovery strategy for web scraping download pages.

    Configuration example:
        source:
          strategy: web_scrape
          page_url: "https://vendor.com/download.html"
          link_selector: 'a[href$=".msi"]'
          version_pattern: "app-v([0-9.]+)"
    """

    def get_version_info(
        self,
        app_config: dict[str, Any],
        verbose: bool = False,
        debug: bool = False,
    ) -> VersionInfo:
        """Scrape download page for version and URL without downloading (version-first path).

        This method scrapes an HTML page, finds a download link using CSS selector
        or regex, extracts the version from that link, and returns version info.
        If the version matches cached state, the download can be skipped entirely.

        Args:
            app_config: App configuration containing source.page_url,
                source.link_selector or source.link_pattern, and
                source.version_pattern.
            verbose: If True, print verbose logging messages.
                Defaults to False.
            debug: If True, print debug logging messages.
                Defaults to False.

        Returns:
            Version info with version string, download URL, and
                source name.

        Raises:
            ValueError: If required config fields are missing, invalid, or if
                selectors/patterns don't match anything.
            RuntimeError: If page download fails (chained with 'from err').

        Example:
            Scrape 7-Zip download page:

                strategy = WebScrapeStrategy()
                config = {
                    "source": {
                        "page_url": "https://www.7-zip.org/download.html",
                        "link_selector": 'a[href$="-x64.msi"]',
                        "version_pattern": "7z(\\d{2})(\\d{2})-x64",
                        "version_format": "{0}.{1}"
                    }
                }
                version_info = strategy.get_version_info(config)
                # version_info.version returns: '25.01'

        """
        from notapkgtool.cli import print_verbose

        # Validate configuration
        source = app_config.get("source", {})
        page_url = source.get("page_url")
        if not page_url:
            raise ValueError("web_scrape strategy requires 'source.page_url' in config")

        link_selector = source.get("link_selector")
        link_pattern = source.get("link_pattern")

        if not link_selector and not link_pattern:
            raise ValueError(
                "web_scrape strategy requires either 'source.link_selector' or "
                "'source.link_pattern' in config"
            )

        version_pattern = source.get("version_pattern")
        if not version_pattern:
            raise ValueError(
                "web_scrape strategy requires 'source.version_pattern' in config"
            )

        version_format = source.get("version_format", "{0}")

        print_verbose("DISCOVERY", "Strategy: web_scrape (version-first)")
        print_verbose("DISCOVERY", f"Page URL: {page_url}")
        if link_selector:
            print_verbose("DISCOVERY", f"Link selector (CSS): {link_selector}")
        if link_pattern:
            print_verbose("DISCOVERY", f"Link pattern (regex): {link_pattern}")
        print_verbose("DISCOVERY", f"Version pattern: {version_pattern}")

        # Download the HTML page
        print_verbose("DISCOVERY", f"Fetching page: {page_url}")
        try:
            response = requests.get(page_url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            raise RuntimeError(
                f"Failed to fetch page: {response.status_code} {response.reason}"
            ) from err
        except requests.exceptions.RequestException as err:
            raise RuntimeError(f"Failed to fetch page: {err}") from err

        html_content = response.text
        print_verbose("DISCOVERY", f"Page fetched ({len(html_content)} bytes)")

        # Find download link using CSS selector or regex
        download_url = None

        if link_selector:
            # Use CSS selector with BeautifulSoup4
            soup = BeautifulSoup(html_content, "html.parser")
            element = soup.select_one(link_selector)

            if not element:
                raise ValueError(
                    f"CSS selector {link_selector!r} did not match any elements on page"
                )

            # Get href attribute
            href = element.get("href")
            if not href:
                raise ValueError(
                    f"Element matched by {link_selector!r} has no href attribute"
                )

            print_verbose("DISCOVERY", f"Found link via CSS: {href}")

            # Build absolute URL
            download_url = urljoin(page_url, href)

        elif link_pattern:
            # Use regex fallback
            try:
                pattern = re.compile(link_pattern)
                match = pattern.search(html_content)

                if not match:
                    raise ValueError(
                        f"Regex pattern {link_pattern!r} did not match anything on page"
                    )

                # Get first capture group or full match
                if pattern.groups > 0:
                    href = match.group(1)
                else:
                    href = match.group(0)

                print_verbose("DISCOVERY", f"Found link via regex: {href}")

                # Build absolute URL
                download_url = urljoin(page_url, href)

            except re.error as err:
                raise ValueError(
                    f"Invalid link_pattern regex: {link_pattern!r}"
                ) from err

        print_verbose("DISCOVERY", f"Download URL: {download_url}")

        # Extract version from the download URL
        try:
            version_regex = re.compile(version_pattern)
            match = version_regex.search(download_url)

            if not match:
                raise ValueError(
                    f"Version pattern {version_pattern!r} did not match URL {download_url!r}"
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
                    raise ValueError(
                        f"version_format {version_format!r} failed with groups {groups}: {err}"
                    ) from err

        except re.error as err:
            raise ValueError(
                f"Invalid version_pattern regex: {version_pattern!r}"
            ) from err

        print_verbose("DISCOVERY", f"Extracted version: {version_str}")

        return VersionInfo(
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
        source = app_config.get("source", {})

        # Check page_url
        if "page_url" not in source:
            errors.append("Missing required field: source.page_url")
        elif not isinstance(source["page_url"], str):
            errors.append("source.page_url must be a string")
        elif not source["page_url"].strip():
            errors.append("source.page_url cannot be empty")

        # Check that at least one link finding method is provided
        link_selector = source.get("link_selector")
        link_pattern = source.get("link_pattern")

        if not link_selector and not link_pattern:
            errors.append(
                "Missing required field: must provide either source.link_selector or source.link_pattern"
            )

        # Validate link_selector if provided
        if link_selector:
            if not isinstance(link_selector, str):
                errors.append("source.link_selector must be a string")
            elif not link_selector.strip():
                errors.append("source.link_selector cannot be empty")
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
                errors.append("source.link_pattern must be a string")
            elif not link_pattern.strip():
                errors.append("source.link_pattern cannot be empty")
            else:
                # Validate regex compiles
                try:
                    re.compile(link_pattern)
                except re.error as err:
                    errors.append(f"Invalid link_pattern regex: {err}")

        # Check version_pattern
        if "version_pattern" not in source:
            errors.append("Missing required field: source.version_pattern")
        elif not isinstance(source["version_pattern"], str):
            errors.append("source.version_pattern must be a string")
        elif not source["version_pattern"].strip():
            errors.append("source.version_pattern cannot be empty")
        else:
            # Validate regex compiles
            try:
                re.compile(source["version_pattern"])
            except re.error as err:
                errors.append(f"Invalid version_pattern regex: {err}")

        # Validate version_format if provided
        if "version_format" in source:
            if not isinstance(source["version_format"], str):
                errors.append("source.version_format must be a string")
            elif not source["version_format"].strip():
                errors.append("source.version_format cannot be empty")

        return errors


# Register this strategy when the module is imported
register_strategy("web_scrape", WebScrapeStrategy)
