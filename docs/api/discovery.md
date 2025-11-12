# discovery

The discovery module implements the strategy pattern for obtaining application installers and extracting version information.

NAPT supports two types of discovery strategies:

- **Version-First Strategies** (web_scrape, api_github, api_json): Discover version without downloading, enabling fast update checks (~100-300ms) and the ability to skip downloads entirely when versions are unchanged.

- **File-First Strategy** (url_download): Must download file to extract version, uses HTTP ETag conditional requests for optimization.

::: notapkgtool.discovery.base

::: notapkgtool.discovery.url_download

::: notapkgtool.discovery.web_scrape

::: notapkgtool.discovery.api_github

::: notapkgtool.discovery.api_json

