# User Guide

This guide covers NAPT's key features, configuration system, and advanced usage patterns.

## How NAPT Works

NAPT automates the complete workflow from version discovery to Intune package creation. Understanding how each step works helps you troubleshoot issues and customize recipes effectively.

### Discovery Process (`napt discover`)

The discovery process finds the latest version and downloads the installer:

1. **Load Configuration** - Merges organization defaults, vendor defaults, and recipe configuration
2. **Check Version** - Uses the configured discovery strategy to check for new versions
3. **Compare with Cache** - Compares discovered version to cached `known_version` in state file
4. **Skip or Download**:
    - If version unchanged and file exists → Skip download 
    - If version changed or file missing → Download installer
5. **Extract Version** - Extracts version from installer (MSI ProductVersion) or uses discovered version
6. **Update State** - Updates `state/versions.json` with new version, file path, SHA-256 hash, and ETag (if download occurred). 

**Output**: Downloaded installer in `downloads/` directory, updated state file

### Build Process (`napt build`)

The build process creates a complete PSADT package from the recipe and downloaded installer:

1. **Load Configuration** - Merges configuration layers (org → vendor → recipe)
2. **Find Installer** - Locates installer in `downloads/` directory (tries URL filename, then app name/id, then most recent). Supports `.msi`, `.exe`, and `.msix` files
3. **Extract Version** - Extracts version from installer file (MSI from ProductVersion, MSIX from AppxManifest.xml), otherwise uses state file version
4. **Get PSADT Release** - Downloads/caches PSADT Template_v4 from GitHub if not already cached
5. **Create Build Directory** - Creates versioned directory using discovered app version: `builds/{app_id}/{version}/`
6. **Copy PSADT Template** - Copies entire PSADT template structure (unmodified) from cache:
    - `PSAppDeployToolkit/` - Core PSADT module
    - `PSAppDeployToolkit.Extensions/` - Extension modules
    - `Assets/` - Default icons and banners
    - `Config/` - Default configuration files
    - `Strings/` - Localization strings
    - `Files/` - Empty directory for installer files
    - `SupportFiles/` - Empty directory for additional files
    - `Invoke-AppDeployToolkit.exe` - Compiled launcher
    - `Invoke-AppDeployToolkit.ps1` - Template script (will be overwritten)
7. **Generate Deployment Script** - Generates `Invoke-AppDeployToolkit.ps1` from template:
    - Substitutes PSADT variables (`$appVendor`, `$appName`, `$appVersion`, etc.) from recipe configuration
    - Inserts install script from `psadt.install` field (for MSIX, auto-generates install/uninstall commands from manifest based on `intune.run_as_account` unless `override_msix_commands: true`)
    - Inserts uninstall script from `psadt.uninstall` field
    - Sets dynamic values (AppScriptDate, discovered version, PSADT version)
    - Preserves PSADT's structure and comments
8. **Copy Installer** - Copies downloaded installer file to `Files/` directory:
    - Source: `downloads/{installer_filename}`
    - Destination: `builds/{app_id}/{version}/Files/{installer_filename}`
    - Installer is accessible in scripts via `$($adtSession.DirFiles)` (PSADT 4.x)
9. **Apply Branding** - Replaces PSADT default assets with custom branding (if configured):
    - Reads `brand_pack` configuration from org/vendor defaults
    - Replaces files in `Assets/` directory (AppIcon.png, Banner.Classic.png, etc.)
    - Uses pattern matching to find source files in brand pack directory
10. **Generate Detection and Requirements Scripts** - Creates PowerShell scripts for Intune Win32 app deployment (detection always generated; requirements only when `build_types` is `both` or `update_only`). See [Detection and Requirements Scripts](#detection-and-requirements-scripts) below for details.

**Output**: Complete PSADT package in `builds/{app_id}/{version}/` with detection script always present, and requirements script when `build_types` is `both` or `update_only`.

#### Detection and Requirements Scripts

NAPT generates PowerShell scripts used by Intune Win32 app entries to check installation state:

- **Detection script** (always generated): Used by the **App** entry and by the **Update** entry when using the two-app model to determine if the app is installed at the expected version. Filename: `{AppName}_{Version}-Detection.ps1`.
- **Requirements script** (when `build_types` is `both` or `update_only`): Used by the **Update** entry to determine if an older version is installed so Intune can offer the update. Filename: `{AppName}_{Version}-Requirements.ps1`.

For MSI and EXE installers, both scripts share the same logic for registry lookup, app name
resolution, and installer-type filtering; they differ only in how they interpret the version
comparison (see below). For MSIX installers, scripts query the AppX package database by
identity name instead of registry scanning; which store is queried depends on
`intune.run_as_account` (see below).

**How the scripts work:**

- **Registry locations checked (architecture-aware):**
    - Scripts use explicit `RegistryView` (Registry64 or Registry32) for deterministic behavior regardless of PowerShell process bitness
    - **For x64/arm64 architecture** (or 64-bit view when architecture is "any"):
        - `HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` (machine-level)
        - `HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` (user-level)
    - **For x86 architecture** (or 32-bit view when architecture is "any" on 64-bit OS):
        - `HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall` (machine-level)
        - `HKCU:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall` (user-level)
    - **For x86 architecture on 32-bit OS**:
        - `HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` (machine-level)
        - `HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` (user-level)
    - **When architecture is "any"** (default): Checks both 64-bit and 32-bit views (all applicable paths above)

- **App name determination:**
    - **MSI installers:** Uses MSI `ProductName` property (authoritative source for registry DisplayName). For MSIs where the vendor includes version in the ProductName (e.g., "7-Zip 25.01"), use `intune.detection.override_msi_display_name: true` to specify a custom `display_name` pattern instead. See [Recipe Reference - detection](recipe-reference.md#detection) for details.
    - **Non-MSI installers:** Requires `intune.detection.display_name` in recipe configuration. Scripts match registry `DisplayName` to this value.

- **Installer type filtering:**
    - **MSI installers (strict):** Only match registry entries that are MSI-based (checks `WindowsInstaller` = 1). Prevents false matches when both MSI and EXE versions exist.
    - **Non-MSI installers (permissive):** Match any registry entry (MSI or non-MSI) to handle EXE installers that run embedded MSIs internally.

- **Architecture filtering:**
    - Controls which registry views are checked based on the `AppArch` value from `psadt.app_vars` in the recipe
    - **MSI installers:** AppArch is automatically extracted from MSI package metadata during discovery (no manual configuration needed)
    - **Non-MSI installers:** AppArch must be explicitly specified in `intune.detection` (e.g., `architecture: "x64"`)
    - **Architecture values:**
        - `x64` / `arm64`: Checks only 64-bit registry view (ARM64 uses 64-bit registry)
        - `x86`: Checks only 32-bit registry view
        - `any` (default if not specified): Checks both 64-bit and 32-bit views for maximum compatibility
    - Uses explicit `RegistryView` API for deterministic behavior regardless of PowerShell process bitness
    - Prevents false matches when both 32-bit and 64-bit versions of the same software are installed

- **MSIX detection (AppX package-based):**
    - MSIX installers query the Windows AppX package database by package identity name
      (from `AppxManifest.xml`), not the registry
    - Which store is queried depends on `intune.run_as_account`:
        - `"system"` (default): `Get-AppxProvisionedPackage -Online` (provisioned/all-users store)
        - `"user"`: `Get-AppxPackage -Name` (per-user store)
    - Architecture is auto-detected from the MSIX manifest's `ProcessorArchitecture` attribute
    - The `intune.detection.display_name`, `architecture`, and `override_msi_display_name`
      fields are not used for MSIX installers

- **Logging:**
    - **Format:** CMTrace format for compatibility with Intune diagnostics tools
    - **Primary locations:**
        - System context: `C:\ProgramData\Microsoft\IntuneManagementExtension\Logs\`
        - User context: `C:\ProgramData\Microsoft\IntuneManagementExtension\Logs\`
        - Detection: `NAPTDetections.log` (system) / `NAPTDetectionsUser.log` (user)
        - Requirements: `NAPTRequirements.log` (system) / `NAPTRequirementsUser.log` (user)
    - **Fallback locations** (used if primary location fails):
        - System context: `C:\ProgramData\NAPT\`
        - User context: `%LOCALAPPDATA%\NAPT\`
        - Same log file names as primary locations
    - **Fallback behavior:** Script tries primary first (creates directory if needed, verifies write access). If that fails (insufficient permissions), tries fallback. If both fail, script continues with a warning to stderr but no log file
    - **Log rotation:** 2-file rotation (.log and .log.old), default 3MB max size per file

**Detection vs Requirements scripts:**

- **Detection script** - Checks if the application is installed at the expected version:
    - Version check: Compares installed version to expected version
    - Match modes: Exact match (installed = expected) or minimum version (installed >= expected)
    - Exit codes: Exit 0 if installed and meets requirement, exit 1 otherwise
    - Used by: Both App and Update entries in Intune
- **Requirements script** - Determines if an installed application needs to be updated:
    - Version check: Determines if installed version < target version
    - Output: Writes "Required" to stdout if update needed, nothing otherwise
    - Exit codes: Always exits 0 (allows Intune to evaluate stdout)
    - Intune configuration: Requirement rule with output type String, operator Equals, value "Required"
    - Used by: Update entry only (to determine if update is applicable)

**Output location and packaging:**

Scripts are saved as siblings to the `packagefiles/` directory and are NOT included in the `.intunewin` package:

```
builds/napt-chrome/144.0.7559.110/
  ├── packagefiles/                                 # PSADT package (packaged into .intunewin)
  │   └── ...
  ├── Google-Chrome-144.0.7559.110-Detection.ps1    # Detection script
  └── Google-Chrome-144.0.7559.110-Requirements.ps1 # Requirements script (if generated)
```

**Configuration:** See [Recipe Reference - Intune Configuration](recipe-reference.md#intune-configuration) for `intune.detection` and `intune.build_types` options.

### Package Process (`napt package`)

The package process creates a `.intunewin` file from a PSADT build for the
recipe's app:

1. **Resolve Build Directory** - Scans `builds/{app_id}/` for the most recently
   modified version directory that contains a `packagefiles/` folder.
   Use `--version VERSION` to target a specific version instead
2. **Verify Structure** - Validates the build directory has the required PSADT structure:
    - `PSAppDeployToolkit/` directory
    - `Files/` directory
    - `Invoke-AppDeployToolkit.ps1` script
    - `Invoke-AppDeployToolkit.exe` launcher
3. **Get IntuneWinAppUtil** - Downloads/caches `IntuneWinAppUtil.exe` from Microsoft's GitHub
   repository. The release is controlled by `intunewin.release` in `defaults/org.yaml`
   (default: `"latest"`). The tool is cached under `cache/tools/{version}/` so each
   pinned release is stored independently
4. **Create Package** - Runs `IntuneWinAppUtil.exe` to create `.intunewin` file:
    - Input: `packagefiles/` subdirectory of the build (PSADT structure)
    - Output: `Invoke-AppDeployToolkit.intunewin` in `packages/{app_id}/{version}/`
    - Previous version directory for this app is removed automatically
5. **Copy Detection Scripts** - Copies `*-Detection.ps1` and `*-Requirements.ps1`
   from the build version directory into `packages/{app_id}/{version}/` so that
   `napt upload` is self-contained and does not need access to the builds directory
6. **Optional Cleanup** - If `--clean-source` flag is used, removes the build
   version directory after successful packaging

**Output**: `.intunewin` and detection scripts in `packages/{app_id}/{version}/`,
ready for `napt upload`. Only one version is kept on disk per app at a time —
packaging a new version removes the previous one automatically.

### Upload Process (`napt upload`)

The upload process publishes a packaged app to Microsoft Intune via the
Graph API. Run `napt package` before uploading.

1. **Locate Package** - Scans `packages/{app_id}/` for the versioned subdirectory
   created by `napt package` and reads `Invoke-AppDeployToolkit.intunewin` from it
2. **Authenticate** - Tries three credential methods in order (see [Authentication](#authentication) below)
3. **Parse Package Metadata** - Reads encryption metadata from `Detection.xml` inside the `.intunewin` ZIP
4. **Create App Record** - POSTs to Graph API to create a new Win32 LOB app in Intune.
   App metadata (display name, install commands, detection/requirements scripts, architecture)
   is assembled from the recipe config and the scripts in the package directory
5. **Upload Encrypted Payload** - Extracts the encrypted payload from the `.intunewin` ZIP
   and uploads it to Azure Blob Storage in 6 MiB chunks
6. **Commit** - Finalizes the upload by committing the content version with encryption metadata

**Output**: Intune app ID, app name, version, and package path

#### Authentication

`napt upload` requires a NAPT app registration in Microsoft Entra ID.
See [App Registration Setup](#app-registration-setup) below.
The authentication method is selected automatically based on environment
variables:

| Method | When it's used |
|--------|---------------|
| `EnvironmentCredential` | `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_TENANT_ID` are set — service principal, recommended for CI/CD |
| `ManagedIdentityCredential` | Running on an Azure VM, Container Instance, or pipeline agent with managed identity assigned — no env vars needed |
| `DeviceCodeCredential` | `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` are set (no secret), interactive terminal — prompts with a URL and code to authenticate in any browser |

#### App Registration Setup

Create the app registration once per organization:

1. Go to [entra.microsoft.com](https://entra.microsoft.com) →
   **App registrations** → **New registration**
2. Name it (e.g. "NAPT"), leave redirect URI blank, click **Register**
3. Note the **Application (client) ID** and **Directory (tenant) ID**
4. Go to **API permissions** → **Add a permission** →
   **Microsoft Graph** → **Application permissions**
5. Search for and add `DeviceManagementApps.ReadWrite.All`
6. Also add the **Delegated** version of `DeviceManagementApps.ReadWrite.All`
   (for interactive device code auth)
7. Click **Grant admin consent**
8. Go to **Authentication** → **Advanced settings** →
   set **Allow public client flows** to **Yes** → click **Save**
   (required for device code flow)

**Developer setup:**

Set two environment variables — no client secret needed:

```bash
export AZURE_CLIENT_ID="<Application (client) ID>"
export AZURE_TENANT_ID="<Directory (tenant) ID>"
```

On first run, NAPT prompts with a device code:

```console
To sign in, use a web browser to open the page https://microsoft.com/devicelogin
and enter the code ABCD1234 to authenticate.
```

After consenting once, subsequent runs authenticate silently.

**CI/CD setup:**

Create a client secret under **Certificates & secrets** → **New client secret**.
Set all three environment variables as pipeline secrets:

```bash
AZURE_CLIENT_ID="<Application (client) ID>"
AZURE_CLIENT_SECRET="<client secret value>"
AZURE_TENANT_ID="<Directory (tenant) ID>"
```

**Azure managed identity:**

No environment variables needed. Assign the managed identity the
`DeviceManagementApps.ReadWrite.All` application permission in Entra ID.

### Directory Structure

After a complete workflow, your directory structure looks like:

```
downloads/
  └── googlechromestandaloneenterprise64.msi

builds/
  └── napt-chrome/
      └── 142.0.7444.163/
          ├── packagefiles/                # PSADT package contents
          │   ├── PSAppDeployToolkit/      # PSADT module (from template)
          │   ├── PSAppDeployToolkit.Extensions/
          │   ├── Assets/                  # Custom branding (if configured)
          │   ├── Config/
          │   ├── Strings/
          │   ├── Files/                   # Installer copied here
          │   │   └── googlechromestandaloneenterprise64.msi
          │   ├── SupportFiles/            # Empty (for additional files)
          │   ├── Invoke-AppDeployToolkit.ps1  # Generated script
          │   └── Invoke-AppDeployToolkit.exe  # From template
          ├── Google-Chrome-142.0.7444.163-Detection.ps1
          └── Google-Chrome-142.0.7444.163-Requirements.ps1

packages/
  └── napt-chrome/
      └── 142.0.7444.163/                              # One version kept at a time
          ├── Invoke-AppDeployToolkit.intunewin        # Encrypted package
          ├── Google-Chrome-142.0.7444.163-Detection.ps1    # Copied by napt package
          └── Google-Chrome-142.0.7444.163-Requirements.ps1 # Copied by napt package

state/
  └── versions.json                        # Version tracking
```

## Commands Reference

> **💡 Tip:** All commands support `--help` (or `-h`) to show detailed usage, options, and examples. Try `napt discover --help` to see what's available.

### napt init

Initializes a new NAPT project with the recommended directory structure. Creates `recipes/`, `defaults/org.yaml`, and `defaults/vendors/`. Existing files are preserved by default; use `--force` to backup and overwrite.

```bash
napt init [DIRECTORY] [OPTIONS]
```

### napt validate

Validates recipe syntax and configuration without making network calls. Checks YAML syntax, required fields, and strategy configuration. Does not verify URLs are accessible or files can be downloaded.

```bash
napt validate recipes/Google/chrome.yaml [OPTIONS]
```

### napt discover

Discovers the latest version and downloads the installer. Uses version-based caching to skip downloads when versions haven't changed.

```bash
napt discover recipes/Google/chrome.yaml [OPTIONS]
```

### napt build

Builds a complete PSADT package from a recipe and downloaded installer. Generates deployment scripts, applies branding, and creates versioned build directories.

```bash
napt build recipes/Google/chrome.yaml [OPTIONS]
```

### napt package

Creates a `.intunewin` package for a recipe's build. The build directory is
inferred automatically from the recipe's app ID. Without `--version`, packages
the most recent build. Only one version is kept on disk per app — previous
package directories are removed automatically.

```bash
napt package recipes/Google/chrome.yaml [OPTIONS]
napt package recipes/Google/chrome.yaml --version 130.0.6723.116
```

### napt upload

Uploads the `.intunewin` package to Microsoft Intune via the Graph API.
Authentication is automatic — no configuration required.

```bash
napt upload recipes/Google/chrome.yaml [OPTIONS]
```

### Output Modes

All commands support verbosity flags to control output detail:

| Flag | What it shows |
|------|---------------|
| (none) | Clean output with step indicators (e.g., `[1/4]`) and progress |
| `--verbose` or `-v` | All of the above, plus HTTP requests/responses, file operations, SHA-256 hashes, and configuration loading |
| `--debug` or `-d` | All verbose output, plus full YAML config dumps (org/vendor/recipe/merged), backend selection details, and regex match groups |

Debug mode includes all verbose output plus deep diagnostic information. Use `--verbose` for normal troubleshooting and `--debug` when you need to understand exactly what NAPT is doing internally.

## Discovery Strategies

Discovery strategies are the core mechanism for obtaining application installers and extracting version information.

### Available Strategies

| Strategy | Version Source | Use Case | Unchanged Version Detection Speed |
|----------|---------------|----------|---------------------|
| **api_github** | Git tags | GitHub-hosted releases | Fast (GitHub API ~100ms) |
| **api_json** | JSON API | REST APIs with metadata | Fast (API call ~100ms) |
| **url_download** | File metadata | Fixed URLs, MSI installers | Medium (HTTP conditional ~500ms) |
| **web_scrape** | Download page | Vendors without APIs | Fast (page scrape + regex) |

> **Note:** For complete configuration examples and field documentation for each strategy, see [Recipe Reference](recipe-reference.md).

### Decision Guide

Use this flowchart to choose the right strategy:

```mermaid
flowchart TD
    Start{JSON API for<br/>version/download?}
    Start -->|Yes| JSON[api_json<br/>Fast version checks]
    Start -->|No| GitHub{Published via<br/>GitHub releases?}
    GitHub -->|Yes| GHRelease[api_github<br/>Reliable API, fast checks]
    GitHub -->|No| DirectURL{Fixed/stable<br/>download URL?}
    DirectURL -->|Yes| Static[url_download<br/>Must download to check]
    DirectURL -->|No| Scrape[web_scrape<br/>Scrape vendor page for link]
```

**Performance Note**: Version-first strategies (everything except url_download) can skip downloads entirely when versions haven't changed, making them ideal for scheduled CI/CD checks.

## Recipe Basics

A recipe file defines how to discover, download, and package an application. Recipes are YAML files that specify:

- **Discovery strategy** - How to find the latest version and download URL
- **PSADT configuration** - PowerShell deployment scripts and variables

### Basic Structure

```yaml
apiVersion: napt/v1    # Recipe format version
name: "Application Name"  # Display name
id: "napt-app-id"      # Unique identifier

discovery:             # Discovery configuration
  strategy: api_github  # One of: api_github, api_json, url_download, web_scrape
  # ... strategy-specific fields

psadt:                 # PSADT configuration
  app_vars:
    AppName: "Application Name"
    AppVersion: "${discovered_version}"
  install: |           # Installation script
    # PowerShell code here
  uninstall: |         # Uninstallation script
    # PowerShell code here

intune:                # Optional: Intune-specific settings
  detection:
    display_name: "Application Name"  # Required for EXE installers
    architecture: "x64"               # Required for EXE installers
```

### Quick Reference

- **Top-level fields:** `apiVersion` (required), `name` (required), `id` (required),
  `discovery` (required), `psadt` (required), `intune` (optional), `logging` (optional)
- **Discovery strategies:** See [Discovery Strategies](#discovery-strategies) section above for strategy selection and examples
- **PSADT scripts:** Use `${discovered_version}` for auto-substituted version, `$($adtSession.DirFiles)` for installer path (PSADT 4.x)

### Complete Documentation

For complete field documentation, all options, and detailed examples, see the [Recipe Reference](recipe-reference.md) page.

For practical workflows and copy-paste examples, see [Common Tasks](common-tasks.md).

## State Management & Caching

NAPT automatically tracks discovered versions and optimizes subsequent runs by avoiding unnecessary downloads. This version-based caching is critical for CI/CD with frequent scheduled checks, providing fast feedback when applications haven't changed.

### How It Works

NAPT uses two caching approaches depending on the discovery strategy:

```mermaid
flowchart TD
    Start([napt discover]) --> Strategy{Strategy Type?}
    
    Strategy -->|Version-First<br/>api_github, api_json, web_scrape| CheckVersion[Check Version via API/Page]
    Strategy -->|File-First<br/>url_download| CheckETag[Check File via HTTP ETag]
    
    CheckVersion --> VersionChanged{Version<br/>Changed?}
    VersionChanged -->|No| FileExists1{File<br/>Exists?}
    VersionChanged -->|Yes| Download1[Download File]
    
    CheckETag --> ETagResponse{Server<br/>Response?}
    ETagResponse -->|304 Not Modified| FileExists2{File<br/>Exists?}
    ETagResponse -->|200 OK Changed| Download2[Download File]
    
    FileExists1 -->|Yes| SkipDownload1([✓ Skip Download<br/>Use cached file])
    FileExists1 -->|No| Download1
    
    FileExists2 -->|Yes| SkipDownload2([✓ Skip Download<br/>Use cached file])
    FileExists2 -->|No| Download2
    
    Download1 --> UpdateState[Update state.json]
    Download2 --> UpdateState
    SkipDownload1 --> UpdateState
    SkipDownload2 --> UpdateState
    UpdateState --> Ready([✓ Ready for napt build])
```

**Performance:** Version-first strategies (api_github, api_json, web_scrape) check versions before downloading (~100-300ms) and skip downloads entirely if unchanged. File-first strategy (url_download) uses HTTP conditional requests (~500ms) with ETag caching.

**Note:** State is updated after every discovery run, even when skipping downloads. This updates the `last_updated` timestamp and confirms the cached version is still current.

### Default Behavior (Stateful)

```bash
# State tracking enabled by default
napt discover recipes/Google/chrome.yaml

# Creates/updates: state/versions.json
```

### Stateless Mode

```bash
# Disable state tracking for one-off checks
napt discover recipes/Google/chrome.yaml --stateless

# Always downloads, no caching
# Useful for CI/CD clean builds
```

## Configuration Layers

NAPT uses a layered configuration system that promotes DRY (Don't Repeat Yourself) principles.
All defaults live in code; configuration files are optional overrides.

### How Configuration Works

```
Code defaults (always complete)     <- baseline, ships with napt
    |
./defaults/org.yaml                 <- organization overrides (optional)
    |
./defaults/vendors/<Vendor>.yaml    <- vendor overrides (optional)
    |
recipe.yaml                         <- recipe-specific overrides
```

**Key principles:**

- Code provides complete, working defaults for all settings
- Config files only override what you need to change
- Missing fields always fall back to code defaults
- Old configs never break when NAPT adds new features
- Any setting can be overridden at any layer — org, vendor, or recipe

### The Three Override Layers

1. **Organization defaults** (`defaults/org.yaml`) - Base overrides for all apps.
Optional; only needed if you want to customize settings organization-wide.
Contains PSADT settings, update policies, and build configuration.

2. **Vendor defaults** (`defaults/vendors/<Vendor>.yaml`) - Vendor-specific overrides.
Optional; only loaded if vendor is detected (e.g., Google-specific settings).

3. **Recipe configuration** (`recipes/<Vendor>/<app>.yaml`) - App-specific settings.
Always required; defines the specific app with final overrides.

### Example

```yaml
# defaults/org.yaml
psadt:
  release: "latest"
  app_vars:
    AppVendor: "Unknown"
```

```yaml
# defaults/vendors/Google.yaml
psadt:
  app_vars:
    AppVendor: "Google LLC"
```

```yaml
# recipes/Google/chrome.yaml
name: "Google Chrome"
id: "napt-chrome"
discovery:
  strategy: url_download
  url: "https://dl.google.com/..."
psadt:
  release: "4.1.7"   # overrides org default of "latest" for this recipe only
# AppVendor will be "Google LLC" (from vendor defaults)
```

### Directory Flag Defaults

All directory flags follow the same pattern: CLI flag overrides config;
config overrides the built-in default.
This is the same pattern used by tools like `npm`, `pytest`, and `ruff`.

Each command reads from the previous command's output directory and writes
to its own:

| Command | Flag | Purpose | Config key | Built-in default |
|---------|------|---------|-----------|-----------------|
| `napt discover` | `--output-dir` | Where to save downloaded installers | `directories.discover` | `downloads` |
| `napt build` | `--downloads-dir` | Where to find the installer | `directories.discover` | `downloads` |
| `napt build` | `--output-dir` | Where to save builds | `directories.build` | `builds` |
| `napt package` | `--builds-dir` | Where to find the build | `directories.build` | `builds` |
| `napt package` | `--output-dir` | Where to save packages | `directories.package` | `packages` |

Note that input and output share a config key across adjacent commands —
`discover --output-dir` and `build --downloads-dir` both read from
`directories.discover`, so the output of one is automatically
the input of the next without extra configuration.

To change the defaults org-wide, add to `defaults/org.yaml`:

```yaml
directories:
  discover: "cache/downloads"   # used by both discover and build
  build: "artifacts/builds"     # used by both build and package
  package: "artifacts/packages"
```

Any CLI flag still overrides the config value for that single run:

```bash
# Uses config default (or built-in if not configured)
napt discover recipes/Google/chrome.yaml

# Overrides for this run only
napt discover recipes/Google/chrome.yaml --output-dir /tmp/downloads
napt build recipes/Google/chrome.yaml --downloads-dir /tmp/downloads
```

### IntuneWinAppUtil Release Pinning

By default NAPT always resolves `"latest"` for `IntuneWinAppUtil.exe` by querying
the GitHub releases API and caching the resolved version.
To pin to a specific release for reproducible builds, set `intunewin.release` in
`defaults/org.yaml`:

```yaml
intunewin:
  release: "1.8.6"   # pin to a specific release
```

The tool is cached under `cache/tools/{version}/` — each pinned release lives in
its own subdirectory, so switching versions just downloads once and caches both.

Use `"latest"` to always resolve the current release:

```yaml
intunewin:
  release: "latest"  # default; resolves via GitHub API on each run if not cached
```

## Cross-Platform Support

**NAPT is a Windows tool** for Microsoft Intune packaging. Develop on any platform, package on Windows.

### Platform Compatibility Matrix

| Platform | Discover & Download | Build | Package |
|----------|---------------------|-------|---------|
| **Windows** | ✅ | ✅ | ✅ |
| **Linux** | ✅ | ✅ | ⚫ Windows Only |
| **macOS** | ✅ | ✅ | ⚫ Windows Only |

### Why Windows for Packaging?

The `napt package` command uses Microsoft's [IntuneWinAppUtil.exe](https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool), which is a Windows-only .NET application. This is the official tool for creating .intunewin packages.

### Recommended Workflows

#### Workflow 1: All-Windows (Simplest)
```bash
# Run everything on Windows
napt discover recipes/Google/chrome.yaml
napt build recipes/Google/chrome.yaml
napt package recipes/Google/chrome.yaml
```

#### Workflow 2: Mixed Platform Development
```bash
# On Linux/macOS: Discovery and build
napt discover recipes/Google/chrome.yaml
napt build recipes/Google/chrome.yaml

# Transfer build directory to Windows (e.g., via shared storage)
# On Windows: Package
napt package recipes/Google/chrome.yaml
```

## Best Practices

### Recipe Organization

Organize recipes by vendor: `recipes/<Vendor>/<app>.yaml`. NAPT automatically detects vendor from directory structure and loads `defaults/vendors/<Vendor>.yaml` if it exists.

### State Management

**Production:** Keep state tracking enabled (default), use version control for state files, run on schedule to detect updates, use `--verbose` in CI/CD.

**Development:** Use `--stateless` for testing, `--debug` for troubleshooting, delete state file to force re-discovery.

### Scripting

All commands return standard exit codes (`0` = success, `1` = error), making them easy to use in automation scripts:

```bash
if napt discover recipes/Google/chrome.yaml; then
    napt build recipes/Google/chrome.yaml
fi
```

## Troubleshooting

### Common Issues

**Problem**: MSI extraction fails on Linux/macOS

```bash
# Solution: Install msitools
sudo apt-get install msitools  # Debian/Ubuntu
brew install msitools           # macOS
```

**Problem**: State file corrupted

```bash
# NAPT automatically creates backup
# Backup saved to: state/versions.json.backup

# Force re-download
napt discover recipes/app.yaml --stateless
```

**Problem**: GitHub API rate limit

> **⚠️ Security Note:** Never put tokens directly in recipe files (e.g., `token: "ghp_abc123"`). Always use environment variable substitution (`token: "${GITHUB_TOKEN}"`) to keep tokens out of version control. See [Handle Authentication Tokens](common-tasks.md#handle-authentication-tokens) for best practices.

```yaml
# Solution: Use authentication token via environment variable
discovery:
  strategy: api_github
  token: "${GITHUB_TOKEN}"  # Environment variable substitution (secure)
```

```powershell
# Set environment variable on Windows:
$env:GITHUB_TOKEN="your_token_here"
```
```bash
# Set environment variable on Linux/macOS: 
export GITHUB_TOKEN="your_token_here"
```


