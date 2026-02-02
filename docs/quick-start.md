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

Best for development and contributing to NAPT.

**Prerequisites:** Poetry must be installed. See [Poetry Installation Guide](https://python-poetry.org/docs/#installation)

```powershell
# Clone repository
git clone https://github.com/RogerCibrian/notapkgtool.git
cd notapkgtool

# Install (Poetry creates .venv automatically)
poetry install

# Activate virtual environment
.venv\Scripts\Activate.ps1  # On Linux/macOS: source .venv/bin/activate

# Verify installation
napt --version
```

### Platform Requirements

NAPT runs on Windows, Linux, and macOS with the following requirements:

#### Windows

- No additional dependencies required
- All features supported (discovery, building, packaging)
- Uses native PowerShell COM API for MSI extraction

#### Linux/macOS

- **Required:** msitools for MSI version extraction
- **Limitation:** Cannot create .intunewin packages (requires Windows)
- Supports discovery and building features

Install msitools:

```bash
# Debian/Ubuntu
sudo apt-get install msitools

# RHEL/Fedora
sudo dnf install msitools

# macOS
brew install msitools
```

See the [Cross-Platform Support](user-guide.md#cross-platform-support) section for platform-specific workflows.

## Basic Usage

### Command-Line Options

All NAPT commands support these helpful flags:

- `--help` or `-h` - Show detailed help and examples for any command
- `--verbose` - Show progress details and additional information
- `--debug` - Show full diagnostics including configuration dumps

Example: `napt discover --help` or `napt build --verbose`

### Validate a Recipe

Quick validation checks syntax and configuration without downloading anything:

```bash
napt validate recipes/Google/chrome.yaml
```

### Discover Latest Version

Download the installer and extract version information:

```bash
# Discover version and download installer
# State tracking enabled by default for efficient re-runs
napt discover recipes/Google/chrome.yaml

# Specify custom output directory
napt discover recipes/Google/chrome.yaml --output-dir ./cache

# Disable state tracking (always download, no caching)
napt discover recipes/Google/chrome.yaml --stateless
```

### Build PSADT Package

Create a complete PSADT package ready for deployment:

```bash
# Build PSADT package from recipe and downloaded installer
napt build recipes/Google/chrome.yaml

# Specify custom downloads and output directories
napt build recipes/Google/chrome.yaml --downloads-dir ./downloads --output-dir ./builds
```

### Create .intunewin Package

Package the PSADT build for Microsoft Intune:

```bash
# Create .intunewin from build directory
napt package builds/napt-chrome/144.0.7559.110/packagefiles/

# Specify output directory and clean source after packaging
napt package builds/napt-chrome/144.0.7559.110/packagefiles/ --output-dir ./packages --clean-source
```

## Example Workflows

### Complete Workflow: Recipe to Package

Here's a complete workflow from recipe validation to Intune package:

#### 1. Validate recipe

```console
$ napt validate recipes/Google/chrome.yaml
Validating recipe: /path/to/recipes/Google/chrome.yaml

======================================================================
VALIDATION RESULTS
======================================================================
Recipe:      /path/to/recipes/Google/chrome.yaml
Status:      VALID
App Count:   1

======================================================================

[SUCCESS] Recipe is valid!
```

#### 2. Discover and download latest version

```console
$ napt discover recipes/Google/chrome.yaml
Discovering version for recipe: /path/to/recipes/Google/chrome.yaml
Output directory: /path/to/downloads

[1/4] Loading configuration...
[2/4] Discovering version...
[3/4] Discovering version...
[4/4] Downloading installer...
download progress: 0%
...
download progress: 100%
[1/1] Download complete: /path/to/downloads/googlechromestandaloneenterprise64.msi (abc123...) in 25.5s
======================================================================
DISCOVERY RESULTS
======================================================================
App Name:        Google Chrome
App ID:          napt-chrome
Strategy:        url_download
Version:         144.0.7559.110
Version Source:  msi
File Path:       /path/to/downloads/googlechromestandaloneenterprise64.msi
SHA-256:         abc123...
Status:          success
======================================================================

[SUCCESS] Version discovered successfully!
```

#### 3. Build PSADT package

```console
$ napt build recipes/Google/chrome.yaml
Building PSADT package for recipe: /path/to/recipes/Google/chrome.yaml
Downloads directory: /path/to/downloads

[1/8] Loading configuration...
[2/8] Finding installer...
[3/8] Determining version...
[4/8] Getting PSADT release...
[5/8] Creating build structure...
[6/8] Applying branding...
[7/8] Generating detection script...
[8/8] Generating requirements script...
======================================================================
BUILD RESULTS
======================================================================
App Name:        Google Chrome
App ID:          napt-chrome
Version:         144.0.7559.110
PSADT Version:   4.1.8
Build Directory: builds/napt-chrome/144.0.7559.110/packagefiles
Status:          success
======================================================================

[SUCCESS] PSADT package built successfully!
```

#### 4. Create .intunewin package

```console
$ napt package builds/napt-chrome/144.0.7559.110/packagefiles/
Creating .intunewin package from: /path/to/builds/napt-chrome/144.0.7559.110/packagefiles

[1/4] Verifying build structure...
[2/4] Getting IntuneWinAppUtil tool...
[3/4] Creating .intunewin package...
[4/4] Cleaning up...
======================================================================
PACKAGE RESULTS
======================================================================
App ID:          napt-chrome
Version:         144.0.7559.110
Package Path:    /path/to/packages/napt-chrome/Invoke-AppDeployToolkit.intunewin
Build Directory: /path/to/builds/napt-chrome/144.0.7559.110/packagefiles
Status:          success
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
[2/4] Version unchanged (144.0.7559.110)
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
napt package builds/napt-chrome/144.0.7559.110/packagefiles/ --clean-source
```

## Common Tasks

For step-by-step guides on common workflows, see [Common Tasks](common-tasks.md):

- Create a recipe for a GitHub release app
- Create a recipe for a vendor download page
- Create a recipe for a JSON API endpoint
- Troubleshoot discovery failures

## What's Next?

Now that you have NAPT installed and understand the basic commands, explore:

- **[Common Tasks](common-tasks.md)** - Step-by-step guides for common workflows
- **[User Guide](user-guide.md)** - Learn about discovery strategies, configuration, and advanced features
- **[Creating Recipes](user-guide.md#discovery-strategies)** - Write your own application recipes
- **[Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)** - Browse example recipes for Chrome, Git, and more

