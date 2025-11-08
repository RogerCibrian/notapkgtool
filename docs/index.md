# NAPT - Not a Pkg Tool

> **Automated Windows application packaging and deployment to Microsoft Intune using PSAppDeployToolkit**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Overview

NAPT is a Python-based CLI tool that automates the entire workflow for packaging Windows applications and deploying them to Microsoft Intune. It eliminates repetitive manual work through declarative YAML-based recipes and intelligent version discovery.

### Key Features

- ✅ **Declarative YAML recipes** - Define app packaging once, run everywhere
- ✅ **Automatic version discovery** - Extract versions from MSI, EXE, URLs, or APIs
- ✅ **Robust downloads** - Retry logic, conditional requests (ETags), atomic writes
- ✅ **Intelligent caching** - Version-first strategies can skip downloads entirely when unchanged
- ✅ **Dual-path optimization** - Version-first (instant checks) and file-first (ETag) strategies
- ✅ **Cross-platform support** - Windows, Linux, and macOS
- ✅ **Layered configuration** - Organization → Vendor → Recipe inheritance
- ✅ **PSADT packaging** - Generate Intune-ready packages with PSAppDeployToolkit
- 🚧 **Direct Intune upload** - Automatic deployment (planned)
- 🚧 **Deployment waves** - Phased rollouts with rings (planned)

## Quick Example

```bash
# Validate a recipe
napt validate recipes/Google/chrome.yaml

# Discover version and download installer
napt discover recipes/Google/chrome.yaml

# Build PSADT package
napt build recipes/Google/chrome.yaml

# Create .intunewin package
napt package builds/napt-chrome/141.0.7390.123/
```

> **💡 Tip:** Add `--verbose` or `--debug` flags to any command for detailed output

## Getting Started

Ready to get started? Check out the [Quick Start Guide](quick-start.md) for installation instructions and your first steps with NAPT.

## Architecture

NAPT uses a modular architecture with key design patterns:

- **3-Layer Configuration** - Organization → Vendor → Recipe inheritance with deep merging
- **Strategy Pattern** - Pluggable discovery strategies with version-first and file-first approaches
- **Version-First Optimization** - Skip downloads entirely when versions unchanged (url_regex, github_release, http_json)
- **File-First Fallback** - ETag-based conditional requests when version must be extracted from file (http_static)
- **Cross-Platform** - Native Windows support, Linux/macOS via msitools

See the [User Guide](user-guide.md) for detailed architecture information and the [API Reference](api/core.md) for code-level documentation.

## Cross-Platform Support

| Platform | Download | Config | CLI | MSI Extraction | Status |
|----------|----------|--------|-----|----------------|--------|
| **Windows** | ✅ | ✅ | ✅ | ✅ Native (PowerShell COM) | Fully Supported |
| **Linux** | ✅ | ✅ | ✅ | ✅ Via msitools | Fully Supported |
| **macOS** | ✅ | ✅ | ✅ | ✅ Via msitools | Fully Supported |

## Creating Recipes

Recipes are declarative YAML files that define how to discover, download, and package applications.

**Example recipes:**

- **[chrome.yaml](https://github.com/RogerCibrian/notapkgtool/blob/main/recipes/Google/chrome.yaml)** - HTTP static strategy with MSI version extraction
- **[git.yaml](https://github.com/RogerCibrian/notapkgtool/blob/main/recipes/Git/git.yaml)** - GitHub release strategy with asset pattern matching
- **[json-api-example.yaml](https://github.com/RogerCibrian/notapkgtool/blob/main/recipes/Examples/json-api-example.yaml)** - HTTP JSON API strategy

**Supported discovery strategies:**

- `http_static` - Fixed URLs, version from file
- `url_regex` - Extract version from URL patterns
- `github_release` - GitHub releases API
- `http_json` - JSON API endpoints with JSONPath

See the [User Guide](user-guide.md#discovery-strategies) for detailed configuration reference and examples.

## Contributing

Contributions are welcome! Please ensure:

1. Code follows existing patterns and conventions
2. All functions have comprehensive docstrings
3. Type annotations are included
4. Tests are added for new features
5. Documentation is updated

See [Contributing](contributing.md) for detailed guidelines.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](https://github.com/RogerCibrian/notapkgtool/blob/main/LICENSE) file for details.

## Author

**Roger Cibrian**

## Acknowledgments

- Built for automating Windows application deployment
- Uses PSAppDeployToolkit (PSADT) for packaging
- Targets Microsoft Intune for distribution

