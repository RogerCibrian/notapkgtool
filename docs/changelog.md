# Changelog

All notable changes to NAPT (Not a Pkg Tool) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Deployment configuration** - New `deployment:` recipe section:
    `require_pending` makes `napt upload` fail unless the release was
    recorded at discovery (for review-gated publish workflows);
    `rings`, `install`, and `retain_versions` define update promotion
    policy for the upcoming `napt promote` command. Group name resolution
    requires the `Group.Read.All` application permission

- **Deployment state files** - `napt discover` records each discovered
    release in `state/deployment/{id}.json` as a pending publication
    candidate. One file per app; the newest discovery wins
- **Idempotent upload** - Re-running `napt upload` adopts the existing
    NAPT-stamped Intune apps for a release instead of creating duplicates,
    and resumes the content upload when a previous run crashed mid-publish.
    Pass `--force` to re-send metadata and content to the existing apps
    (e.g., after changing PSADT commands without a new installer release)
- **Upload provenance** - `napt upload` stamps each Intune app entry's
    notes field with `napt/v1 id=<recipe-id> entry=<install|update>
    sha256=<hash>` and records the published version, hash, and Intune
    app IDs in deployment state
- **Installer hash verification** - `napt upload` refuses to publish a
    package whose installer hash does not match the pending release
    recorded at discovery, so what was approved is exactly what ships

### Changed

- **BREAKING: `intune.notes` removed** - The Intune notes field is
    reserved for NAPT's provenance stamp. Move any notes content to
    `intune.description` or `intune.owner`
- **BREAKING: Discovery cache moved** - `state/versions.json` is now
    `cache/discovery.json`, and `napt discover --state-file` was renamed
    to `--cache-file`. Delete the old file; the cache rebuilds on the
    next run
    - New `directories.cache` and `directories.state` settings
    - `--stateless` also skips deployment state writes
    - `napt init` additionally creates `state/deployment/`

## [0.6.0] - 2026-07-04

### Added

- **Auto-generated MSI install/uninstall commands** - `napt build` now
    generates install (`Start-ADTMsiProcess`, with `ALLUSERS=1` appended
    for system deployments) and uninstall (`Uninstall-ADTApplication` by
    exact ProductName) commands for MSI installers, so MSI recipes no
    longer need `psadt.install` or `psadt.uninstall`. Uninstall matches by
    name, not ProductCode, so it keeps working when vendors change the
    ProductCode between versions. Set `psadt.override_msi_commands: true`
    to use recipe commands instead

- **Automatic app icon extraction** - `napt build` extracts the app icon
    from MSI, EXE, and MSIX installers to `icons/{id}.png`, and
    `napt upload` sends it as the app logo in Intune and the Company
    Portal. Only PNG-encoded frames of at least 128px are used, preferring
    the size closest to Intune's recommended 256px. Drop a custom PNG at
    `icons/{id}.png` to override (NAPT never overwrites existing files),
    or set `intune.logo_path` to disable extraction for a recipe
- **`{{installer_filename}}` recipe variable** - Substituted at build time
    in `psadt.install`, `psadt.uninstall`, and `psadt.app_vars` with the
    exact filename of the downloaded installer in the package's Files
    directory. Replaces wildcard paths, which PSADT does not support
- **Unrecognized variable warning** - `napt build` warns when an
    `app_vars` value or an install/uninstall script contains a
    `{{snake_case}}` token that is not a supported NAPT variable

### Changed

- **BREAKING: Recipe variable syntax** - NAPT build-time variables now use
    `{{...}}` instead of `${...}`. Replace `${discovered_version}` with
    `{{discovered_version}}` in recipes. `${...}` now exclusively means
    environment variables, which work only in `discovery.token` and
    `discovery.headers`
- **`intune.logo_path` file types restricted to PNG and JPEG** - Other
    file types now warn and fall back to the extracted icon instead of
    uploading with a guessed MIME type

### Fixed

- Fixed the version variable never being substituted in `psadt.install`
    and `psadt.uninstall` scripts, where it reached PowerShell as literal
    `${...}` syntax and silently expanded to an empty string at deploy time
- Fixed 7-Zip recipes failing at deploy time because PSADT resolves
    `-FilePath` literally and does not expand wildcards; the recipes now
    use `{{installer_filename}}`
- Fixed `intune.logo_path` relative paths resolving from the current
    working directory instead of the recipe file's location as documented

## [0.5.1] - 2026-06-22

### Fixed

- Fixed system-scope MSIX detection and requirements scripts matching any
    installed package instead of only the target app, which could cause Intune
    to report the wrong install state
- Fixed malformed timestamps in detection and requirements script logs when
    the device is in a UTC+ timezone, which made CMTrace display incorrect
    log times
- Fixed detection and requirements scripts failing to detect installed apps
    whose registry version contains non-numeric text (e.g. `5.2 (64-bit)`)
- Fixed generated detection and requirements scripts breaking when the app
    name contains special characters such as quotes or dollar signs
- Fixed crash when an MSIX manifest's `<PublisherDisplayName/>` element is present but contains no text. Publisher now defaults to an empty string in that case instead of triggering a downstream `TypeError`.

## [0.5.0] - 2026-04-05

### Added

- **Automatic recipe validation in pipeline commands** - `napt discover`,
    `napt build`, and `napt upload` now validate the merged configuration
    before proceeding. Invalid recipes produce clear error messages instead
    of failing with unexpected errors mid-pipeline
- **Configuration provenance in `napt validate --debug`** - Shows which
    config layer (code default, org.yaml, vendor defaults, or recipe) set
    each value. Helps debug unexpected configuration by tracing the full
    merge history
- **MSIX installer support** - NAPT now supports `.msix` installers alongside
    MSI and EXE. Metadata (display name, version, architecture, package
    identity) is extracted from `AppxManifest.xml` inside the package.
    Detection and requirements scripts query the AppX package database; install
    and uninstall commands are auto-generated from manifest metadata unless
    overridden with `psadt.override_msix_commands: true`. Install scope is
    controlled by `intune.run_as_account`: `"system"` (default) uses
    provisioned cmdlets (`Add-AppxProvisionedPackage` /
    `Remove-AppxProvisionedPackage`); `"user"` uses per-user cmdlets
    (`Add-AppxPackage` / `Remove-AppxPackage`). Detection and requirements
    scripts automatically query the correct store based on the same setting.
    `psadt.app_vars.RequireAdmin` defaults to `false` when scope is `"user"`
- **`intunewin.release` config key** - Pin `IntuneWinAppUtil.exe` to a specific
    release for reproducible builds (e.g., `release: "1.8.6"`). Defaults to
    `"latest"`, which resolves the current release via GitHub API. Each version
    is cached independently under `cache/tools/{version}/`
- **`logging:` top-level section** - New optional section for per-recipe logging
    configuration. Supports `log_format` (`cmtrace`, `text`), `log_level`
    (`verbose`, `debug`), and `log_rotation_mb`
- **New `intune:` fields** - Expanded metadata and upload behavior fields,
    all configurable at org, vendor, or recipe level: `developer`, `owner`,
    `notes`, `logo_path`, `minimum_supported_windows_release`,
    `install_command`, `uninstall_command`, `is_featured` (Company Portal
    featured app, defaults to `false`), `allow_available_uninstall`,
    `device_restart_behavior`, `max_run_time_minutes`,
    `enforce_signature_check`, and `run_as_32_bit`
- **Sample recipe: `recipes/Microsoft/vscode.yaml`** - New example recipe for
    Visual Studio Code using the `api_json` strategy

### Changed

- **Build script module restructured** - Detection and requirements script
    generation consolidated into `registry_scripts` module (registry-based
    MSI/EXE) and new `msix_scripts` module (AppX-based MSIX). Shared
    PowerShell logging functions split from registry-specific helpers for
    cleaner template reuse
- **BREAKING: Recipe schema flattened** - The `app:` wrapper is removed. Fields
    `name`, `id`, `discovery:`, `psadt:`, `intune:`, and `logging:` are now
    top-level. Update all recipes by moving fields out of `app:`
- **BREAKING: `source:` renamed to `discovery:`** - All discovery configuration
    must move from `source:` to `discovery:`. Affects all four strategies:
    `api_github`, `api_json`, `url_download`, `web_scrape`
- **BREAKING: `win32.installed_check` replaced by `intune.detection`** -
    Detection configuration moves from `win32.installed_check.*` to
    `intune.detection.*`. Fields are unchanged (`display_name`, `architecture`,
    `exact_match`, `override_msi_display_name`)
- **BREAKING: Directory config keys renamed** - `defaults.discover.output_dir`,
    `defaults.build.output_dir`, and `defaults.package.output_dir` are now
    `directories.discover`, `directories.build`, and `directories.package`.
    Update `defaults/org.yaml` if you set these keys

### Fixed

- **Cached installer filename now survives re-runs** - NAPT stores the actual
    downloaded filename in state after each download. On subsequent runs,
    cache hits use the stored path instead of re-deriving from the recipe URL.
    Previously, if the server returned a `Content-Disposition` header or the
    download URL redirected to a different path, the cached file could not be
    found and the run would fail
- **Incomplete or stale cache no longer requires `--stateless`** - If the
    cache is missing fields or the cached file was deleted, NAPT automatically
    forces a fresh download instead of failing with a confusing error message
- **`intune.device_restart_behavior` default corrected to
    `"basedOnReturnCode"`** - Previously an inline fallback used `"allow"`
    instead of the value defined in `DEFAULT_CONFIG`
- **`napt upload` now creates two Intune Win32 app entries when `build_types`
    is `"both"`** - Previously only one entry was created regardless of
    `build_types`. The install entry (detection script only, base app name) and
    the update entry (detection + requirements scripts, prefixed with
    `update_name_prefix`) are now each created, uploaded, and committed in
    sequence. Single-entry behavior for `"app_only"` and `"update_only"` is
    unchanged
- **Version cache uses semantic comparison** - Versions with a `v` prefix
    (e.g., `v1.2.3` vs `1.2.3`) are now correctly recognized as matching
    and won't re-download unnecessarily

## [0.4.0] - 2026-03-08

### Added

- **`napt upload <recipe>`** - New command uploads `.intunewin` packages directly to Microsoft Intune via the Graph API. Authentication tries service principal (`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`), then managed identity, then device code (requires `AZURE_CLIENT_ID` + `AZURE_TENANT_ID` set and a TTY)
- **`napt package --version VERSION`** - New flag to target a specific build
    version instead of the most recent (e.g.,
    `napt package recipes/Google/chrome.yaml --version 130.0.6723.116`)
- **Configurable directory defaults and new CLI flags** - All pipeline directory
    flags now read from `defaults/org.yaml` when not set on the CLI, and new
    flags are available on each command:
    - `napt discover --output-dir DIR` - where to save downloaded installers
    - `napt build --downloads-dir DIR` - where to find the installer
    - `napt build --output-dir DIR` - where to save builds
    - `napt package --builds-dir DIR` - where to find the build
    - `napt package --output-dir DIR` - where to save packages
    Three new config keys control the defaults: `defaults.discover.output_dir`
    (`downloads`), `defaults.build.output_dir` (`builds`), and
    `defaults.package.output_dir` (`packages`). Each key is shared between the
    command that produces and the command that consumes the directory
- **Code-Based Defaults** - NAPT now ships with complete built-in defaults, making `pip install napt` work out of the box without requiring any configuration files. Organization defaults (`defaults/org.yaml`) and vendor defaults are now optional overrides rather than requirements
- **`napt init` Command** - New command to scaffold NAPT project structure. Creates `recipes/`, `defaults/vendors/`, and a commented `defaults/org.yaml` template. Safely skips existing files; use `--force` to overwrite with automatic backup

### Changed

- **`napt package` now takes `<recipe>` instead of `<build_dir>`** - All commands now take a recipe path for consistent CLI usage. The build directory is inferred automatically from the recipe's app ID by scanning the builds output directory for the most recent completed build
- **`napt package` outputs to versioned paths** - Package output is now
    `packages/{app_id}/{version}/Invoke-AppDeployToolkit.intunewin`. Only one
    version is kept per app — the previous version directory is removed
    automatically when a new one is packaged (single-slot). Detection and
    requirements scripts are copied alongside the `.intunewin` file so
    `napt upload` is self-contained and does not need the builds directory
- **Four-Layer Configuration** - Configuration system now has four layers: code defaults (baseline) -> org.yaml (optional) -> vendor.yaml (optional) -> recipe (required). Old configs continue to work; new fields automatically get code defaults

## [0.3.1] - 2026-02-03

### Changed

- **PyPI Package Name** - Package renamed from `notapkgtool` to `napt` for simpler installation (`pip install napt`)
- **Automated PyPI Publishing** - Releases now automatically publish to PyPI via GitHub Actions using Trusted Publisher (OIDC)

## [0.3.0] - 2026-02-02

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


[Unreleased]: https://github.com/RogerCibrian/notapkgtool/compare/0.6.0...HEAD
[0.6.0]: https://github.com/RogerCibrian/notapkgtool/compare/0.5.1...0.6.0
[0.5.1]: https://github.com/RogerCibrian/notapkgtool/compare/0.5.0...0.5.1
[0.5.0]: https://github.com/RogerCibrian/notapkgtool/compare/0.4.0...0.5.0
[0.4.0]: https://github.com/RogerCibrian/notapkgtool/compare/0.3.1...0.4.0
[0.3.1]: https://github.com/RogerCibrian/notapkgtool/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/RogerCibrian/notapkgtool/compare/0.2.0...0.3.0
[0.2.0]: https://github.com/RogerCibrian/notapkgtool/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/RogerCibrian/notapkgtool/releases/tag/0.1.0

