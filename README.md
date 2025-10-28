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
- ✅ **Intelligent updates** - Version-based, hash-based, or combined strategies
- ✅ **Cross-platform support** - Windows, Linux, and macOS
- ✅ **Layered configuration** - Organization → Vendor → Recipe inheritance
- 🚧 **PSADT packaging** - Generate Intune packages (planned)
- 🚧 **Direct Intune upload** - Automatic deployment (planned)
- 🚧 **Deployment waves** - Phased rollouts with rings (planned)

## 🚀 Quick Start

### Installation

```bash
# Install dependencies
pip install pyyaml requests

# On Linux, install msitools for MSI support
sudo apt-get install msitools  # Debian/Ubuntu
```

### Validate a Recipe

```bash
# Check a recipe (downloads installer and extracts version)
napt check recipes/Google/chrome.yaml

# Specify custom output directory
napt check recipes/Google/chrome.yaml --output-dir ./cache

# Show verbose output with progress details
napt check recipes/Google/chrome.yaml --verbose

# Show debug output with full configuration dumps
napt check recipes/Google/chrome.yaml --debug
```

### Output Modes

NAPT supports three output verbosity levels:

**Normal Mode** (default):
- Clean, minimal output with step indicators
- Download progress bar
- Final results summary

**Verbose Mode** (`-v` or `--verbose`):
- Configuration loading details
- HTTP request/response information
- File operations and SHA-256 hashes
- Version extraction details

**Debug Mode** (`-d` or `--debug`):
- All verbose output
- Complete YAML configuration dumps
- Backend selection details (e.g., MSI extraction methods)
- Full troubleshooting information

### Example Output

```
Checking recipe: recipes/Google/chrome.yaml
Output directory: ./downloads

download progress: 100%
download complete: googlechromestandaloneenterprise64.msi (f8f4a...) in 1.2s
======================================================================
CHECK RESULTS
======================================================================
App Name:        Google Chrome
App ID:          napt-chrome
Strategy:        http_static
Version:         141.0.7390.123
Version Source:  msi_product_version_from_file
File Path:       ./downloads/googlechromestandaloneenterprise64.msi
SHA-256:         f8f4aedf10183d73ef7fe34488924d8e324bfb34a544bb1f2c43d2b1b0b4c797
Status:          success
======================================================================

[SUCCESS] Recipe validated successfully!
```

## 📖 Documentation

- **[DOCUMENTATION.md](DOCUMENTATION.md)** - Comprehensive project documentation
- **[defaults/org.yaml](defaults/org.yaml)** - Example organization configuration
- **[recipes/Google/chrome.yaml](recipes/Google/chrome.yaml)** - Example recipe

## 🏗️ Architecture

### Project Structure

```
notapkgtool/
├── cli.py                 # Command-line interface (argparse)
├── core.py                # High-level orchestration
├── config/
│   └── loader.py          # YAML loading and 3-layer merging
├── discovery/
│   ├── base.py            # Strategy protocol and registry
│   ├── http_static.py     # Static URL downloads
│   └── url_regex.py       # URL regex discovery strategy
├── versioning/
│   ├── keys.py            # Version comparison (semver, numeric)
│   ├── msi.py             # MSI ProductVersion extraction
│   └── url_regex.py       # URL regex extraction helper
├── io/
│   ├── download.py        # Robust HTTP downloads with retries
│   └── upload.py          # Upload adapters (planned)
└── policy/
    └── updates.py         # Update policies and waves (planned)
```

### Configuration Layers

NAPT uses a sophisticated 3-layer configuration system:

1. **Organization defaults** (`defaults/org.yaml`) - Base settings for all apps
2. **Vendor defaults** (`defaults/vendors/<Vendor>.yaml`) - Vendor-specific overrides
3. **Recipe configuration** (`recipes/<Vendor>/<app>.yaml`) - App-specific settings

Configurations are deep-merged with "last wins" semantics.

### Discovery Strategies

Pluggable strategies for obtaining application installers:

- **`http_static`** ✅ - Download from fixed URLs, extract version from file
- **`url_regex`** ✅ - Extract version from URL patterns before download
- **`github_release`** ✅ - Fetch from GitHub releases API with asset matching
- **`http_json`** ✅ - Query JSON API endpoints with JSONPath navigation

> **📚 For detailed comparison, configuration reference, and decision guide, see the [Discovery Strategies](DOCUMENTATION.md#discovery-strategies) section in DOCUMENTATION.md**

## 💻 Programmatic API

```python
from pathlib import Path
from notapkgtool.core import check_recipe
from notapkgtool.config import load_effective_config
from notapkgtool.versioning import compare_any, is_newer_any

# Validate a recipe (with verbose output)
result = check_recipe(
    recipe_path=Path("recipes/Google/chrome.yaml"),
    output_dir=Path("./downloads"),
    verbose=True
)
print(f"Version: {result['version']}")

# Validate with debug output
result = check_recipe(
    recipe_path=Path("recipes/Google/chrome.yaml"),
    output_dir=Path("./downloads"),
    debug=True
)

# Load configuration
config = load_effective_config(Path("recipes/Google/chrome.yaml"))

# Compare versions
if is_newer_any("1.2.0", "1.1.9"):
    print("Update available!")
```

## 🌍 Cross-Platform Support

| Platform | Download | Config | CLI | MSI Extraction | Status |
|----------|----------|--------|-----|----------------|--------|
| **Windows** | ✅ | ✅ | ✅ | ✅ Native (PowerShell COM) | Fully Supported |
| **Linux** | ✅ | ✅ | ✅ | ✅ Via msitools | Fully Supported |
| **macOS** | ✅ | ✅ | ✅ | ✅ Via msitools | Fully Supported |

### MSI Extraction Backends

**Windows** (tried in order):
1. `msilib` (Python standard library)
2. `_msi` (CPython extension)
3. **PowerShell COM** (always available, universal fallback)

**Linux/macOS**:
1. `msiinfo` from msitools package

## 🔧 Development

### Requirements

- Python 3.11+
- `pyyaml` >= 6.0.2
- `requests` >= 2.32

### Code Quality

```bash
# Format code
black notapkgtool/

# Lint code
ruff check notapkgtool/

# Run tests
pytest tests/
```

## 📝 Creating Recipes

Create a recipe YAML file in `recipes/<Vendor>/<app>.yaml`:

### HTTP Static Strategy

```yaml
apiVersion: napt/v1

apps:
  - name: "Google Chrome"
    id: "napt-chrome"
    
    source:
      strategy: http_static
      url: "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"
      version:
        type: msi_product_version_from_file
    
    psadt:
      app_vars:
        AppName: "Google Chrome"
        AppVersion: "${discovered_version}"
        AppArch: "x64"
      install: |
        Start-ADTMsiProcess `
          -Path "$dirFiles\googlechromestandaloneenterprise64.msi" `
          -Parameters "ALLUSERS=1" `
          -MsiParameters "/qn /norestart"
      uninstall: |
        $app = Get-InstalledApplication -Name "Google Chrome" -Exact
        if ($app -and $app.ProductCode) {
          Start-ADTMsiProcess -ProductCode $app.ProductCode `
            -MsiParameters "/qn /norestart" -Action Uninstall
        }
```

### GitHub Release Strategy

```yaml
apiVersion: napt/v1

apps:
  - name: "Git for Windows"
    id: "napt-git"
    
    source:
      strategy: github_release
      repo: "git-for-windows/git"
      asset_pattern: "Git-.*-64-bit\\.exe$"
      version_pattern: "v?([0-9.]+)\\.windows"
    
    psadt:
      app_vars:
        AppName: "Git for Windows"
        AppVersion: "${discovered_version}"
        AppArch: "x64"
      install: |
        Execute-Process `
          -Path "$dirFiles\Git-${discovered_version}-64-bit.exe" `
          -Parameters "/VERYSILENT /NORESTART" `
          -WindowStyle Hidden
```

## 🗺️ Roadmap

### v0.1.0 (Current)
- ✅ CLI with `check` command
- ✅ Verbose and debug output modes
- ✅ Configuration system with 3-layer merging
- ✅ HTTP static discovery strategy
- ✅ URL regex discovery strategy
- ✅ GitHub release discovery strategy
- ✅ MSI ProductVersion extraction
- ✅ Version comparison utilities
- ✅ Cross-platform support

### v0.2.0 (Planned)
- 🚧 PSADT package building
- 🚧 .intunewin generation

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

See [DOCUMENTATION.md](DOCUMENTATION.md) for detailed guidelines.

## 📄 License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## 👤 Author

**Roger Cibrian**

## 🙏 Acknowledgments

- Built for automating Windows application deployment
- Uses PSAppDeployToolkit (PSADT) for packaging
- Targets Microsoft Intune for distribution

---

*For detailed documentation, see [DOCUMENTATION.md](DOCUMENTATION.md)*
