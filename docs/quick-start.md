# Quick start guide

## Installation

### Prerequisites

- Python 3.11 or higher
- Git

### Choose your installation method

#### Option 1: pip (for using NAPT)

```powershell
# Create a project directory
mkdir napt-workspace
cd napt-workspace

# Create and activate virtual environment (recommended)
python -m venv .venv
.venv\Scripts\Activate.ps1  # On Linux/macOS: source .venv/bin/activate

# Install from PyPI
pip install napt

# Verify installation
napt --version
```

#### Option 2: Poetry (for development)

> **Note:** Clones the main branch, so you're working with the latest code.

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

### Platform requirements

Windows needs nothing extra. Linux and macOS need `msitools` for MSI version
extraction and cannot create .intunewin packages (that step requires Windows):

```bash
# Debian/Ubuntu
sudo apt-get install msitools

# RHEL/Fedora
sudo dnf install msitools

# macOS
brew install msitools
```

See [Cross-platform support](user-guide.md#cross-platform-support) for the
mixed-platform workflow.

## Basic usage

### Command-line options

All commands support:

- `--help` or `-h` - Show detailed help and examples for any command
- `--verbose` - Show progress details and additional information
- `--debug` - Show full diagnostics including configuration dumps

Example: `napt discover --help` or `napt build --verbose`

### Initialize a new project

Set up the recommended directory structure for a new NAPT project:

```bash
# Initialize in current directory
napt init

# Initialize in a specific directory
napt init /path/to/project

# Overwrite existing files (backs up originals)
napt init --force
```

This creates:

- `recipes/` - Directory for your recipe files
- `defaults/org.yaml` - Organization-wide configuration (commented template)
- `defaults/vendors/` - Directory for vendor-specific defaults
- `state/deployment/` - Per-app deployment state files

### Validate a recipe

Quick validation checks syntax and configuration without downloading anything:

```bash
napt validate recipes/Google/chrome.yaml
```

### Discover latest version

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

Re-running `napt discover` skips the download when nothing changed; the fetch
step reports `[CACHE] File not modified` instead.

### Build PSADT package

Create a complete PSADT package ready for deployment:

```bash
# Build PSADT package from recipe and downloaded installer
napt build recipes/Google/chrome.yaml

# Specify custom downloads and output directories
napt build recipes/Google/chrome.yaml --downloads-dir ./downloads --output-dir ./builds
```

### Create .intunewin package

Package the PSADT build for Microsoft Intune:

```bash
# Create .intunewin from recipe (infers most recent build automatically)
napt package recipes/Google/chrome.yaml

# Specify output directory and clean source after packaging
napt package recipes/Google/chrome.yaml --output-dir ./packages --clean-source
```

## Complete workflow: recipe to package

### 1. Validate recipe

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

### 2. Discover and download latest version

```console
$ napt discover recipes/Google/chrome.yaml
Discovering version for recipe: /path/to/recipes/Google/chrome.yaml

[1/4] Loading configuration...
[2/4] Discovering version...
[3/4] Fetching installer...
[DOWNLOAD] 100%
[4/4] Updating state...
======================================================================
DISCOVERY RESULTS
======================================================================
App Name:        Google Chrome
App ID:          napt-chrome
Strategy:        url_download
Version:         <version>
Version Source:  msi
File Path:       /path/to/downloads/napt-chrome/<version>/googlechromestandaloneenterprise64.msi
SHA-256:         <sha256>
Status:          success
======================================================================

[SUCCESS] Version discovered successfully!
```

### 3. Build PSADT package

```console
$ napt build recipes/Google/chrome.yaml
Building PSADT package for recipe: /path/to/recipes/Google/chrome.yaml

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
Version:         <version>
PSADT Version:   <psadt version>
Build Directory: /path/to/builds/napt-chrome/<version>/packagefiles
Status:          success
======================================================================

[SUCCESS] PSADT package built successfully!
```

### 4. Create .intunewin package

```console
$ napt package recipes/Google/chrome.yaml
Creating .intunewin package from: /path/to/builds/napt-chrome/<version>
Output directory: /path/to/packages

[1/5] Verifying build structure...
[2/5] Getting IntuneWinAppUtil tool...
[3/5] Creating .intunewin package...
[4/5] Copying detection scripts...
[5/5] Package complete
======================================================================
PACKAGE RESULTS
======================================================================
App ID:          napt-chrome
Version:         <version>
Package Path:    /path/to/packages/napt-chrome/<version>/Invoke-AppDeployToolkit.intunewin
Build Directory: /path/to/builds/napt-chrome/<version>
Status:          success
======================================================================

[SUCCESS] .intunewin package created successfully!
```

**Result:** Ready-to-upload .intunewin file in `packages/napt-chrome/<version>/`

## What's next?

- **[Deploy to Intune](common-tasks.md#deploy-to-intune)** - Set up authentication with `napt auth`, upload the package with `napt upload`, and roll it out with `napt promote`
- **[Common Tasks](common-tasks.md)** - Step-by-step guides, including a recipe walkthrough for each discovery strategy
- **[User Guide](user-guide.md)** - How each command works, configuration layers, and state
- **[Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)** - Browse example recipes for Chrome, Git, and more

