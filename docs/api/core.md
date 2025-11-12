# core

Core orchestration module for NAPT.

The orchestration uses a two-path architecture that automatically optimizes based on discovery strategy capabilities:

- **Version-First Path**: For strategies with `get_version_info()` method (web_scrape, api_github, api_json), discovers version first, compares to cache, and skips downloads entirely when unchanged.

- **File-First Path**: For strategies with only `discover_version()` method (url_download), uses HTTP ETag conditional requests to minimize bandwidth.

::: notapkgtool.core

