# Quick start guide

## Installation

### Prerequisites

- Python 3.11 or higher

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

> **Note:** This installs unreleased code from `main`.

**Prerequisites:** Git and
[Poetry](https://python-poetry.org/docs/#installation).

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

Windows needs nothing extra.
Linux and macOS need `msitools` to read MSI installers (discover and build)
and cannot create .intunewin packages (that step requires Windows):

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

Every command and subcommand accepts:

- `-h`, `--help` - Show help and examples
- `-v`, `--verbose` - Show progress details and additional information
- `-d`, `--debug` - Show full diagnostics including configuration dumps

For `napt promote` and `napt auth`, pass `-v` and `-d` to the subcommand
(`napt promote plan -v`, not `napt promote -v`).

### Initialize a new project

```bash
# Initialize in current directory
napt init

# Initialize in a specific directory
napt init /path/to/project

# Replace defaults/org.yaml with a fresh template
# (the old one is kept as defaults/org.yaml.backup)
napt init --force
```

`napt init` creates `recipes/`, `defaults/org.yaml` (a commented template),
`defaults/vendors/`, and `state/deployment/`.

## Complete workflow: recipe to package

### 1. Create a recipe

`napt init` leaves `recipes/` empty.
Save this recipe as `recipes/Google/chrome.yaml`:

```yaml
apiVersion: napt/v1
name: "Google Chrome"
id: "napt-chrome"

discovery:
  strategy: url_download
  url: "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"

psadt:
  app_vars:
    AppName: "Google Chrome"
    AppVersion: "{{discovered_version}}"
```

NAPT downloads the MSI from the fixed URL and reads the version from it.
[Create a recipe for a fixed download URL](common-tasks.md#create-a-recipe-for-a-fixed-download-url)
explains what to customize.

### 2. Validate the recipe

`napt validate` checks syntax and configuration without network calls:

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

### 3. Discover and download the latest version

```console
$ napt discover recipes/Google/chrome.yaml
Discovering version for recipe: /path/to/recipes/Google/chrome.yaml

[1/4] Loading configuration...
[2/4] Discovering version...
[3/4] Fetching installer...
[DOWNLOAD] Complete: googlechromestandaloneenterprise64.msi (<hash>...) in <seconds>s at <speed> MB/s
[4/4] Updating state...
[STATE] Recorded pending release <version> in state/deployment/napt-chrome.json
======================================================================
DISCOVERY RESULTS
======================================================================
App Name:        Google Chrome
App ID:          napt-chrome
Strategy:        url_download
Version:         <version>
Version Source:  msi
File Path:       downloads/napt-chrome/<version>/googlechromestandaloneenterprise64.msi
SHA-256:         <sha256>
Status:          success
======================================================================

[SUCCESS] Version discovered successfully!
```

Re-running `napt discover` skips the download when nothing changed; the fetch
step reports `[DISCOVERY] File not modified` instead.
Add `--stateless` to skip recording the pending release; the download and
reuse logic is unchanged.
`--output-dir <dir>` downloads somewhere other than `downloads/`.
To force a download, see
[Discover reuses an installer you want downloaded again](common-tasks.md#issue-discover-reuses-an-installer-you-want-downloaded-again).

### 4. Build the PSADT package

Build the PSADT deployment folder:

```console
$ napt build recipes/Google/chrome.yaml
Building PSADT package for recipe: /path/to/recipes/Google/chrome.yaml

[1/8] Loading configuration...
[2/8] Finding installer...
[3/8] Determining version...
[BUILD] Building Google Chrome v<version>
[BUILD] Extracted app icon (256px): icons/napt-chrome.png
[4/8] Getting PSADT release...
[PSADT] Downloading PSADT <psadt version>...
[BUILD] Using PSADT <psadt version>
[5/8] Creating build structure...
[BUILD] Auto-generated MSI install: Start-ADTMsiProcess -Action Install -FilePath 'googlechromestandaloneenterprise64.msi' -AdditionalArgumentList "ALLUSERS=1"
[BUILD] Auto-generated MSI uninstall: Uninstall-ADTApplication -Name 'Google Chrome' -NameMatch 'Exact' -ApplicationType 'MSI'
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
Build Directory: builds/napt-chrome/<version>/packagefiles
Status:          success
======================================================================

[SUCCESS] PSADT package built successfully!
```

`--downloads-dir` and `--output-dir` change where build looks for the
installer and where it writes the build.

### 5. Create the .intunewin package

This step requires Windows.

```console
$ napt package recipes/Google/chrome.yaml
Creating .intunewin package from: builds/napt-chrome/<version>
Output directory: packages

[1/5] Verifying build structure...
[2/5] Getting IntuneWinAppUtil tool...
[PACKAGE] Downloading IntuneWinAppUtil.exe <tool version>...
[PACKAGE] IntuneWinAppUtil.exe <tool version> cached successfully
[3/5] Creating .intunewin package...
[4/5] Copying detection scripts...
[5/5] Package complete
======================================================================
PACKAGE RESULTS
======================================================================
App ID:          napt-chrome
Version:         <version>
Package Path:    packages/napt-chrome/<version>/Invoke-AppDeployToolkit.intunewin
Build Directory: builds/napt-chrome/<version>
Status:          success
======================================================================

[SUCCESS] .intunewin package created successfully!
```

`--output-dir` sets the parent folder for the package; `--clean-source`
removes the build folder after packaging.

**Result:** Ready-to-upload .intunewin file in `packages/napt-chrome/<version>/`

## What's next?

- **[Deploy to Intune](common-tasks.md#deploy-to-intune)** - Continue from
  the package you just built: create the app registration with
  `napt auth setup`, sign in with `napt auth login`, upload with
  `napt upload`, then roll the release out through the rings with
  `napt promote plan` and `napt promote apply`
- **[Common tasks](common-tasks.md)** - Step-by-step guides, including a
  recipe walkthrough for each discovery strategy
- **[User guide](user-guide.md)** - How each command works, configuration
  layers, and state
- **[Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)** -
  Browse example recipes for Chrome, Git, and more

