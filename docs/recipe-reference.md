# Recipe Reference

Complete documentation of all recipe fields, options, and configuration patterns. Use this as a reference when writing recipes.

> **💡 Tip:** For practical examples and workflows, see [Common Tasks](common-tasks.md). For strategy selection guidance, see [Discovery Strategies](user-guide.md#discovery-strategies) in the User Guide.

## Top-Level Fields

```yaml
apiVersion: v1  # Required: Recipe format version (currently v1)
apps:  # Required: List of applications to package
  - name: "Application Name"
    # ... app configuration
```

### apiVersion

**Type:** `string`  
**Required:** Yes  
**Values:** `v1` (currently only version)

Specifies the recipe format version. Currently only `v1` is supported.

### apps

**Type:** `array`  
**Required:** Yes

List of applications to package. Each item in the array defines one application with its own discovery, download, and packaging configuration.

## App Configuration

Each item in the `apps` array defines one application:

```yaml
apps:
  - name: "Application Name"  # Required: Display name for the application
    id: "napt-app-id"  # Required: Unique identifier (used for build directories, package names)
    source:  # Required: Discovery configuration
      # ... strategy-specific configuration
    psadt:  # Required: PSAppDeployToolkit configuration
      # ... PSADT settings
```

### name

**Type:** `string`  
**Required:** Yes

Display name for the application. Used in PSADT dialogs and package metadata.

### id

**Type:** `string`  
**Required:** Yes  
**Format:** Lowercase, alphanumeric, hyphens only (e.g., `napt-chrome`, `napt-git`)

Unique identifier for the application. Used to generate:
- Build directory names: `builds/{id}/{version}/`
- Package names: `packages/{id}/Invoke-AppDeployToolkit.intunewin`

**Naming Convention:** Use `napt-` prefix followed by application name (e.g., `napt-chrome`, `napt-git`).

### source

**Type:** `object`  
**Required:** Yes

Discovery configuration that defines how NAPT finds and downloads the installer. The structure depends on the chosen `strategy`.

**Common Fields (All Strategies):**

- `strategy`: Required. One of: `api_github`, `api_json`, `url_download`, `web_scrape`

See strategy-specific sections below for complete configuration options.

### psadt

**Type:** `object`  
**Required:** Yes

PSAppDeployToolkit configuration that defines PowerShell deployment scripts and PSADT variables.

See [PSADT Configuration](#psadt-configuration) section below for complete options.

## Source Configuration

The `source` section configuration depends on the chosen discovery strategy.

### api_github Strategy

**Best for:** Open-source projects on GitHub with releases and semantic versioned tags.

**Configuration:**

```yaml
source:
  strategy: api_github  # Discovery strategy type
  repo: "owner/repository"  # Required: GitHub repository in owner/repo format
  asset_pattern: ".*\\.exe$"  # Required: Regex pattern to match installer filename in release assets
  version_pattern: "v?([0-9.]+)"  # Required: Regex pattern to extract version from Git tag
  token: "${GITHUB_TOKEN}"  # Optional: GitHub personal access token (use env var for security)
```

#### repo

**Type:** `string`  
**Required:** Yes  
**Format:** `owner/repository` (e.g., `git-for-windows/git`)

GitHub repository identifier in owner/repository format.

#### asset_pattern

**Type:** `string` (regex)  
**Required:** Yes

Regular expression pattern to match the installer filename in release assets. The pattern is matched against asset filenames from the GitHub Releases API.

**Examples:**
- `"Git-.*-64-bit\\.exe$"` - Matches Git installers for 64-bit
- `".*\\.msi$"` - Matches any MSI file
- `"app-.*-x64\\.exe$"` - Matches app installers for x64

**Note:** Escape special regex characters (e.g., `\\.` for literal dot).

#### version_pattern

**Type:** `string` (regex)  
**Required:** Yes

Regular expression pattern to extract version from the Git tag. Should include capture groups for version components.

**Examples:**
- `"v?([0-9.]+)"` - Extracts version from tags like `v2.51.2` or `2.51.2`
- `"release-([0-9]+\\.[0-9]+)"` - Extracts version from tags like `release-1.5`

**Note:** The first capture group is used as the version string.

#### token

**Type:** `string`  
**Required:** No  
**Default:** None

GitHub personal access token for authenticated API requests. Use environment variable substitution (e.g., `"${GITHUB_TOKEN}"`) for security.

**When to use:**
- Avoid GitHub API rate limits (60 requests/hour unauthenticated, 5000/hour authenticated)
- Access private repositories

**How it works:** Queries GitHub Releases API, finds the latest release, matches assets using `asset_pattern`, extracts version from tag using `version_pattern`.

### api_json Strategy

**Best for:** Vendors with JSON REST APIs, cloud services with version endpoints, or APIs requiring authentication.

**Configuration:**

```yaml
source:
  strategy: api_json  # Discovery strategy type
  api_url: "https://api.vendor.com/latest"  # Required: JSON API endpoint URL
  version_path: "version"  # Required: JSONPath to version field (e.g., "version" or "data.version")
  download_url_path: "download_url"  # Required: JSONPath to download URL field
  headers:  # Optional: HTTP headers for authentication
    Authorization: "Bearer ${API_TOKEN}"  # Environment variable substitution supported
```

#### api_url

**Type:** `string` (URL)  
**Required:** Yes

JSON API endpoint URL that returns version and download URL information.

#### version_path

**Type:** `string` (JSONPath)  
**Required:** Yes

JSONPath expression to extract the version field from the API response. Supports nested paths.

**Examples:**
- `"version"` - Direct field: `{"version": "1.2.3"}`
- `"data.version"` - Nested field: `{"data": {"version": "1.2.3"}}`
- `"release.latest.version"` - Deeply nested: `{"release": {"latest": {"version": "1.2.3"}}}`

#### download_url_path

**Type:** `string` (JSONPath)  
**Required:** Yes

JSONPath expression to extract the download URL field from the API response. Supports nested paths (same format as `version_path`).

#### headers

**Type:** `object` (key-value pairs)  
**Required:** No  
**Default:** None

HTTP headers to include in the API request. Useful for authentication tokens, API keys, or custom headers.

**Environment Variable Substitution:** Use `${VARIABLE_NAME}` syntax. NAPT substitutes environment variables at runtime.

**Example:**
```yaml
headers:
  Authorization: "Bearer ${API_TOKEN}"
  X-API-Key: "${VENDOR_API_KEY}"
```

**How it works:** Makes HTTP GET request to `api_url`, extracts version using `version_path`, extracts download URL using `download_url_path`. Supports nested JSON paths.

### url_download Strategy

**Best for:** Vendors with stable download URLs and MSI installers with embedded ProductVersion.

**Configuration:**

```yaml
source:
  strategy: url_download  # Discovery strategy type
  url: "https://vendor.com/installer.msi"  # Required: Stable download URL (must not change with versions)
  version:  # Required: Version extraction configuration
    type: msi  # Required: Extract version from MSI ProductVersion property
    file: "installer.msi"  # Optional: Specific filename if multiple files downloaded
```

#### url

**Type:** `string` (URL)  
**Required:** Yes

Stable download URL for the installer. **Important:** This URL must not change when new versions are released. If the URL changes with each version, use `web_scrape` strategy instead.

#### version

**Type:** `object`  
**Required:** Yes

Version extraction configuration.

##### type

**Type:** `string`  
**Required:** Yes  
**Values:** `msi` (currently only supported type)

Method to extract version from the downloaded file. Currently only `msi` is supported, which extracts the `ProductVersion` property from MSI files.

##### file

**Type:** `string`  
**Required:** No  
**Default:** Auto-detected from download

Specific filename to use for version extraction if multiple files are downloaded or the filename differs from the URL.

**How it works:** Downloads file from `url`, extracts version from MSI ProductVersion property. Uses HTTP conditional requests (ETags) for caching to avoid re-downloading unchanged files.

### web_scrape Strategy

**Best for:** Vendors with download pages listing installers when no direct download URL or API is available.

**Configuration:**

```yaml
source:
  strategy: web_scrape  # Discovery strategy type
  page_url: "https://vendor.com/download"  # Required: URL of vendor download page
  link_selector: 'a[href$=".msi"]'  # Required: CSS selector to find download link
  version_pattern: "app-(\\d+\\.\\d+)\\.msi"  # Required: Regex to extract version from discovered URL
  version_format: "{0}"  # Optional: Format string for captured groups (default: use first capture group)
```

#### page_url

**Type:** `string` (URL)  
**Required:** Yes

URL of the vendor download page that contains links to installer files.

#### link_selector

**Type:** `string` (CSS selector)  
**Required:** Yes

CSS selector to find the download link on the page. Uses standard CSS selector syntax.

**Examples:**
- `'a[href$=".msi"]'` - Matches links ending in `.msi`
- `'a.download-link'` - Matches links with `download-link` class
- `'#download-button'` - Matches element with `download-button` ID
- `'a[href*="installer"]'` - Matches links containing "installer"

**Note:** The selector should match exactly one link. If multiple links match, the first match is used.

#### version_pattern

**Type:** `string` (regex)  
**Required:** Yes

Regular expression pattern to extract version from the discovered download URL. Should include capture groups for version components.

**Examples:**
- `"app-(\\d+\\.\\d+)\\.msi"` - Extracts `1.5` from `app-1.5.msi`
- `"7z(\\d{2})(\\d{2})-x64"` - Captures year and month from `7z2501-x64.msi` (groups: `25`, `01`)
- `"v([0-9.]+)"` - Extracts version from `v2.51.2` (captures `2.51.2`)

**Note:** Use capture groups `( )` to extract version components. The first capture group is used by default, or use `version_format` to combine multiple groups.

#### version_format

**Type:** `string` (format string)  
**Required:** No  
**Default:** Use first capture group as-is

Format string to combine multiple capture groups from `version_pattern`. Uses Python format string syntax with `{0}`, `{1}`, etc. for capture groups.

**Examples:**
- `"{0}.{1}"` - Combines two groups: `"25"` + `"01"` → `"25.01"`
- `"{1}.{0}"` - Reverses order: `"01"` + `"25"` → `"01.25"`
- `"v{0}"` - Prefixes version: `"2.51.2"` → `"v2.51.2"`

**How it works:** Downloads HTML from `page_url`, finds link using CSS selector, extracts version from URL using regex pattern, formats version using `version_format` if provided.

## PSADT Configuration

The `psadt` section defines PowerShell deployment scripts and PSADT variables:

```yaml
psadt:
  release: "latest"  # Optional: PSADT release version (default: "latest")
  app_vars:  # Optional: PSADT application variables
    AppName: "Application Name"  # Display name in PSADT dialogs
    AppVersion: "${discovered_version}"  # Version (use ${discovered_version} for auto-substitution)
    AppArch: "x64"  # Architecture: x64, x86, or All
    # ... other PSADT variables
  install: |  # Required: PowerShell script executed during installation
    # Your installation logic here
    Start-ADTMsiProcess -Action Install -Path "$dirFiles\installer.msi" -Parameters "ALLUSERS=1"
  uninstall: |  # Required: PowerShell script executed during uninstallation
    # Your uninstallation logic here
    Uninstall-ADTApplication -Name "Application Name"
```

### release

**Type:** `string`  
**Required:** No  
**Default:** `"latest"` (from organization defaults)

PSADT release version to use. Can be:
- `"latest"` - Use the latest PSADT release from GitHub
- Specific version: `"4.1.7"` - Use a specific PSADT version

**Note:** This is typically set in organization defaults (`defaults/org.yaml`) rather than per-recipe.

### app_vars

**Type:** `object` (key-value pairs)  
**Required:** No  
**Default:** Merged from organization and vendor defaults

PSADT application variables that are available in deployment scripts. These variables are set in the generated `Invoke-AppDeployToolkit.ps1` file.

**Common Variables:**

- `AppName`: Display name shown in PSADT dialogs
- `AppVersion`: Application version (use `${discovered_version}` for auto-substitution)
- `AppArch`: Architecture (`x64`, `x86`, or `All`)
- `AppVendor`: Vendor name (typically set in vendor defaults)
- `AppLang`: Application language
- `AppMaint`: Maintenance mode flag
- `DeployMode`: Deployment mode (`Install`, `Uninstall`, `Repair`)

**Special Variable:**

- `${discovered_version}`: Automatically substituted with the version discovered by NAPT. Use this in `AppVersion` to ensure the version matches the downloaded installer.

**Environment Variable Substitution:**

All values in `app_vars` support environment variable substitution using `${VARIABLE_NAME}` syntax. NAPT substitutes environment variables at runtime.

**Example:**
```yaml
app_vars:
  AppVersion: "${discovered_version}"  # NAPT auto-substitution
  AppVendor: "${ORG_NAME}"  # Environment variable
```

### install

**Type:** `string` (multiline)  
**Required:** Yes

PowerShell script executed during installation. This script is inserted into the generated `Invoke-AppDeployToolkit.ps1` file in the installation section.

**Available Variables:**

- `$dirFiles`: Path to installer files directory (contains downloaded installer)
- `$discovered_version`: Version discovered by NAPT
- Standard PSADT variables: `$dirApp`, `$dirSupportFiles`, `$dirFiles`, etc.
- All `app_vars` are available as variables (e.g., `$AppName`, `$AppVersion`)

**Commonly Used PSADT Functions:**

These are some of the most frequently used PSADT functions. PSADT provides 134+ functions - see the [PSADT Reference Documentation](https://psappdeploytoolkit.com/) for the complete function reference.

- `Start-ADTProcess`: Execute EXE installers with parameters
- `Start-ADTMsiProcess`: Install MSI files with parameters
- `Uninstall-ADTApplication`: Uninstall applications by name (handles ProductCode lookup automatically)

**Example:**
```yaml
install: |
  Start-ADTMsiProcess -Action Install -Path "$dirFiles\installer.msi" -Parameters "ALLUSERS=1 /qn"
```

### uninstall

**Type:** `string` (multiline)  
**Required:** Yes

PowerShell script executed during uninstallation. This script is inserted into the generated `Invoke-AppDeployToolkit.ps1` file in the uninstallation section.

**Available Variables:**

Same as `install` script (see above).

**Example:**
```yaml
uninstall: |
  Uninstall-ADTApplication -Name "Application Name"
```

## Environment Variable Substitution

NAPT supports environment variable substitution throughout recipe files using `${VARIABLE_NAME}` syntax.

### Where It Works

- **Source configuration:** API tokens, authentication headers
- **PSADT app_vars:** Any variable value
- **Special variable:** `${discovered_version}` is automatically substituted with the discovered version

### Syntax

```yaml
source:
  token: "${GITHUB_TOKEN}"  # Environment variable
  headers:
    Authorization: "Bearer ${API_TOKEN}"  # Environment variable

psadt:
  app_vars:
    AppVersion: "${discovered_version}"  # NAPT auto-substitution
    AppVendor: "${ORG_NAME}"  # Environment variable
```

### Setting Environment Variables

**Windows (PowerShell):**
```powershell
$env:GITHUB_TOKEN="your_token_here"
```

**Windows (Command Prompt):**
```cmd
set GITHUB_TOKEN=your_token_here
```

**Linux/macOS:**
```bash
export GITHUB_TOKEN="your_token_here"
```

**Note:** For CI/CD, set environment variables in your pipeline configuration (GitHub Actions, Azure DevOps, etc.).

## Complete Example

```yaml
apiVersion: v1

apps:
  - name: "Example Application"
    id: "napt-example"
    source:
      strategy: api_github
      repo: "owner/repo"
      asset_pattern: ".*-x64\\.exe$"
      version_pattern: "v?([0-9.]+)"
    psadt:
      app_vars:
        AppName: "Example Application"
        AppVersion: "${discovered_version}"
        AppArch: "x64"
      install: |
        Start-ADTProcess -Path "$dirFiles\*.exe" -Parameters "/S"
      uninstall: |
        Uninstall-ADTApplication -Name "Example Application"
```

## See Also

- [Common Tasks](common-tasks.md) - Practical workflows and examples
- [Discovery Strategies](user-guide.md#discovery-strategies) - Strategy selection guide
- [User Guide](user-guide.md) - Complete user documentation
- [PSADT Reference](https://psappdeploytoolkit.com/) - Complete PSADT function reference

