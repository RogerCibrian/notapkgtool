# Recipe Reference

Complete documentation of all recipe fields, options, and configuration patterns. Use this as a reference when writing recipes.

> **💡 Tip:** For practical examples and workflows, see [Common Tasks](common-tasks.md). For strategy selection guidance, see [Discovery Strategies](user-guide.md#discovery-strategies) in the User Guide.

## Top-Level Fields

```yaml
apiVersion: v1  # Required: Recipe format version (currently v1)
app:  # Required: Application configuration
  name: "Application Name"
  # ... app configuration
```

### apiVersion

**Type:** `string`  
**Required:** Yes  
**Values:** `v1` (currently only version)

Specifies the recipe format version. Currently only `v1` is supported.

### app

**Type:** `object`  
**Required:** Yes

Application configuration defining discovery, download, and packaging settings for a single application.

## App Configuration

The `app` object defines the application:

```yaml
app:
  name: "Application Name"  # Required: Display name for the application
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
```

#### url

**Type:** `string` (URL)  
**Required:** Yes

Stable download URL for the installer. **Important:** This URL must not change when new versions are released. If the URL changes with each version, use `web_scrape` strategy instead.

**How it works:** Downloads file from `url`, auto-detects MSI files by extension (`.msi`) and extracts version from MSI ProductVersion property. Uses HTTP conditional requests (ETags) for caching to avoid re-downloading unchanged files.

**Version Extraction:** Automatically detected by file extension. MSI files (`.msi` extension) automatically extract ProductVersion. No configuration needed. Other file types are not supported for version extraction - use a version-first strategy (api_github, api_json, web_scrape) instead.

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

## Win32 Configuration

The `win32` section configures Win32-specific build settings including the two-app model (App + Update) and installed-state checking (detection and requirements scripts).

### build_types

**Type:** `string`  
**Required:** No  
**Default:** `"both"`

Specifies which Intune app entries to create during build. The **detection script** is always generated (used by the App entry and by the Update entry when applicable). This setting controls **requirements script** generation only:

- `"both"` (default): Generate detection and requirements scripts (App + Update entries in build manifest)
- `"app_only"`: Generate only the detection script (App entry only)
- `"update_only"`: Generate detection and requirements scripts (Update entry only)

**Configuration Location:**

- **Organization defaults:** `defaults/org.yaml` → `defaults.win32.build_types`
- **Recipe (per-app):** `app.win32.build_types` (overrides defaults)

**Example:**
```yaml
# Organization defaults
defaults:
  win32:
    build_types: "both"

# Per-app override
app:
  name: "My App"
  win32:
    build_types: "app_only"  # Only create App entry for this app
```

### installed_check

The `installed_check` section configures detection and requirements script generation for Intune Win32 app deployments. These scripts check Windows uninstall registry keys to determine application installation state.

**Configuration Location:**

- **Organization defaults:** `defaults/org.yaml` → `defaults.win32.installed_check`
- **Vendor defaults:** `defaults/vendors/<Vendor>.yaml` → `defaults.win32.installed_check`
- **Recipe (per-app):** `app.win32.installed_check` (overrides defaults)

**Configuration:**

```yaml
defaults:
  win32:
    installed_check:
      fail_on_error: true       # If true, script generation failures abort the build.
      log_rotation_mb: 3        # Maximum log file size in MB before rotation
      detection:
        exact_match: false      # If true, version must match exactly.

# Per-app override:
app:
  name: "My App"
  win32:
    installed_check:
      display_name: "My Application"  # Required for non-MSI installers
      detection:
        exact_match: true       # Override default for this app
```

#### display_name

**Type:** `string`  
**Required:** Yes for non-MSI installers, ignored for MSI installers

Application name used in scripts to match registry `DisplayName`. This value is used both in script logic and generated filenames.

**Behavior:**

- **MSI installers:** This field is ignored (a warning is logged if set). MSI `ProductName` is used as the authoritative source since it directly corresponds to the registry `DisplayName`.
- **Non-MSI installers (EXE, etc.):** Required. Must be set in recipe configuration. Scripts check Windows uninstall registry keys for this exact `DisplayName` value.

**Note:** The value is sanitized for use in Windows filenames (spaces become hyphens, invalid characters removed). Script filenames follow the pattern: `{DisplayName}_{Version}-Detection.ps1` and `{DisplayName}_{Version}-Requirements.ps1`.

**Template Variable Support:**

- `${discovered_version}`: Automatically substituted with the version discovered by NAPT. Use this when the registry DisplayName includes the version number (e.g., "7-Zip 25.01 (x64)").

**Wildcard Support:**

When `display_name` contains wildcards (`*` or `?`), the generated scripts use PowerShell's `-like` operator instead of exact `-eq` matching:

| Wildcard | Meaning | Example |
|----------|---------|---------|
| `*` | Matches zero or more characters | `"7-Zip *"` matches "7-Zip 24.09", "7-Zip 25.01 (x64)" |
| `?` | Matches exactly one character | `"7-Zip ??.??"` matches "7-Zip 24.09" but not "7-Zip 24.9" |

Use `*` for most cases - it's flexible and handles varying version formats. Use `?` only when you need precise control over character positions (rare).

**Example:**
```yaml
app:
  name: "My App"
  win32:
    installed_check:
      display_name: "My Application"  # Matches registry DisplayName for EXE installers
```

**Example with version in DisplayName:**
```yaml
app:
  name: "7-Zip (x64) EXE"
  win32:
    installed_check:
      display_name: "7-Zip ${discovered_version} (x64)"  # Matches "7-Zip 25.01 (x64)" in registry
```

**Example with wildcard (for MSI with override):**
```yaml
app:
  name: "7-Zip (x64) MSI"
  win32:
    installed_check:
      display_name: "7-Zip *"  # Matches any 7-Zip version
      override_msi_display_name: true
```

#### architecture

**Type:** `string`  
**Required:** Yes for non-MSI installers, ignored for MSI installers  
**Allowed values:** `x86`, `x64`, `arm64`, `any`

Specifies the expected architecture for detection/requirements scripts. This controls which registry views are checked.

**Behavior:**

- **MSI installers:** This field is ignored (a warning is logged if set). Architecture is auto-detected from the MSI Summary Information `Template` property.
- **Non-MSI installers (EXE, etc.):** Required. Must be set in recipe configuration.

**Allowed values:**

| Value | Description |
|-------|-------------|
| `x86` | 32-bit x86; checks only 32-bit registry view |
| `x64` | 64-bit x64/AMD64; checks only 64-bit registry view |
| `arm64` | 64-bit ARM; checks only 64-bit registry view |
| `any` | Checks all registry views (permissive, matches legacy behavior) |

**Why this matters:** Without architecture filtering, an x86 installation could satisfy x64 detection if the DisplayName and version match, potentially blocking proper x64 deployment. The architecture-aware approach ensures detection scripts check the correct registry view for the target architecture.

**Example:**
```yaml
app:
  name: "My App"
  win32:
    installed_check:
      display_name: "My Application"
      architecture: "x64"  # Required for EXE installers
```

#### override_msi_display_name

**Type:** `boolean`  
**Required:** No  
**Default:** `false`  
**Applies to:** MSI installers only

When `true`, uses the `display_name` field instead of the MSI's ProductName for registry lookups.

**When to Use:**

Use this flag when the MSI's ProductName contains a version number that changes with each release. Common examples:
- "7-Zip 25.01" - version embedded in ProductName
- "Application Name v1.2.3" - version prefix in ProductName

Without this flag, detection/requirements scripts would look for an exact match on the versioned ProductName, causing:
- Detection to fail when checking for a different version than installed
- Requirements to fail when installed version differs from target

**Behavior:**

- **MSI with `override_msi_display_name: false` (default):** Uses MSI ProductName (authoritative source)
- **MSI with `override_msi_display_name: true`:** Uses `display_name` field (must be set)
- **Non-MSI installers:** Flag is ignored (a warning is logged if set)

**Note:** Architecture is still auto-detected from the MSI Template property even when using this override.

**Example:**
```yaml
app:
  name: "7-Zip (x64) MSI"
  win32:
    installed_check:
      display_name: "7-Zip *"           # Matches any 7-Zip version
      override_msi_display_name: true   # Use display_name instead of MSI ProductName
      # architecture still auto-detected from MSI Template
```

#### fail_on_error

**Type:** `boolean`  
**Required:** No  
**Default:** `true`

If `true`, script generation failures will abort the build. If `false`, build continues even if script generation fails (useful for development/testing).

**Behavior:**

- `fail_on_error: true` (default): Build fails if scripts cannot be generated
- `fail_on_error: false`: Build continues, script paths will be `None` in BuildResult

#### log_rotation_mb

**Type:** `integer`  
**Required:** No  
**Default:** `3`

Maximum log file size in megabytes before rotation. Scripts use a 2-file rotation scheme (`.log` and `.log.old`).

**Note:** Scripts try the Intune folder first: `C:\ProgramData\Microsoft\IntuneManagementExtension\Logs\` (files: `NAPTDetections.log` / `NAPTDetectionsUser.log` or `NAPTRequirements.log` / `NAPTRequirementsUser.log`), creating the parent directory if it does not exist and verifying write access. If that fails (e.g. permissions), they fall back to `C:\ProgramData\NAPT\` (system) or `%LOCALAPPDATA%\NAPT\` (user), creating that parent if needed. If both primary and fallback fail, a warning is written to stderr and the script runs without a log file. Requirements scripts always exit 0 and indicate applicability via stdout ("Required" or nothing); configure the requirement rule in Intune with output type String, operator Equals, value "Required".

#### detection.exact_match

**Type:** `boolean`  
**Required:** No  
**Default:** `false`

If `true`, the detection script requires an exact version match. If `false`, the detection script passes if the installed version is greater than or equal to the required version (minimum version check).

**Behavior:**

- `exact_match: false` (default): Allows users to have newer versions installed without triggering reinstall
- `exact_match: true`: Requires exact version match (useful for compliance scenarios)

**How Scripts Work:**

- **App Name Detection:**
    - **MSI installers:** Uses MSI `ProductName` property (authoritative source for registry `DisplayName`). The `display_name` field is ignored unless `override_msi_display_name: true` is set.
    - **Non-MSI installers:** Requires `win32.installed_check.display_name` in recipe configuration. This value is matched against the registry `DisplayName`.
    - **Wildcard matching:** When `display_name` contains `*` or `?`, scripts use PowerShell's `-like` operator for flexible matching instead of exact `-eq` comparison.
- **Installer Type Filtering:**
    - Scripts automatically detect installer type from file extension during build.
    - **MSI installers (strict):** Only matches registry entries with `WindowsInstaller` = 1. Prevents false matches when both MSI and EXE versions exist.
    - **Non-MSI installers (permissive):** Matches ANY registry entry. Handles EXE installers that run embedded MSIs internally.
- **Architecture-Aware Registry Checking:** Uses explicit registry views for deterministic detection:
    - `x64`/`arm64`: Checks only 64-bit registry view (Registry64)
    - `x86`: Checks only 32-bit registry view (Registry32)
    - `any`: Checks both views (permissive mode)
    - For MSI installers, architecture is auto-detected from the MSI Template property.
    - For non-MSI installers, `architecture` must be specified in the recipe.
- **Version Comparison:** Uses `DisplayVersion` registry value. Detection: exit 0 if installed meets requirement, 1 otherwise. Requirements: always exit 0; output "Required" to stdout if an older version is installed, nothing otherwise.
- **Script Location:** Generated scripts are saved as siblings to the `packagefiles/` directory (not included in `.intunewin` package - must be uploaded separately to Intune).

See [Detection and Requirements Scripts](user-guide.md#detection-and-requirements-scripts) in the User Guide for how the scripts work and how to use them in Intune.

## Intune Configuration

The `intune` section configures Intune-specific settings for app publishing.

### update_name_prefix

**Type:** `string`  
**Required:** No  
**Default:** `"[Update] "`

Prefix added to the app name for the Update app entry in Intune. The Update app display name is: `update_name_prefix + app.name`.

**Configuration Location:**

- **Organization defaults:** `defaults/org.yaml` → `defaults.intune.update_name_prefix`
- **Recipe (per-app):** `app.intune.update_name_prefix` (overrides defaults)

**Example:**
```yaml
defaults:
  intune:
    update_name_prefix: "[Update] "

# Results in:
# - App entry: "Google Chrome"
# - Update entry: "[Update] Google Chrome"
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

app:
  name: "Example Application"
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

