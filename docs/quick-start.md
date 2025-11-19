# Quick Start Guide

## Installation

### Prerequisites

- Python 3.11 or higher
- Git

### Choose Your Installation Method

#### Option 1: pip (For Using NAPT)

Best for users who just want to use the tool without extra tooling.

```powershell
# Clone repository
git clone https://github.com/RogerCibrian/notapkgtool.git
cd notapkgtool

# Create and activate virtual environment (recommended)
python -m venv .venv
.venv\Scripts\Activate.ps1  # On Linux/macOS: source .venv/bin/activate

# Install
pip install -e .

# Verify installation
napt --version
```

#### Option 2: Poetry (For Development)

Best for developers who want reproducible builds and dependency management.

**Prerequisites:** Poetry must be installed. See [Poetry Installation Guide](https://python-poetry.org/docs/#installation)

```powershell
# Clone repository
git clone https://github.com/RogerCibrian/notapkgtool.git
cd notapkgtool

# Install (Poetry creates .venv automatically)
poetry install

# Activate virtual environment
poetry shell

# Verify installation
napt --version
```

### Platform Requirements

**Discovery and building:** Work on Windows, Linux, and macOS.

**Packaging (.intunewin creation):** Requires Windows (uses IntuneWinAppUtil.exe).

**Linux/macOS:** Install msitools for MSI version extraction:

```bash
# Debian/Ubuntu
sudo apt-get install msitools

# RHEL/Fedora
sudo dnf install msitools

# macOS
brew install msitools
```

**Windows:** No additional requirements (uses native PowerShell COM API).

See the [Cross-Platform Support](user-guide.md#cross-platform-support) section for CI/CD workflows and detailed examples.

## Basic Usage

> **💡 Tip:** Use `napt <command> --help` (or `-h`) to see detailed help and examples for any command. For example: `napt discover --help`

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

## Example Workflows

### Complete Workflow: Recipe to Package

Here's a complete workflow from recipe validation to Intune package:

```bash
# 1. Validate recipe
napt validate recipes/Google/chrome.yaml
```

**Expected output:**
```
Validating recipe: recipes/Google/chrome.yaml

======================================================================
VALIDATION RESULTS
======================================================================
Recipe:      recipes/Google/chrome.yaml
Status:      VALID
App Count:   1

======================================================================

[SUCCESS] Recipe is valid!
```

```bash
# 2. Discover and download latest version
napt discover recipes/Google/chrome.yaml
```

**Expected output:**
```
Discovering version for recipe: recipes/Google/chrome.yaml
Output directory: downloads

======================================================================
DISCOVERY RESULTS
======================================================================
App Name:        Google Chrome
App ID:          napt-chrome
Strategy:        url_download
Version:         142.0.7444.163
Version Source:  msi
File Path:       downloads/googlechromestandaloneenterprise64.msi
SHA-256:         abc123...
Status:          downloaded

======================================================================

[SUCCESS] Version discovered successfully!
```

```bash
# 3. Build PSADT package
napt build recipes/Google/chrome.yaml
```

**Expected output:**
```
Building PSADT package for recipe: recipes/Google/chrome.yaml
Downloads directory: downloads

======================================================================
BUILD RESULTS
======================================================================
App Name:        Google Chrome
App ID:          napt-chrome
Version:         142.0.7444.163
PSADT Version:   4.1.7
Build Directory: builds/napt-chrome/142.0.7444.163
Status:          built

======================================================================

[SUCCESS] PSADT package built successfully!
```

```bash
# 4. Create .intunewin package
napt package builds/napt-chrome/142.0.7444.163/
```

**Expected output:**
```
Creating .intunewin package from: builds/napt-chrome/142.0.7444.163

======================================================================
PACKAGE RESULTS
======================================================================
App ID:          napt-chrome
Version:         142.0.7444.163
Package Path:    packages/napt-chrome/Invoke-AppDeployToolkit.intunewin
Build Directory: builds/napt-chrome/142.0.7444.163
Status:          packaged

======================================================================

[SUCCESS] .intunewin package created successfully!
```

**Result:** Ready-to-upload .intunewin file in `packages/napt-chrome/`

### Quick Check Workflow

Check if a new version is available (skips re-downloading if unchanged):

```bash
# Discover with verbose output to see what happens
napt discover recipes/Google/chrome.yaml --verbose
```

If the version hasn't changed since the last run and the file exists, you'll see:
```
[1/4] Checking cached version...
[2/4] Version unchanged (142.0.7444.163)
[3/4] File exists, skipping download
[4/4] Using cached file: downloads/googlechromestandaloneenterprise64.msi
```

**Note:** This requires having run `napt discover` at least once before to create the cached version.

### Clean Build Workflow

Force a fresh download and rebuild:

```bash
# Always download (ignore cache)
napt discover recipes/Google/chrome.yaml --stateless

# Build with custom output
napt build recipes/Google/chrome.yaml --output-dir ./my-builds

# Package and clean up source
napt package builds/napt-chrome/142.0.7444.163/ --clean-source
```

## Common Tasks

For step-by-step guides on common workflows, see [Common Tasks](common-tasks.md):

- Create a recipe for a GitHub release app
- Create a recipe for a vendor download page
- Create a recipe for a JSON API endpoint
- Set up CI/CD with NAPT
- Troubleshoot discovery failures

## What's Next?

Now that you have NAPT installed and understand the basic commands, explore:

- **[Common Tasks](common-tasks.md)** - Step-by-step guides for common workflows
- **[User Guide](user-guide.md)** - Learn about discovery strategies, configuration, and advanced features
- **[Creating Recipes](user-guide.md#discovery-strategies)** - Write your own application recipes
- **[Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)** - Browse example recipes for Chrome, Git, and more

