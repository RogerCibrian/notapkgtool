# Changelog

All notable changes to NAPT (Not a Pkg Tool) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

## [0.2.0] - 2025-11-07

### Added

#### Build & Packaging
- **PSADT Package Generation** with `napt build` command
  - Automatic download and caching of PSAppDeployToolkit v4 templates
  - Template customization with recipe install/uninstall scripts
  - Version injection from state files for all discovery strategies
  - Installer matching by app name/ID for accurate file selection
  - Complete PSADT v4 structure with all required files
  - Custom branding support (icons, banners) from brand-packs

- **.intunewin Package Creation** with `napt package` command
  - Automatic download and caching of IntuneWinAppUtil.exe
  - Integration with Microsoft's official packaging tool
  - Build directory validation before packaging
  - Ready-to-upload packages for Intune

#### Discovery Strategies
- **GitHub Release Strategy** (`github_release`)
  - Automatic latest release detection from GitHub API
  - Asset filtering by patterns
  - Version extraction from release tags
  - ETag caching for efficient updates

- **HTTP JSON Strategy** (`http_json`)
  - JSON API endpoint parsing with JSONPath
  - Flexible version and download URL extraction
  - Support for complex API responses

- **URL Regex Strategy** (`url_regex`)
  - Version extraction from URLs using regex
  - Support for web scrapers and custom endpoints
  - Flexible pattern matching

#### State Management
- **State File Schema v2**
  - Convention-based file paths derived from URLs
  - Metadata tracking (ETag, SHA-256, known_version)
  - NAPT version tracking for compatibility
  - Per-app state isolation
  - Efficient re-runs with cached metadata

#### Testing Infrastructure
- **Hybrid Testing Strategy**
  - Unit tests with mocked/fake data for speed
  - Integration tests with real PSADT templates
  - Network-dependent tests marked appropriately
  - Session-scoped fixtures for expensive operations
  - Pytest markers (`@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.network`)

#### Documentation & Project Management
- **ROADMAP.md** for tracking future features
  - Categorized by status (Ideas, Investigating, Ready, Completed, Declined)
  - Complexity and value assessments
  - Technical considerations and blockers
  - Workspace rule for automatic updates

- **Comprehensive Test Documentation**
  - Testing philosophy and strategy explained
  - Running tests by category
  - Coverage guidelines and best practices

### Changed

- **CLI Commands**: Reorganized to reflect implemented vs. future commands
  - Implemented: `validate`, `discover`, `build`, `package`
  - Future: `upload`, `sync`

- **Recipe Format**: Enhanced PSADT section
  - `install` and `uninstall` blocks now generate PSADT v4 scripts
  - Support for PSAppDeployToolkit v4 cmdlets

- **Sample Recipes**: Updated to PSADT v4 best practices
  - Chrome: Uses `Start-ADTMsiProcess` and `Uninstall-ADTApplication`
  - Git: Uses `Start-ADTProcess` and `Uninstall-ADTApplication`
  - JSON API examples: Updated with modern patterns

- **Build Manager**: State-based version fallback
  - Supports building apps discovered via any strategy
  - Uses `known_version` from state when file extraction not available
  - Prioritizes installer matching by app name/ID

- **Console Output**: Removed Unicode characters for Windows compatibility
  - Replaced ✓ with `[OK]`
  - Replaced ✗ with `[ERROR]`
  - Replaced ⚠ with `[WARNING]`
  - Replaced → with `->`

### Fixed

- **PSADT Template Handling**
  - Correctly identifies PSAppDeployToolkit_Template_v4.zip from releases
  - Copies all required files from template root
  - Places Invoke-AppDeployToolkit.exe in correct location

- **Branding Application**
  - Fixed target path to use root Assets/ directory
  - Corrected Banner.Classic.png suffix handling

- **Discovery Error Handling**
  - Proper exception chaining with `from None`
  - Convention-based cache file path derivation (schema v2)

- **Version Extraction**
  - SyntaxWarnings in regex patterns corrected
  - MSI ProductVersion extraction reliability improved

- **Git Workflow**
  - Git operations respect hooks and require explicit signing
  - No automatic force-push or --no-verify flags

### Developer Experience

- **Workspace Rules**
  - PSADT reference documentation auto-loaded
  - Git workflow conventions enforced
  - Roadmap management automated
  - No backward compatibility required pre-1.0.0

- **Code Quality**
  - Ruff and Black integration in workflow
  - Import organization and formatting automated
  - Pytest configuration with strict markers

### Breaking Changes

> **Note**: NAPT has not been publicly released yet (0.1.0 was internal only).
> Breaking changes are acceptable until 1.0.0 release.

- State file schema changed to v2 (convention-based paths)
- Old state files will need to be regenerated
- CLI command structure finalized

## [0.1.0] - 2025-10-23

### Added

#### CLI & Core Functionality
- **Recipe validation** with `napt check` command
- Core orchestration for recipe → discover → download → extract workflow
- Command-line interface with argparse
- Verbose mode for detailed error tracebacks
- Structured result output for programmatic use

#### Configuration System
- Three-layer YAML configuration merging (organization → vendor → recipe)
- Deep merge for dictionaries with "last wins" semantics
- Automatic vendor detection from directory structure
- Relative path resolution for relocatable recipes
- Dynamic value injection (e.g., AppScriptDate)

#### Discovery Strategies
- Strategy pattern with protocol-based design
- Plugin registry for extensible discovery sources
- HTTP static URL strategy implementation
- Support for MSI ProductVersion extraction

#### Version Management
- Semantic versioning comparison with prerelease support
- MSI 3-part numeric version comparison
- EXE 4-part numeric version comparison
- Lexicographic fallback for non-standard formats
- Prerelease tag ordering (alpha < beta < rc)
- Chrome-style multi-part version support

#### Download Infrastructure
- Robust HTTP downloads with retry logic and exponential backoff
- Conditional requests using ETag and Last-Modified headers
- Atomic file writes (no partial downloads)
- SHA-256 integrity verification
- Content-Disposition header support
- Redirect following
- Stable ETag support (Accept-Encoding: identity)

#### MSI Support
- Cross-platform MSI ProductVersion extraction
- Multiple backend support:
  - Windows: msilib (stdlib), _msi (CPython extension), PowerShell COM
  - Linux/macOS: msitools (msiinfo)
- Universal Windows support via PowerShell fallback

#### Testing
- Comprehensive test suite with 61 tests
- 100% pass rate
- Coverage for all major functionality
- Isolated tests with mocking (no network access)
- Tests run in < 0.2 seconds
- Shared pytest fixtures

#### Documentation
- Complete README with quick start guide
- Comprehensive DOCUMENTATION.md
- API documentation for all modules
- Module-level docstrings with examples
- Test suite documentation
- Design rationale and decision explanations
- Cross-platform compatibility notes

### Technical Details

#### Dependencies
- Python 3.11+ support
- PyYAML for configuration
- Requests for HTTP operations
- Poetry for dependency management

#### Project Structure
- Modular package organization
- Protocol-based extensibility
- Type annotations throughout
- Modern Python 3.11+ syntax
- Consistent code style (Black + Ruff)

#### Cross-Platform Support
- ✅ Windows (primary platform)
- ✅ Linux (with msitools)
- ✅ macOS (with msitools)

### Known Limitations

- Only processes first app in multi-app recipes
- PSADT packaging not yet implemented
- Intune upload not yet implemented
- Deployment wave management not yet implemented
- Only http_static discovery strategy available

### Future Plans (0.3.0+)

- Additional discovery strategies (url_regex, github_release, http_json)
- PSADT package building
- .intunewin generation
- Microsoft Intune upload
- Deployment wave/ring management
- Update policy enforcement

---

## Release Notes

This is the initial release of NAPT, providing a solid foundation for automating Windows application packaging workflows. The focus has been on building robust infrastructure for configuration management, version discovery, and file downloading.

### What Works Now

You can:
- Validate recipes with `napt check`
- Download installers automatically
- Extract versions from MSI files
- Compare versions intelligently
- Use declarative YAML recipes

### What Works Now

With 0.2.0, you can:
- Validate recipes with `napt validate`
- Discover versions automatically with `napt discover`
- Build PSADT packages with `napt build`
- Create .intunewin packages with `napt package`
- Use all four discovery strategies (http_static, github_release, http_json, url_regex)
- Apply custom branding to deployments

### What's Coming

Future releases will add direct Intune upload, deployment wave management, and advanced validation features.

[Unreleased]: https://github.com/RogerCibrian/notapkgtool/compare/0.2.0...HEAD
[0.2.0]: https://github.com/RogerCibrian/notapkgtool/compare/0.1.0...0.2.0
[0.1.0]: https://github.com/RogerCibrian/notapkgtool/releases/tag/0.1.0

