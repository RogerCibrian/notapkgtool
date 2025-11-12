# discovery

The discovery module implements the strategy pattern for obtaining application installers and extracting version information.

NAPT supports two types of discovery strategies:

- **Version-First Strategies** (url_pattern, api_github, api_json): Discover version without downloading, enabling instant update checks and the ability to skip downloads entirely when versions are unchanged.

- **File-First Strategy** (url_download): Must download file to extract version, uses HTTP ETag conditional requests for optimization.

::: notapkgtool.discovery.base

::: notapkgtool.discovery.url_download

::: notapkgtool.discovery.url_pattern

::: notapkgtool.discovery.api_github

::: notapkgtool.discovery.api_json

