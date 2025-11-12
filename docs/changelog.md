# Changelog

All notable changes to NAPT (Not a Pkg Tool) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

- **BREAKING: Uniform Strategy Naming** - Discovery strategies renamed to follow consistent `<source>_<method>` pattern for better discoverability and scalability:
  - `http_static` → `url_download` (fixed URL with file extraction)
  - `url_regex` → `url_pattern` (version extraction from URL patterns)
  - `http_json` → `api_json` (generic JSON API queries)
  - `github_release` → `api_github` (GitHub releases API)
- **BREAKING: Simplified Version Types** - Version type names shortened for clarity:
  - `msi_product_version_from_file` → `msi`
  - Removed nested `version.type` for `url_pattern` (now uses `source.pattern` directly)
- **Discovery Performance Optimization** - Version-first strategies (url_pattern, api_github, api_json) now check versions before downloading, enabling instant to ~100ms update checks when unchanged instead of full downloads
- State file now saves actual download URLs for all strategies
- **Documentation Rendering** - Fixed module docstrings to follow Google-style format with proper indentation for mkdocstrings

### Fixed

- Fixed ETag preservation bug causing alternating download/cached behavior in url_download strategy
- Fixed docstring formatting issues across multiple modules (missing blank lines, incorrect Args sections)

## [0.2.0] - 2025-11-07

### Added

- **PSADT Package Generation** with `napt build` command - Creates complete PSADT v4 deployment packages with custom branding support
- **.intunewin Package Creation** with `napt package` command - Generates Intune-ready packages using Microsoft's IntuneWinAppUtil.exe
- **GitHub Release Strategy** (`api_github`) - Discovers versions from GitHub releases with asset pattern filtering
- **HTTP JSON Strategy** (`api_json`) - Extracts versions and download URLs from JSON API endpoints using JSONPath
- **URL Regex Strategy** (`url_pattern`) - Extracts versions directly from URLs using regex patterns
- **Roadmap Management** (`docs/roadmap.md`) - Structured feature tracking with status categories and workspace automation
- **MkDocs Documentation Site** - User guide and auto-generated API reference

### Changed

- **State File Schema v2** - Convention-based file paths, improved metadata tracking, per-app isolation (Breaking: old state files need regeneration)
- **CLI Commands** - Renamed `check` to `validate` for clarity
- **Recipe Format** - PSADT `install`/`uninstall` blocks now generate PSAppDeployToolkit v4 scripts
- **Console Output** - Replaced Unicode symbols with ASCII for Windows compatibility (`✓` → `[OK]`, etc.)

### Fixed

- **PSADT Template Handling** - Correctly identifies and copies PSAppDeployToolkit_Template_v4.zip files
- **ETag Preservation** - Fixed bug causing alternating download/cached behavior in url_download strategy
- **Branding Application** - Fixed Assets/ directory path resolution for custom icons and banners
- **Version Extraction** - Corrected regex escape sequences causing SyntaxWarnings

## [0.1.0] - 2025-10-23

Initial internal release.

### Added

- **Recipe Validation** with `napt check` command - Validates recipe syntax and configuration without network calls
- **HTTP Static Discovery** - Downloads installers from static URLs with ETag caching for efficiency
- **Three-Layer Configuration** - Organization defaults, vendor overrides, and recipe-specific settings with deep merging
- **Version Comparison** - Supports semantic versioning, MSI/EXE numeric versions, and Chrome-style multi-part versions
- **MSI Version Extraction** - Cross-platform support (Windows via msilib/PowerShell, Linux/macOS via msitools)
- **Robust Downloads** - Retry logic, atomic writes, SHA-256 verification, and conditional requests


[Unreleased]: https://github.com/RogerCibrian/notapkgtool/compare/0.2.0...HEAD
[0.2.0]: https://github.com/RogerCibrian/notapkgtool/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/RogerCibrian/notapkgtool/releases/tag/0.1.0

