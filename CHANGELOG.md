# Changelog

All notable changes to NAPT (Not a Pkg Tool) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Future Plans (v0.2.0+)

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

### What's Coming

Future releases will add PSADT package generation and direct Intune deployment capabilities.

[0.1.0]: https://github.com/RogerCibrian/notapkgtool/releases/tag/v0.1.0

