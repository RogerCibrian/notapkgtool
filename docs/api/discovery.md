# discovery

The discovery module implements the strategy pattern for obtaining application installers and extracting version information.

NAPT supports two types of discovery strategies:

- **Version-First Strategies** (url_regex, github_release, http_json): Discover version without downloading, enabling instant update checks and the ability to skip downloads entirely when versions are unchanged.

- **File-First Strategy** (http_static): Must download file to extract version, uses HTTP ETag conditional requests for optimization.

::: notapkgtool.discovery.base

::: notapkgtool.discovery.http_static

::: notapkgtool.discovery.url_regex

::: notapkgtool.discovery.github_release

::: notapkgtool.discovery.http_json

