# NAPT - Not a Pkg Tool

> **Automated Windows application packaging and deployment to Microsoft Intune using PSAppDeployToolkit**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## 📋 Overview

NAPT is a Python-based CLI tool that automates the entire workflow for packaging Windows applications and deploying them to Microsoft Intune. It eliminates repetitive manual work through declarative YAML-based recipes and intelligent version discovery.

### Key Features

- ✅ **Declarative YAML recipes** - Define app packaging once, run everywhere
- ✅ **Automatic version discovery** - Extract versions from MSI, EXE, URLs, or APIs
- ✅ **Robust downloads** - Retry logic, conditional requests (ETags), atomic writes
- ✅ **Intelligent caching** - State tracking with ETag-based conditional downloads
- ✅ **Intelligent updates** - Version-based, hash-based, or combined strategies
- ✅ **Cross-platform support** - Windows, Linux, and macOS
- ✅ **Layered configuration** - Organization → Vendor → Recipe inheritance
- ✅ **PSADT packaging** - Generate Intune-ready packages with PSAppDeployToolkit
- 🚧 **Direct Intune upload** - Automatic deployment (planned)
- 🚧 **Deployment waves** - Phased rollouts with rings (planned)

## 🚀 Quick Start

### Installation

**Prerequisites:**
- Python 3.11 or higher
- Git

**Choose your installation method:**

#### Option 1: Poetry (Recommended for Development)

Best for contributors and developers who want reproducible builds and dependency management.

**Prerequisites:** Poetry must be installed. See [Poetry Installation Guide](https://python-poetry.org/docs/#installation)

```bash
# Clone and install
git clone https://github.com/RogerCibrian/notapkgtool.git
cd notapkgtool
poetry install

# Activate virtual environment
poetry shell

# Verify installation
napt --version
```

#### Option 2: pip (Recommended for End Users)

Best for users who just want to use the tool without extra tooling.

```bash
# Clone and install
git clone https://github.com/RogerCibrian/notapkgtool.git
cd notapkgtool
pip install -e .

# Verify installation
napt --version
```


#### Platform-Specific Requirements

On **Linux/macOS**, install msitools for MSI version extraction:
```bash
# Debian/Ubuntu
sudo apt-get install msitools

# RHEL/Fedora
sudo dnf install msitools

# macOS
brew install msitools
```

On **Windows**, no additional dependencies are required (uses PowerShell COM API for MSI extraction).

### Validate a Recipe

```bash
# Quick validation (syntax check only, no downloads)
napt validate recipes/Google/chrome.yaml

# With verbose output
napt validate recipes/Google/chrome.yaml --verbose
```

### Discover Latest Version

```bash
# Discover version and download installer
# State tracking enabled by default for efficient re-runs
napt discover recipes/Google/chrome.yaml

# Specify custom output directory
napt discover recipes/Google/chrome.yaml --output-dir ./cache

# Show verbose output with progress details
napt discover recipes/Google/chrome.yaml --verbose

# Disable state tracking (always download, no caching)
napt discover recipes/Google/chrome.yaml --stateless

# Show debug output with full configuration dumps
napt discover recipes/Google/chrome.yaml --debug
```

### Build PSADT Package

```bash
# Build PSADT package from recipe and downloaded installer
napt build recipes/Google/chrome.yaml

# Specify custom downloads and output directories
napt build recipes/Google/chrome.yaml --downloads-dir ./downloads --output-dir ./builds

# Show verbose output
napt build recipes/Google/chrome.yaml --verbose
```

### Create .intunewin Package

```bash
# Create .intunewin from build directory
napt package builds/napt-chrome/141.0.7390.123/

# Specify output directory and clean source after packaging
napt package builds/napt-chrome/141.0.7390.123/ --output-dir ./packages --clean-source
```

> **💡 Tip:** Add `--verbose` or `--debug` flags to any command for detailed output

## 📖 Documentation

- **[Documentation Site](https://rogercibrian.github.io/notapkgtool)** - Complete user guide and API reference
- **[Quick Start Guide](https://rogercibrian.github.io/notapkgtool/quick-start/)** - Installation and basic usage
- **[API Reference](https://rogercibrian.github.io/notapkgtool/api/core/)** - Auto-generated from code
- **[defaults/org.yaml](defaults/org.yaml)** - Example organization configuration
- **[recipes/Google/chrome.yaml](recipes/Google/chrome.yaml)** - Example recipe

## 🏗️ Architecture

NAPT uses a modular architecture with key design patterns:

- **3-Layer Configuration** - Organization → Vendor → Recipe inheritance with deep merging
- **Strategy Pattern** - Pluggable discovery strategies (http_static, url_regex, github_release, http_json)
- **State Tracking** - ETag-based caching for efficient conditional downloads
- **Cross-Platform** - Native Windows support, Linux/macOS via msitools

> **📚 See the [Documentation Site](https://rogercibrian.github.io/notapkgtool) for detailed architecture, API reference, and configuration guides**

## 💻 Programmatic API

NAPT can be used as a Python library. See the [Programmatic API](https://rogercibrian.github.io/notapkgtool/user-guide/#programmatic-api) section for code examples and detailed usage.

## 🌍 Cross-Platform Support

| Platform | Download | Config | CLI | MSI Extraction | Status |
|----------|----------|--------|-----|----------------|--------|
| **Windows** | ✅ | ✅ | ✅ | ✅ Native (PowerShell COM) | Fully Supported |
| **Linux** | ✅ | ✅ | ✅ | ✅ Via msitools | Fully Supported |
| **macOS** | ✅ | ✅ | ✅ | ✅ Via msitools | Fully Supported |

## 🔧 Development

```bash
# Clone and install with dev dependencies
git clone https://github.com/RogerCibrian/notapkgtool.git
cd notapkgtool
poetry install

# Run code quality checks
poetry run black notapkgtool/
poetry run ruff check --fix notapkgtool/
poetry run pytest tests/
```

**Tip:** Use `poetry shell` to activate the environment, or prefix commands with `poetry run`

## 📝 Creating Recipes

Recipes are declarative YAML files that define how to discover, download, and package applications.

**Example recipes:**
- **[chrome.yaml](recipes/Google/chrome.yaml)** - HTTP static strategy with MSI version extraction
- **[git.yaml](recipes/Git/git.yaml)** - GitHub release strategy with asset pattern matching
- **[json-api-example.yaml](recipes/Examples/json-api-example.yaml)** - HTTP JSON API strategy

**Supported discovery strategies:**
- `http_static` - Fixed URLs, version from file
- `url_regex` - Extract version from URL patterns
- `github_release` - GitHub releases API
- `http_json` - JSON API endpoints with JSONPath

> **📚 See [Discovery Strategies](https://rogercibrian.github.io/notapkgtool/user-guide/#discovery-strategies) for detailed configuration reference and examples**

## 🗺️ Roadmap

### 0.1.0
- ✅ CLI with `validate` and `discover` commands
- ✅ Recipe validation (syntax and configuration checks)
- ✅ Verbose and debug output modes
- ✅ Configuration system with 3-layer merging
- ✅ HTTP static discovery strategy
- ✅ URL regex discovery strategy
- ✅ GitHub release discovery strategy
- ✅ HTTP JSON discovery strategy
- ✅ MSI ProductVersion extraction
- ✅ Version comparison utilities
- ✅ State tracking with ETag caching
- ✅ Cross-platform support

### 0.2.0 (Current Release)
- ✅ PSADT package building with `build` command
- ✅ .intunewin generation with `package` command
- ✅ PSADT release management from GitHub
- ✅ Invoke-AppDeployToolkit.ps1 generation from templates
- ✅ Custom branding support
- ✅ Filesystem-first version tracking (state schema v2)

### v0.3.0 (Planned)
- 🚧 Microsoft Intune upload
- 🚧 Deployment wave management
- 🚧 Update policy enforcement

## 🤝 Contributing

Contributions are welcome! Please ensure:

1. Code follows existing patterns and conventions
2. All functions have comprehensive docstrings
3. Type annotations are included
4. Tests are added for new features
5. Documentation is updated

See the [Documentation Site](https://rogercibrian.github.io/notapkgtool) for detailed guidelines.

## 📄 License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## 👤 Author

**Roger Cibrian**

## 🙏 Acknowledgments

- Built for automating Windows application deployment
- Uses PSAppDeployToolkit (PSADT) for packaging
- Targets Microsoft Intune for distribution

---

*For detailed documentation, visit the [Documentation Site](https://rogercibrian.github.io/notapkgtool)*
