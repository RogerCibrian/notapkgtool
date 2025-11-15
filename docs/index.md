# NAPT - Not a Pkg Tool

> **Automated Windows application packaging and deployment to Microsoft Intune using PSAppDeployToolkit**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Overview

NAPT is a Python-based CLI tool that automates the entire workflow for packaging Windows applications and deploying them to Microsoft Intune. It runs on Windows, Linux, and macOS, though packaging (.intunewin creation) requires Windows.

### Why NAPT?

Packaging applications for Microsoft Intune with PSAppDeployToolkit (PSADT) typically involves a manual, time-consuming process:

1. **Manually check for new versions** - Check vendor sites/APIs for updates. Easy to miss versions or waste time when nothing changed.

2. **Create PSADT deployment** - Copy template, manually edit `Invoke-AppDeployToolkit.ps1` with variables, configure install/uninstall logic. Error-prone and repetitive.

3. **Create detection script** - Write PowerShell detection logic, test thoroughly, maintain version checks. Must update for each new version.

4. **Package as .intunewin** - Run IntuneWinAppUtil.exe manually, manage paths, handle errors. Tedious and error-prone.

5. **Upload to Intune** - Upload package via portal, fill metadata, configure app info and requirements manually.

6. **Configure deployment** - Set up rollout assignments manually for each version.

This manual workflow is repetitive, difficult to automate in CI/CD pipelines, lacks version tracking, and requires re-doing most of the work for every update. NAPT automates this entire workflow with YAML-based recipes and intelligent version tracking.

### Key Features

- ✅ **Intelligent version tracking** - Automatic discovery from MSI, EXE, URLs, or APIs with smart caching to skip unnecessary downloads
- ✅ **YAML-based recipes** - Define app packaging once with layered configuration (Organization → Vendor → Recipe)
- ✅ **Automated PSADT packaging** - Generate Intune-ready packages with detection scripts, no manual template editing
- ✅ **Cross-platform workflow** - Run on Windows, Linux, and macOS (packaging requires Windows)
- 🚧 **Direct Intune upload** - Automatic deployment (planned)

## Getting Started

```bash
# Validate a recipe
napt validate recipes/Google/chrome.yaml

# Discover version and download installer
napt discover recipes/Google/chrome.yaml

# Build PSADT package
napt build recipes/Google/chrome.yaml

# Create .intunewin package
napt package builds/napt-chrome/141.0.7444.60/
```

> **💡 Tip:** Add `--verbose` for progress updates or `--debug` for detailed diagnostics. See [Commands Reference](user-guide.md#commands-reference) for details.

Check out the [Quick Start Guide](quick-start.md) for installation instructions and your first steps with NAPT.

## Cross-Platform Support

| Command | Windows | Linux/macOS |
|---------|---------|-------------|
| `napt discover` | ✅ | ✅ |
| `napt build` | ✅ | ✅ |
| `napt package` | ✅ | ⚫ Windows Only |

See the [Cross-Platform Support](user-guide.md#cross-platform-support) section for detailed workflows.

## Creating Recipes

Recipes are YAML configuration files that define how to discover, download, and package applications.

**Example recipes:**

- **[chrome.yaml](https://github.com/RogerCibrian/notapkgtool/blob/main/recipes/Google/chrome.yaml)** - url_download strategy with MSI version extraction
- **[7zip.yaml](https://github.com/RogerCibrian/notapkgtool/blob/main/recipes/7-Zip/7zip.yaml)** - web_scrape strategy for vendor download pages

NAPT supports multiple discovery strategies (url_download, web_scrape, api_github, api_json) - see the [Discovery Strategies](user-guide.md#discovery-strategies) guide for detailed configuration and more examples.

## Contributing

Contributions are welcome! See [Contributing](contributing.md) for guidelines.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](https://github.com/RogerCibrian/notapkgtool/blob/main/LICENSE) file for details.

## Author

**Roger Cibrian**

## Acknowledgments

- Built for automating Windows application deployment
- Uses PSAppDeployToolkit (PSADT) for packaging
- Targets Microsoft Intune for distribution

