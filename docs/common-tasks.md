# Common Tasks

Step-by-step guides for common NAPT workflows. Each task includes complete, working examples you can copy and adapt.

> **💡 Tip:** Need help with a specific command? Use `napt <command> --help` to see all options and examples. For instance, `napt discover --help` shows discovery command details.

## Initialize a New NAPT Project

Set up the recommended directory structure for a new NAPT project.

### Quick Setup

```bash
# Create and enter project directory
mkdir my-intune-packages
cd my-intune-packages

# Initialize NAPT project structure
napt init
```

**Output:**

```console
$ napt init
Initializing NAPT project in: /path/to/my-intune-packages

[1/2] Creating directory structure...
      Created: recipes/
      Created: defaults/vendors/

[2/2] Creating configuration files...
      Created: defaults/org.yaml

Done! Project initialized.
```

### What Gets Created

```
my-intune-packages/
├── defaults/
│   ├── org.yaml              # Organization-wide defaults (commented template)
│   └── vendors/              # Vendor-specific overrides (empty)
└── recipes/                  # Your recipe files go here
```

### Handling Existing Files

NAPT safely skips existing files by default:

```console
$ napt init
Initializing NAPT project in: /path/to/existing-project

[1/2] Creating directory structure...
      Skipped: recipes/ (already exists)
      Skipped: defaults/vendors/ (already exists)

[2/2] Creating configuration files...
      Skipped: defaults/org.yaml (already exists)

Done! Project initialized.
```

To overwrite existing files (with automatic backup):

```bash
napt init --force
```

This backs up existing files before replacing them:

```console
$ napt init --force
[2/2] Creating configuration files...
      Backed up: defaults/org.yaml -> defaults/org.yaml.backup
      Created: defaults/org.yaml
```

### Next Steps After Init

1. **Edit organization defaults** (optional):
   ```bash
   # Uncomment and customize settings in defaults/org.yaml
   code defaults/org.yaml
   ```

2. **Create your first recipe**:
   ```bash
   mkdir recipes/Google
   code recipes/Google/chrome.yaml
   ```

3. **Validate and test**:
   ```bash
   napt validate recipes/Google/chrome.yaml
   napt discover recipes/Google/chrome.yaml --verbose
   ```

## Create a Recipe for a GitHub Release App

Use this when the application is hosted on GitHub with releases.

**Example: Git for Windows**

1. Create the recipe file:

```yaml
# recipes/Git/git.yaml
apiVersion: napt/v1  # Recipe format version

app:  # Application configuration
  name: "Git for Windows"  # Display name for the application
  id: "napt-git"  # Unique identifier (used for build directories and package names)

  source:  # Discovery configuration - how to find and download the installer
      strategy: api_github  # Discovery strategy: api_github, api_json, url_download, or web_scrape
      repo: "git-for-windows/git"  # GitHub repository (owner/repo format)
      asset_pattern: "Git-.*-64-bit\\.exe$"  # Regex pattern to match installer filename in release assets
      version_pattern: "v?([0-9.]+)\\.windows"  # Regex pattern to extract version from Git tag

  psadt:  # PSAppDeployToolkit configuration
      app_vars:  # PSADT variables (AppName, AppVersion, AppArch)
        AppName: "Git for Windows"
        AppVersion: "${discovered_version}"  # Auto-populated from discovery
        AppArch: "x64"
      install: |  # PowerShell script executed during installation
        Start-ADTProcess -Path "$dirFiles\Git-${discovered_version}-64-bit.exe" -Parameters "/VERYSILENT /NORESTART"
      uninstall: |  # PowerShell script executed during uninstallation
        Uninstall-ADTApplication -Name "Git"
```

2. Validate the recipe:

```bash
napt validate recipes/Git/git.yaml
```

3. Test discovery:

```bash
napt discover recipes/Git/git.yaml --verbose
```

**What to customize:**
- `repo`: GitHub repository (owner/repo format)
- `asset_pattern`: Regex to match the installer filename
- `version_pattern`: Regex to extract version from tag
- `install`/`uninstall`: PowerShell deployment scripts

## Create a Recipe for a Vendor Download Page

Use this when the vendor has a download page listing installers (no API available).

**Example: 7-Zip**

1. Create the recipe file:

```yaml
# recipes/7-Zip/7zip.yaml
apiVersion: napt/v1  # Recipe format version

app:
  name: "7-Zip"  # Display name
  id: "napt-7zip"  # Unique identifier

  source:
      strategy: web_scrape  # Scrape vendor download page for installer link
      page_url: "https://www.7-zip.org/download.html"  # URL of vendor download page
      link_selector: 'a[href$="-x64.msi"]'  # CSS selector to find download link
      version_pattern: "7z(\\d{2})(\\d{2})-x64"  # Regex to extract version from URL (captures year and month)
      version_format: "{0}.{1}"  # Format captured groups as "25.01" (year.month)

  win32:  # Windows-specific configuration for detection and validation
      installed_check:
          display_name: "7-Zip * (x64 edition)"  # Pattern for detecting installed app (wildcards supported)
          override_msi_display_name: true  # Override MSI DisplayName that includes version

  psadt:
      app_vars:  # PSADT variables
        AppName: "7-Zip"
        AppVersion: "${discovered_version}"
        AppArch: "x64"
      install: |  # MSI installation script
        Start-ADTMsiProcess -Action Install -Path "$dirFiles\7z*-x64.msi" -Parameters "ALLUSERS=1"
      uninstall: |  # MSI uninstallation script
        Uninstall-ADTApplication -Name "7-Zip"
```

2. Validate and test:

```bash
napt validate recipes/7-Zip/7zip.yaml
napt discover recipes/7-Zip/7zip.yaml --verbose
```

**What to customize:**

- `page_url`: Vendor download page URL
- `link_selector`: CSS selector to find the download link
- `version_pattern`: Regex to extract version from URL
- `version_format`: Format string to transform version (optional)
- `win32.installed_check`: Configure when vendor includes version in DisplayName (e.g., "7-Zip 25.01")
  - `display_name`: Pattern with wildcards to match the installed app name
  - `override_msi_display_name`: Set to `true` to override MSI's versioned DisplayName

## Create a Recipe for a JSON API Endpoint

Use this when the vendor provides a JSON API with version and download URL.

**Example: Generic JSON API**

1. Create the recipe file:

```yaml
# recipes/Vendor/app.yaml
apiVersion: napt/v1  # Recipe format version

app:
  name: "Application Name"  # Display name
  id: "napt-app"  # Unique identifier

  source:
      strategy: api_json  # Query JSON API for version and download URL
      api_url: "https://api.vendor.com/latest"  # JSON API endpoint URL
      version_path: "version"  # JSONPath to version field (e.g., "version" or "data.version")
      download_url_path: "download_url"  # JSONPath to download URL field
      headers:  # Optional HTTP headers (e.g., for authentication)
        Authorization: "Bearer ${API_TOKEN}"  # Environment variable substitution supported

  psadt:
      app_vars:  # PSADT variables
        AppName: "Application Name"
        AppVersion: "${discovered_version}"
        AppArch: "x64"
      install: |  # Installation script
        Start-ADTProcess -Path "$dirFiles\app-installer.exe" -Parameters "/S"
      uninstall: |  # Uninstallation script
        Uninstall-ADTApplication -Name "Application Name"
```

2. Set environment variable (if needed):

```powershell
# Set environment variable on Windows:
$env:API_TOKEN="your-token-here"
```
```bash
# Set environment variable on Linux/macOS:
export API_TOKEN="your-token-here"
```

3. Validate and test:

```bash
napt validate recipes/Vendor/app.yaml
napt discover recipes/Vendor/app.yaml --verbose
```

**What to customize:**

- `api_url`: JSON API endpoint URL
- `version_path`: JSONPath to version field (e.g., "version" or "data.version")
- `download_url_path`: JSONPath to download URL field
- `headers`: Optional authentication headers

## Create a Recipe for a Fixed Download URL

Use this when the vendor has a stable download URL (like Chrome enterprise MSI).

**Example: Google Chrome**

1. Create the recipe file:

```yaml
# recipes/Google/chrome.yaml
apiVersion: napt/v1  # Recipe format version

app:
  name: "Google Chrome"  # Display name
  id: "napt-chrome"  # Unique identifier

  source:
      strategy: url_download  # Direct download from fixed URL
      url: "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"  # Stable download URL

  psadt:
      app_vars:  # PSADT variables
        AppName: "Google Chrome"
        AppVersion: "${discovered_version}"
        AppArch: "x64"
      install: |  # MSI installation script
        Start-ADTMsiProcess -Action Install -Path "$dirFiles\googlechromestandaloneenterprise64.msi" -Parameters "ALLUSERS=1"
      uninstall: |  # MSI uninstallation script
        Uninstall-ADTApplication -Name "Google Chrome"
```

2. Validate and test:

```bash
napt validate recipes/Google/chrome.yaml
napt discover recipes/Google/chrome.yaml --verbose
```

**What to customize:**

- `url`: Direct download URL (must be stable, not version-specific)
- `app_vars`: Application name, architecture, and other PSADT variables
- `install`/`uninstall`: PowerShell deployment scripts

**Note:** MSI files (`.msi` extension) are automatically detected and versions are extracted from the MSI ProductVersion property. No additional version configuration needed.

## Handle Authentication Tokens

Many APIs require authentication. Here's how to handle tokens securely.

### Environment Variables (Recommended)

1. **Set token in environment:**
   ```powershell
   # Set environment variable on Windows:
   $env:API_TOKEN="your-token-here"
   ```
   ```bash
   # Set environment variable on Linux/macOS:
   export API_TOKEN="your-token-here"
   ```

2. **Reference in recipe:**
   ```yaml
   source:
     strategy: api_json
     api_url: "https://api.vendor.com/latest"
     headers:
       Authorization: "Bearer ${API_TOKEN}"
   ```

3. **In CI/CD, use secrets:**
   ```yaml
   # GitHub Actions
   - name: Discover version
     env:
       API_TOKEN: ${{ secrets.API_TOKEN }}
     run: napt discover recipes/Vendor/app.yaml
   ```

### Recipe-Level Tokens (Less Secure)

If you must store tokens in recipes (not recommended for production):

```yaml
source:
  strategy: api_github
  repo: "owner/repo"
  token: "ghp_your_token_here"  # Not recommended - use env vars instead
```

**Security best practice:** Always use environment variables or CI/CD secrets, never commit tokens to version control.

## Test Recipes Before Production

Validate and test recipes thoroughly before using in production.

1. **Syntax validation:**
   ```bash
   napt validate recipes/Vendor/app.yaml
   ```

2. **Test discovery:**
   ```bash
   napt discover recipes/Vendor/app.yaml --verbose
   ```

3. **Verify downloaded file:**
   ```bash
   # Check file exists and has content
   ls -lh downloads/
   ```

4. **Test build:**
   ```bash
   napt build recipes/Vendor/app.yaml --verbose
   ```

5. **Verify build structure:**
   ```bash
   # Check PSADT files are present
   ls builds/napt-app/*/Invoke-AppDeployToolkit.ps1
   ```

6. **Test packaging:**
   ```bash
   napt package recipes/Vendor/app.yaml --verbose
   ```

7. **Verify .intunewin file:**
   ```bash
   # Check versioned package directory was created
   ls -lh packages/napt-app/
   ```

## Deploy to Intune

Upload a packaged app to Microsoft Intune. Requires `napt package` to have run first.

### App Registration Setup (one time per organization)

1. Go to [entra.microsoft.com](https://entra.microsoft.com) →
   **App registrations** → **New registration**
2. Name it (e.g. "NAPT"), leave redirect URI blank, click **Register**
3. Note the **Application (client) ID** and **Directory (tenant) ID**
4. Go to **API permissions** → **Add a permission** →
   **Microsoft Graph** → **Application permissions**
5. Search for and add `DeviceManagementApps.ReadWrite.All`
6. Repeat for **Delegated permissions** → add `DeviceManagementApps.ReadWrite.All`
7. Click **Grant admin consent**
8. Go to **Authentication** → **Advanced settings** →
   set **Allow public client flows** to **Yes** → click **Save**
   (required for device code flow)

### Developer Setup (one time)

Set two environment variables using the IDs from app registration setup:

```bash
export AZURE_CLIENT_ID="<Application (client) ID>"
export AZURE_TENANT_ID="<Directory (tenant) ID>"
```

On first run, NAPT prompts for authentication in the browser:

```console
To sign in, use a web browser to open the page https://microsoft.com/devicelogin
and enter the code ABCD1234 to authenticate.
```

After consenting once, subsequent runs authenticate silently.

### CI/CD Setup (one time)

Create a client secret: **Certificates & secrets** → **New client secret**.
Add all three as pipeline secrets:

```bash
AZURE_CLIENT_ID="<Application (client) ID>"
AZURE_CLIENT_SECRET="<client secret value>"
AZURE_TENANT_ID="<Directory (tenant) ID>"
```

### Upload an App

```bash
napt upload recipes/Google/chrome.yaml
```

**Example output:**

```console
$ napt upload recipes/Google/chrome.yaml
Uploading 'Google Chrome' (napt-chrome) to Intune...

[1/6] Locating .intunewin package...
[2/6] Authenticating with Azure...
[3/6] Parsing package metadata...
[4/6] Creating Intune app record for 'Google Chrome' 144.0.7559.110...
[5/6] Uploading to Azure Blob Storage...
upload progress: 100%
[6/6] Committing content version...

======================================================================
UPLOAD RESULTS
======================================================================
App ID:        napt-chrome
App Name:      Google Chrome
Version:       144.0.7559.110
Intune App ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Package:       packages/napt-chrome/144.0.7559.110/Invoke-AppDeployToolkit.intunewin
Status:        success
======================================================================

[SUCCESS] App uploaded to Intune successfully!
```

### Full Pipeline Example

```bash
# 1. Check for new version (skips download if unchanged)
napt discover recipes/Google/chrome.yaml

# 2. Build PSADT package
napt build recipes/Google/chrome.yaml

# 3. Create .intunewin package
napt package recipes/Google/chrome.yaml

# 4. Upload to Intune
napt upload recipes/Google/chrome.yaml
```

### CI/CD Setup

Set these environment variables in your CI/CD pipeline:

```yaml
# GitHub Actions example
- name: Upload to Intune
  env:
    AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
    AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
    AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
  run: napt upload recipes/Google/chrome.yaml
```

The app registration must have the `DeviceManagementApps.ReadWrite.All`
Microsoft Graph API permission.

### Override Publisher and Description

By default, the publisher is inferred from the vendor directory name
(e.g., `recipes/Google/` → `"Google"`). Override per-recipe with the
`intune:` section:

```yaml
apiVersion: napt/v1

app:
  name: "Google Chrome"
  id: "napt-chrome"
  # ... rest of recipe

intune:
  publisher: "Google LLC"
  description: "Google Chrome browser for enterprise deployment."
  privacy_url: "https://policies.google.com/privacy"
  info_url: "https://chromeenterprise.google"
```

## Update Existing Recipes

When a recipe needs changes (new version format, different download URL, etc.).

1. **Edit the recipe file:**
   ```bash
   # Edit the YAML file
   code recipes/Vendor/app.yaml
   ```

2. **Validate changes:**
   ```bash
   napt validate recipes/Vendor/app.yaml
   ```

3. **Test discovery:**
   ```bash
   napt discover recipes/Vendor/app.yaml --verbose
   ```

4. **If version format changed, clear state:**
   ```bash
   # Delete state entry for this app
   # Or delete entire state file to start fresh
   rm state/versions.json
   ```

5. **Test full workflow:**
   ```bash
   napt discover recipes/Vendor/app.yaml
   napt build recipes/Vendor/app.yaml
   napt package recipes/Vendor/app.yaml
   napt upload recipes/Vendor/app.yaml
   ```

## Troubleshoot Discovery Failures

Common issues and solutions when `napt discover` fails.

### Issue: "Strategy not found"

**Problem:** Recipe uses a strategy that doesn't exist or isn't registered.

**Solution:**

1. Check strategy name spelling (must be: `api_github`, `api_json`, `url_download`, or `web_scrape`)

2. Validate recipe: `napt validate recipes/App/app.yaml`

3. Check for typos in strategy configuration

### Issue: "Version extraction failed"

**Problem:** NAPT can't extract version from the downloaded file or API response.

**Solution:**

1. Use `--debug` to see what NAPT is trying to parse:

   ```bash
   napt discover recipes/App/app.yaml --debug
   ```

2. For MSI files, verify the file is a valid MSI

3. For `api_json`, check that `version_path` points to the correct JSON field

4. For `web_scrape`, verify `version_pattern` regex matches the URL format

### Issue: "GitHub API rate limit"

**Problem:** Using `api_github` without authentication hits rate limits.

**Solution:**

1. Create a GitHub personal access token
2. Add to recipe:
   ```yaml
   source:
     strategy: api_github
     repo: "owner/repo"
     token: "${GITHUB_TOKEN}"
   ```
3. Set environment variable:
   ```powershell
   # Set environment variable on Windows:
   $env:GITHUB_TOKEN="ghp_your_token_here"
   ```
   ```bash
   # Set environment variable on Linux/macOS:
   export GITHUB_TOKEN="ghp_your_token_here"
   ```

### Issue: "Download failed" or "Network error"

**Problem:** Can't download the installer file.

**Solution:**

1. Check URL is accessible: `curl -I <url>` or open in browser

2. Verify authentication if required (API tokens, headers)

3. Check network connectivity and firewall rules

4. Use `--verbose` to see HTTP request/response details

### Issue: "State file corrupted"

**Problem:** `state/versions.json` has invalid JSON or is corrupted.

**Solution:**

NAPT automatically handles corruption:

1. Creates backup of corrupted file: `state/versions.json.backup`

2. Creates a fresh state file automatically

3. Reports the issue with an error message

The state file is already fixed - just run your command again. Alternatively, use `--stateless` to bypass state tracking temporarily:

```bash
napt discover recipes/app.yaml --stateless
```

## What's Next?

- **[User Guide](user-guide.md)** - Deep dive into discovery strategies, state management, and configuration
- **[Creating Recipes](user-guide.md#discovery-strategies)** - Detailed strategy configuration guides
- **[Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)** - Browse working recipe examples
