# Quick Start Guide

Get up and running with NAPT in minutes!

## Installation

### Prerequisites

- Python 3.11 or higher
- Git

### Choose Your Installation Method

#### Option 1: pip (Recommended for End Users)

Best for users who just want to use the tool without extra tooling.

```bash
# Clone repository
git clone https://github.com/RogerCibrian/notapkgtool.git
cd notapkgtool

# Create and activate virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install
pip install -e .

# Verify installation
napt --version
```

#### Option 2: Poetry (Recommended for Development)

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

### Platform-Specific Requirements

**Linux/macOS** - Install msitools for MSI version extraction:

```bash
# Debian/Ubuntu
sudo apt-get install msitools

# RHEL/Fedora
sudo dnf install msitools

# macOS
brew install msitools
```

> **💡 Note:** Windows users don't need msitools - NAPT uses native PowerShell COM API for MSI extraction.

### Platform Requirements

**Packaging requires Windows.** NAPT uses Microsoft's IntuneWinAppUtil.exe for creating .intunewin packages, which is Windows-only.

**Discovery and building work on all platforms.** Develop on your preferred OS and package on Windows when ready.

See the [Cross-Platform Support](user-guide.md#cross-platform-support) section for CI/CD workflows and detailed examples.

## Basic Usage

### Validate a Recipe

Quick validation checks syntax and configuration without downloading anything:

```bash
# Basic validation
napt validate recipes/Google/chrome.yaml

# With verbose output
napt validate recipes/Google/chrome.yaml --verbose
```

### Discover Latest Version

Download the installer and extract version information:

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

Create a complete PSADT package ready for deployment:

```bash
# Build PSADT package from recipe and downloaded installer
napt build recipes/Google/chrome.yaml

# Specify custom downloads and output directories
napt build recipes/Google/chrome.yaml --downloads-dir ./downloads --output-dir ./builds

# Show verbose output
napt build recipes/Google/chrome.yaml --verbose
```

### Create .intunewin Package

Package the PSADT build for Microsoft Intune:

```bash
# Create .intunewin from build directory
napt package builds/napt-chrome/141.0.7390.123/

# Specify output directory and clean source after packaging
napt package builds/napt-chrome/141.0.7390.123/ --output-dir ./packages --clean-source
```

> **💡 Tip:** Use `--verbose` to see progress details or `--debug` for full diagnostics including configuration dumps and backend selection

## Example Workflow

Here's a complete workflow from recipe validation to Intune package:

```bash
# 1. Validate recipe
napt validate recipes/Google/chrome.yaml
# ✓ Recipe is valid

# 2. Discover and download latest version
napt discover recipes/Google/chrome.yaml
# → downloads/googlechromestandaloneenterprise64.msi
# → state/versions.json (updated)

# 3. Build PSADT package
napt build recipes/Google/chrome.yaml
# → builds/napt-chrome/141.0.7390.123/

# 4. Create .intunewin package
napt package builds/napt-chrome/141.0.7390.123/
# → packages/napt-chrome/napt-chrome-141.0.7390.123.intunewin

# Result: Ready-to-upload .intunewin file in packages/napt-chrome/
```

## What's Next?

Now that you have NAPT installed and understand the basic commands, explore:

- **[User Guide](user-guide.md)** - Learn about discovery strategies, configuration, and advanced features
- **[API Reference](api/core.md)** - Use NAPT as a Python library
- **[Creating Recipes](user-guide.md#discovery-strategies)** - Write your own application recipes
- **[Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)** - Browse example recipes for Chrome, Git, and more

