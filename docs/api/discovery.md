# Discovery Module

The discovery module implements the strategy pattern for obtaining application installers and extracting version information.

## Base Protocol

::: notapkgtool.discovery.base
    options:
      show_root_heading: true
      show_source: true

## HTTP Static Strategy

::: notapkgtool.discovery.http_static
    options:
      show_root_heading: true
      show_source: true

## URL Regex Strategy

::: notapkgtool.discovery.url_regex
    options:
      show_root_heading: true
      show_source: true

## GitHub Release Strategy

::: notapkgtool.discovery.github_release
    options:
      show_root_heading: true
      show_source: true

## HTTP JSON Strategy

::: notapkgtool.discovery.http_json
    options:
      show_root_heading: true
      show_source: true

