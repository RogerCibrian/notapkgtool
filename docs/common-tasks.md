# Common Tasks

Step-by-step guides for common NAPT workflows. Each task includes complete, working examples you can copy and adapt.

> **💡 Tip:** Need help with a specific command? Use `napt <command> --help` to see all options and examples. For instance, `napt discover --help` shows discovery command details.

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
   napt package builds/napt-app/*/
   ```

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
   napt package builds/napt-app/*/ --verbose
   ```

7. **Verify .intunewin file:**
   ```bash
   # Check file was created
   ls -lh packages/napt-app/*.intunewin
   ```

## What's Next?

- **[User Guide](user-guide.md)** - Deep dive into discovery strategies, state management, and configuration
- **[Creating Recipes](user-guide.md#discovery-strategies)** - Detailed strategy configuration guides
- **[Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)** - Browse working recipe examples

