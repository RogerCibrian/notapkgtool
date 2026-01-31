# Changelog

All notable changes to NAPT (Not a Pkg Tool) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Win32 Configuration Validation** - Recipe validation now checks `win32` configuration fields for correct types and values, with typo detection suggesting similar field names (e.g., "Did you mean 'display_name'?")
- **Detection Script Generation** - Automatic PowerShell detection script generation for Intune Win32 app deployments during build process. Scripts check Windows uninstall registry keys, support exact or minimum version matching, and include CMTrace-formatted logging
- **Requirements Script Generation** - Automatic PowerShell requirements script generation for Intune Update app entries. Scripts check if an older version is installed and output "Required" when applicable
- **Installer Type Filtering** - Detection and requirements scripts now filter registry entries based on installer type. MSI builds strictly match MSI registry entries only; EXE builds permissively match any entry to handle EXE installers that run embedded MSIs internally
- **Architecture-Aware Detection** - Detection and requirements scripts now use explicit registry views based on target architecture, preventing false positives when x86 and x64 versions coexist. MSI architecture is auto-detected from Template property; non-MSI installers require `win32.installed_check.architecture` configuration (x86, x64, arm64, or any)
- **MSI Display Name Override** - New `override_msi_display_name` flag allows using custom `display_name` instead of MSI ProductName for registry lookups, solving edge cases where ProductName contains version numbers (e.g., "7-Zip 25.01"). Supports wildcards (`*`, `?`) for flexible matching

### Changed

- **BREAKING: Non-MSI Architecture Required** - `win32.installed_check.architecture` is now required for non-MSI installers (EXE, etc.). Allowed values: `x86`, `x64`, `arm64`, `any`
- **Discovery Performance Optimization** - Version-first strategies (web_scrape, api_github, api_json) now check versions before downloading, enabling ~100-300ms update checks when unchanged instead of full downloads
- State file now saves actual download URLs for all strategies
- **url_download Strategy Simplification** - Removed `version.type` configuration requirement. MSI files are now auto-detected by file extension (`.msi`) for version extraction
- **BREAKING: Uniform Strategy Naming** - Discovery strategies renamed to follow consistent `<source>_<method>` pattern for better discoverability and scalability:
    - `http_static` → `url_download` (fixed URL with file extraction)
    - `url_regex` → `web_scrape` (web scraping for vendor download pages)
    - `http_json` → `api_json` (generic JSON API queries)
    - `github_release` → `api_github` (GitHub releases API)
- **BREAKING: Simplified Version Types** - Version type names shortened for clarity:
    - `msi_product_version_from_file` → `msi`
    - Removed nested `version.type` for `web_scrape` (simplified to `source.link_selector` and `source.version_pattern`)
- **BREAKING: Recipe Format Change** - Changed recipe format from `apps:` array to `app:` single object. Recipes now define a single application per file instead of an array. This simplifies the schema and matches actual usage (only one app was ever processed per recipe).
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

