# Recipe Reference

Complete documentation of all recipe fields, options, and configuration patterns. Use this as a reference when writing recipes.

> **Tip:** For practical examples and workflows, see [Common Tasks](common-tasks.md). For strategy selection guidance, see [Discovery Strategies](user-guide.md#discovery-strategies) in the User Guide.

## Top-Level Fields

```yaml
apiVersion: napt/v1        # Required: Recipe format version
name: "Application Name"   # Required: Display name
id: "napt-app-id"          # Required: Unique identifier
discovery:                  # Required: How to find and download the installer
  strategy: api_github
  # ... strategy-specific fields
psadt:                      # Required: PowerShell deployment configuration
  install: |
    # ...
  uninstall: |
    # ...
intune:                     # Optional: Intune-specific settings
  # ...
logging:                    # Optional: On-device script logging settings
  # ...
```

### apiVersion

**Type:** `string`
**Required:** Yes
**Values:** `napt/v1` (currently only version)

Specifies the recipe format version. Currently only `napt/v1` is supported.

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

## Discovery Configuration

The `discovery` section defines how NAPT finds and downloads the installer. The structure
depends on the chosen `strategy`.

**Common Fields (All Strategies):**

- `strategy`: Required. One of: `api_github`, `api_json`, `url_download`, `web_scrape`

### api_github Strategy

**Best for:** Open-source projects on GitHub with releases and semantic versioned tags.

**Configuration:**

```yaml
discovery:
  strategy: api_github
  repo: "owner/repository"          # Required: GitHub repository in owner/repo format
  asset_pattern: ".*\\.exe$"        # Required: Regex pattern to match installer filename
  version_pattern: "v?([0-9.]+)"    # Required: Regex pattern to extract version from Git tag
  token: "${GITHUB_TOKEN}"          # Optional: GitHub personal access token
```

#### repo

**Type:** `string`
**Required:** Yes
**Format:** `owner/repository` (e.g., `git-for-windows/git`)

GitHub repository identifier in owner/repository format.

#### asset_pattern

**Type:** `string` (regex)
**Required:** Yes

Regular expression pattern to match the installer filename in release assets. The pattern is
matched against asset filenames from the GitHub Releases API.

**Examples:**
- `"Git-.*-64-bit\\.exe$"` - Matches Git installers for 64-bit
- `".*\\.msi$"` - Matches any MSI file
- `"app-.*-x64\\.exe$"` - Matches app installers for x64

**Note:** Escape special regex characters (e.g., `\\.` for literal dot).

#### version_pattern

**Type:** `string` (regex)
**Required:** Yes

Regular expression pattern to extract version from the Git tag. Should include capture groups
for version components.

**Examples:**
- `"v?([0-9.]+)"` - Extracts version from tags like `v2.51.2` or `2.51.2`
- `"release-([0-9]+\\.[0-9]+)"` - Extracts version from tags like `release-1.5`

**Note:** The first capture group is used as the version string.

#### token

**Type:** `string`
**Required:** No
**Default:** None

GitHub personal access token for authenticated API requests. Use environment variable
substitution (e.g., `"${GITHUB_TOKEN}"`) for security.

**When to use:**

- Avoid GitHub API rate limits (60 requests/hour unauthenticated, 5000/hour authenticated)
- Access private repositories

**How it works:** Queries GitHub Releases API, finds the latest release, matches assets using
`asset_pattern`, extracts version from tag using `version_pattern`.

### api_json Strategy

**Best for:** Vendors with JSON REST APIs, cloud services with version endpoints, or APIs
requiring authentication.

**Configuration:**

```yaml
discovery:
  strategy: api_json
  api_url: "https://api.vendor.com/latest"   # Required: JSON API endpoint URL
  version_path: "version"                    # Required: JSONPath to version field
  download_url_path: "download_url"          # Required: JSONPath to download URL field
  headers:                                   # Optional: HTTP headers for authentication
    Authorization: "Bearer ${API_TOKEN}"
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

JSONPath expression to extract the download URL field from the API response. Supports nested
paths (same format as `version_path`).

#### headers

**Type:** `object` (key-value pairs)
**Required:** No
**Default:** None

HTTP headers to include in the API request. Useful for authentication tokens, API keys, or
custom headers.

**Environment Variable Substitution:** Use `${VARIABLE_NAME}` syntax. NAPT substitutes
environment variables at runtime.

**Example:**
```yaml
headers:
  Authorization: "Bearer ${API_TOKEN}"
  X-API-Key: "${VENDOR_API_KEY}"
```

**How it works:** Makes HTTP GET request to `api_url`, extracts version using `version_path`,
extracts download URL using `download_url_path`. Supports nested JSON paths.

### url_download Strategy

**Best for:** Vendors with stable download URLs and MSI installers with embedded ProductVersion.

**Configuration:**

```yaml
discovery:
  strategy: url_download
  url: "https://vendor.com/installer.msi"   # Required: Stable download URL
```

#### url

**Type:** `string` (URL)
**Required:** Yes

Stable download URL for the installer. **Important:** This URL must not change when new versions
are released. If the URL changes with each version, use `web_scrape` strategy instead.

**How it works:** Downloads file from `url`, auto-detects MSI files by extension (`.msi`) and
extracts version from MSI ProductVersion property. Uses HTTP conditional requests (ETags) for
caching to avoid re-downloading unchanged files.

**Version Extraction:** Automatically detected by file extension. MSI files (`.msi` extension)
automatically extract ProductVersion. No configuration needed. Other file types are not
supported for version extraction — use a version-first strategy (api_github, api_json,
web_scrape) instead.

### web_scrape Strategy

**Best for:** Vendors with download pages listing installers when no direct download URL or API
is available.

**Configuration:**

```yaml
discovery:
  strategy: web_scrape
  page_url: "https://vendor.com/download"           # Required: URL of vendor download page
  link_selector: 'a[href$=".msi"]'                  # Required: CSS selector to find download link
  version_pattern: "app-(\\d+\\.\\d+)\\.msi"        # Required: Regex to extract version from URL
  version_format: "{0}"                              # Optional: Format string for captured groups
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

**Note:** The selector should match exactly one link. If multiple links match, the first match
is used.

#### version_pattern

**Type:** `string` (regex)
**Required:** Yes

Regular expression pattern to extract version from the discovered download URL. Should include
capture groups for version components.

**Examples:**
- `"app-(\\d+\\.\\d+)\\.msi"` - Extracts `1.5` from `app-1.5.msi`
- `"7z(\\d{2})(\\d{2})-x64"` - Captures year and month from `7z2501-x64.msi` (groups: `25`, `01`)
- `"v([0-9.]+)"` - Extracts version from `v2.51.2` (captures `2.51.2`)

**Note:** Use capture groups `( )` to extract version components. The first capture group is
used by default, or use `version_format` to combine multiple groups.

#### version_format

**Type:** `string` (format string)
**Required:** No
**Default:** Use first capture group as-is

Format string to combine multiple capture groups from `version_pattern`. Uses Python format
string syntax with `{0}`, `{1}`, etc. for capture groups.

**Examples:**
- `"{0}.{1}"` - Combines two groups: `"25"` + `"01"` → `"25.01"`
- `"{1}.{0}"` - Reverses order: `"01"` + `"25"` → `"01.25"`
- `"v{0}"` - Prefixes version: `"2.51.2"` → `"v2.51.2"`

**How it works:** Downloads HTML from `page_url`, finds link using CSS selector, extracts
version from URL using regex pattern, formats version using `version_format` if provided.

## PSADT Configuration

The `psadt` section defines PowerShell deployment scripts and PSADT variables:

```yaml
psadt:
  release: "latest"                      # Optional: PSADT release version
  app_vars:                              # Optional: PSADT application variables
    AppName: "Application Name"
    AppVersion: "${discovered_version}"  # Use for auto-substitution
  install: |                             # Required: PowerShell installation script
    Start-ADTMsiProcess -Action Install -Path "$dirFiles\installer.msi" -Parameters "ALLUSERS=1"
  uninstall: |                           # Required: PowerShell uninstallation script
    Uninstall-ADTApplication -Name "Application Name"
```

### release

**Type:** `string`
**Required:** No
**Default:** `"latest"` (from organization defaults)

PSADT release version to use. Can be:

- `"latest"` - Use the latest PSADT release from GitHub
- Specific version: `"4.1.7"` - Use a specific PSADT version

**Note:** Typically set in organization defaults (`defaults/org.yaml`) rather than per-recipe.

### app_vars

**Type:** `object` (key-value pairs)
**Required:** No
**Default:** Merged from organization and vendor defaults

PSADT application variables set in the generated `Invoke-AppDeployToolkit.ps1` file.

**Common Variables:**

- `AppName`: Display name shown in PSADT dialogs
- `AppVersion`: Application version (use `${discovered_version}` for auto-substitution)
- `AppVendor`: Vendor name (typically set in vendor defaults)
- `AppArch`: Architecture (`x64`, `x86`, or `All`)
- `AppLang`: Application language

**Special Variable:** `${discovered_version}` is automatically substituted with the version
discovered by NAPT. Use this in `AppVersion` to ensure the version matches the downloaded
installer.

**Environment Variable Substitution:** All values support `${VARIABLE_NAME}` syntax.

### install

**Type:** `string` (multiline)
**Required:** Yes

PowerShell script executed during installation. Inserted into the generated
`Invoke-AppDeployToolkit.ps1` in the installation section.

**Available Variables:**

- `$dirFiles`: Path to installer files directory (contains downloaded installer)
- `$discovered_version`: Version discovered by NAPT
- Standard PSADT variables: `$dirApp`, `$dirSupportFiles`, etc.
- All `app_vars` are available (e.g., `$AppName`, `$AppVersion`)

**Commonly Used PSADT Functions:**

- `Start-ADTProcess`: Execute EXE installers with parameters
- `Start-ADTMsiProcess`: Install MSI files with parameters
- `Uninstall-ADTApplication`: Uninstall applications by name

**Example:**
```yaml
install: |
  Start-ADTMsiProcess -Action Install -Path "$dirFiles\installer.msi" -Parameters "ALLUSERS=1 /qn"
```

### uninstall

**Type:** `string` (multiline)
**Required:** Yes

PowerShell script executed during uninstallation. Same available variables as `install`.

**Example:**
```yaml
uninstall: |
  Uninstall-ADTApplication -Name "Application Name"
```

## Intune Configuration

The `intune` section configures Win32 app settings for Intune packaging and upload.

```yaml
intune:
  build_types: "both"                                # Optional: which entries to create
  update_name_prefix: "[Update] "                    # Optional: prefix for Update entry name
  minimum_supported_windows_release: "Windows10_21H2" # Optional: minimum Windows release
  install_command: "Invoke-AppDeployToolkit.exe ..."  # Optional: override install command
  uninstall_command: "Invoke-AppDeployToolkit.exe ..." # Optional: override uninstall command
  is_featured: false                                 # Optional: feature app in Company Portal
  allow_available_uninstall: true                    # Optional: show Uninstall in Company Portal
  run_as_account: "system"                           # Optional: system or user
  device_restart_behavior: "allow"                   # Optional: allow, suppress, force, basedOnReturnCode
  max_run_time_minutes: 60                           # Optional: max installer runtime
  enforce_signature_check: false                     # Optional: require script signing
  run_as_32_bit: false                               # Optional: run in 32-bit context
  description: "App description for Intune portal"  # Optional: app description
  publisher: "Vendor Name"                           # Optional: publisher name override
  category: "Productivity"                           # Optional: Intune app category
  privacy_url: "https://vendor.com/privacy"          # Optional: privacy information URL
  info_url: "https://vendor.com"                     # Optional: information URL
  logo_path: "brand-packs/logos/app.png"             # Optional: path to app icon
  developer: "Developer Name"                        # Optional: developer field
  owner: "IT Team"                                   # Optional: business owner field
  notes: "Free-text notes shown in Intune portal"    # Optional: notes field
  detection:                                         # Optional: detection configuration
    display_name: "Application Name"
    architecture: "x64"
    exact_match: false
    override_msi_display_name: false
```

### build_types

**Type:** `string`
**Required:** No
**Default:** `"both"`
**Allowed values:** `"both"`, `"app_only"`, `"update_only"`

Specifies which Intune app entries to create during build. The **detection script** is always
generated. This setting controls **requirements script** generation only:

- `"both"` (default): Generate detection and requirements scripts (App + Update entries)
- `"app_only"`: Generate only the detection script (App entry only)
- `"update_only"`: Generate detection and requirements scripts (Update entry only)

**Example:**
```yaml
intune:
  build_types: "app_only"  # Only create App entry for this app
```

### update_name_prefix

**Type:** `string`
**Required:** No
**Default:** `"[Update] "`

Prefix added to the app name for the Update app entry in Intune. The Update app display name is:
`update_name_prefix + name`.

**Example:**
```yaml
intune:
  update_name_prefix: "[Update] "

# Results in:
# - App entry: "Google Chrome"
# - Update entry: "[Update] Google Chrome"
```

### minimum_supported_windows_release

**Type:** `string`
**Required:** No
**Default:** `"Windows10_21H2"`

Minimum Windows 10/11 feature update required to install the app, enforced during Intune
assignment. Format: `"Windows10_<release>"` or `"Windows11_<release>"` where release is
the feature update name (e.g., `"Windows10_21H2"`, `"Windows10_22H2"`, `"Windows11_23H2"`).

### install_command

**Type:** `string`
**Required:** No
**Default:** `"Invoke-AppDeployToolkit.exe -DeploymentType Install -DeployMode Silent"`

Command line used by Intune to install the app. Rarely needs changing unless you need custom
PSADT deployment parameters.

### uninstall_command

**Type:** `string`
**Required:** No
**Default:** `"Invoke-AppDeployToolkit.exe -DeploymentType Uninstall -DeployMode Silent"`

Command line used by Intune to uninstall the app.

### is_featured

**Type:** `boolean`
**Required:** No
**Default:** `false`

When `true`, the app is marked as featured in the Company Portal, giving it
prominent placement on the home screen.

### allow_available_uninstall

**Type:** `boolean`
**Required:** No
**Default:** `true`

When `true`, the "Uninstall" action is available in the Company Portal for Available
assignments.
Set to `false` to prevent self-service uninstall for this app.

### run_as_account

**Type:** `string`
**Required:** No
**Default:** `"system"`
**Allowed values:** `"system"`, `"user"`

Execution account for the installer and detection/requirements scripts.
Use `"system"` for most enterprise deployments.
Use `"user"` for apps that must be installed in the user's profile context.

### device_restart_behavior

**Type:** `string`
**Required:** No
**Default:** `"allow"`
**Allowed values:** `"allow"`, `"suppress"`, `"force"`, `"basedOnReturnCode"`

Controls how Intune handles device restarts after install:

| Value | Behavior |
|-------|----------|
| `"allow"` | Intune may restart the device if needed |
| `"suppress"` | Suppress any restart, even if the installer requests one |
| `"force"` | Force a restart after install completes |
| `"basedOnReturnCode"` | Restart based on the installer's return code |

### max_run_time_minutes

**Type:** `integer`
**Required:** No
**Default:** `60`

Maximum time in minutes Intune waits for the installer to complete before
marking the install as failed.
Increase for apps with long installation times (e.g., large Office deployments).

### enforce_signature_check

**Type:** `boolean`
**Required:** No
**Default:** `false`

When `true`, Intune requires detection and requirements scripts to be
code-signed before execution.
Leave as `false` unless your organization enforces PowerShell script signing policy.

### run_as_32_bit

**Type:** `boolean`
**Required:** No
**Default:** `false`

When `true`, runs the installer and detection/requirements scripts in a
32-bit PowerShell context.
Required for 32-bit installers that cannot run in a 64-bit host process.

### description

**Type:** `string`
**Required:** No
**Default:** None

App description displayed in the Intune portal and Company Portal app.

### publisher

**Type:** `string`
**Required:** No
**Default:** Vendor directory name (e.g., `recipes/Google/` → `"Google"`)

Publisher name shown in Intune and the Company Portal. Override when the directory name doesn't
match the official publisher name.

### category

**Type:** `string`
**Required:** No
**Default:** None

Intune app category. Must match an existing category name in your Intune tenant.

### privacy_url

**Type:** `string` (URL)
**Required:** No
**Default:** None

Link to the vendor's privacy policy. Shown in the Intune portal.

### info_url

**Type:** `string` (URL)
**Required:** No
**Default:** None

Link to more information about the app. Shown in the Intune portal.

### logo_path

**Type:** `string` (path)
**Required:** No
**Default:** None

Path to a PNG or JPEG icon file to use as the app icon in Intune and the Company Portal.
Relative paths are resolved from the recipe file's location.

### developer

**Type:** `string`
**Required:** No
**Default:** None

Developer or maintainer name. Shown in the Intune portal's app details.

### owner

**Type:** `string`
**Required:** No
**Default:** None

Business owner of the application. Shown in the Intune portal's app details.

### notes

**Type:** `string`
**Required:** No
**Default:** None

Free-text notes shown in the Intune portal. Useful for internal documentation.

### detection

The `intune.detection` subsection configures detection and requirements script generation for
Intune Win32 app deployments. These scripts check Windows uninstall registry keys to determine
application installation state.

```yaml
intune:
  detection:
    display_name: "Application Name"  # See below
    architecture: "x64"               # See below
    exact_match: false                # See below
    override_msi_display_name: false  # See below
```

#### display_name

**Type:** `string`
**Required:** Yes for non-MSI installers, ignored for MSI installers

Application name used in scripts to match registry `DisplayName`. This value is also used in
generated script filenames.

**Behavior:**

- **MSI installers:** Ignored (a warning is logged if set). MSI `ProductName` is used as the
  authoritative source since it directly corresponds to the registry `DisplayName`.
- **Non-MSI installers (EXE, etc.):** Required. Scripts check Windows uninstall registry keys
  for this exact `DisplayName` value.

**Note:** The value is sanitized for use in Windows filenames (spaces become hyphens, invalid
characters removed). Script filenames follow the pattern:
`{DisplayName}_{Version}-Detection.ps1` and `{DisplayName}_{Version}-Requirements.ps1`.

**Template Variable Support:** `${discovered_version}` is automatically substituted with the
discovered version. Use this when the registry DisplayName includes the version number (e.g.,
"7-Zip 25.01 (x64)").

**Wildcard Support:** When `display_name` contains wildcards (`*` or `?`), scripts use
PowerShell's `-like` operator instead of exact `-eq` matching:

| Wildcard | Meaning | Example |
|----------|---------|---------|
| `*` | Matches zero or more characters | `"7-Zip *"` matches "7-Zip 24.09", "7-Zip 25.01 (x64)" |
| `?` | Matches exactly one character | `"7-Zip ??.??"` matches "7-Zip 24.09" but not "7-Zip 24.9" |

**Example:**
```yaml
intune:
  detection:
    display_name: "My Application"  # Matches registry DisplayName for EXE installers
```

**Example with version in DisplayName:**
```yaml
intune:
  detection:
    display_name: "7-Zip ${discovered_version} (x64)"  # Matches "7-Zip 25.01 (x64)"
```

**Example with wildcard (for MSI with override):**
```yaml
intune:
  detection:
    display_name: "7-Zip * (x64 edition)"  # Matches any 7-Zip x64 version
    override_msi_display_name: true
```

#### architecture

**Type:** `string`
**Required:** Yes for non-MSI installers, ignored for MSI installers
**Allowed values:** `x86`, `x64`, `arm64`, `any`

Specifies the installer's binary architecture. Controls which registry views detection and
requirements scripts check, and which device architectures the app is offered to in Intune.

**Behavior:**

- **MSI installers:** Ignored (a warning is logged if set). Architecture is auto-detected from
  the MSI Summary Information `Template` property.
- **Non-MSI installers (EXE, etc.):** Required. Must be set in recipe configuration.

**Allowed values:**

| Value | Registry view | Intune device targets |
|-------|---------------|-----------------------|
| `x86` | 32-bit only | x86, x64, ARM64 — all Windows can run x86 via WOW64 |
| `x64` | 64-bit only | x64, ARM64 — ARM64 Windows 11 supports x64 emulation |
| `arm64` | 64-bit only | ARM64 only — native binary |
| `any` | All views | x86, x64, ARM64 — permissive |

**Example:**
```yaml
intune:
  detection:
    display_name: "My Application"
    architecture: "x64"  # Required for EXE installers
```

#### exact_match

**Type:** `boolean`
**Required:** No
**Default:** `false`

If `true`, the detection script requires an exact version match. If `false`, detection passes if
the installed version is greater than or equal to the required version.

- `exact_match: false` (default): Allows users to have newer versions without triggering
  reinstall
- `exact_match: true`: Requires exact version match (useful for compliance scenarios)

#### override_msi_display_name

**Type:** `boolean`
**Required:** No
**Default:** `false`
**Applies to:** MSI installers only

When `true`, uses the `display_name` field instead of the MSI's ProductName for registry
lookups.

**When to use:** When the MSI's ProductName contains a version number that changes with each
release (e.g., "7-Zip 25.01").

**Behavior:**

- `false` (default): Uses MSI ProductName (authoritative source)
- `true`: Uses `display_name` field (must be set)
- Non-MSI installers: Flag is ignored (a warning is logged if set)

**Note:** Architecture is still auto-detected from the MSI Template property even when using
this override.

**Example:**
```yaml
intune:
  detection:
    display_name: "7-Zip * (x64 edition)"  # Matches any 7-Zip x64 version
    override_msi_display_name: true         # Use display_name instead of MSI ProductName
    # architecture still auto-detected from MSI Template
```

**How Scripts Work:**

- **App Name Detection:**
    - **MSI installers:** Uses MSI `ProductName` property (authoritative source for registry
      `DisplayName`). The `display_name` field is ignored unless `override_msi_display_name:
      true` is set.
    - **Non-MSI installers:** Requires `intune.detection.display_name` in recipe configuration.
    - **Wildcard matching:** When `display_name` contains `*` or `?`, scripts use PowerShell's
      `-like` operator for flexible matching.
- **Installer Type Filtering:**
    - **MSI installers (strict):** Only matches registry entries with `WindowsInstaller` = 1.
    - **Non-MSI installers (permissive):** Matches any registry entry.
- **Architecture-Aware Registry Checking:** Uses explicit registry views for deterministic
  detection (`x64`/`arm64`: 64-bit view; `x86`: 32-bit view; `any`: both views). For MSI
  installers, architecture is auto-detected from the MSI Template property.
- **Version Comparison:** Uses `DisplayVersion` registry value. Detection: exit 0 if installed
  meets requirement, 1 otherwise. Requirements: always exit 0; output "Required" to stdout if
  an older version is installed, nothing otherwise.
- **Script Location:** Generated scripts are saved as siblings to the `packagefiles/` directory
  (not included in `.intunewin` package). `napt upload` reads them directly from the build
  output and embeds them as inline PowerShell rules in the Intune app record.

See [Detection and Requirements Scripts](user-guide.md#detection-and-requirements-scripts) in
the User Guide for how scripts work and how to configure them in Intune.

## Logging Configuration

The `logging` section controls on-device logging for detection and requirements scripts.

```yaml
logging:
  log_format: "cmtrace"   # Optional: log format
  log_level: "INFO"       # Optional: minimum log level
  log_rotation_mb: 3      # Optional: max log file size in MB
```

These settings are typically configured in `defaults/org.yaml` rather than per-recipe.

### log_format

**Type:** `string`
**Required:** No
**Default:** `"cmtrace"`
**Allowed values:** `"cmtrace"`

Log format for detection and requirements scripts. Currently only CMTrace format is supported
(compatible with Configuration Manager Trace Log Tool).

### log_level

**Type:** `string`
**Required:** No
**Default:** `"INFO"`
**Allowed values:** `"INFO"`, `"WARNING"`, `"ERROR"`, `"DEBUG"`

Minimum log level for detection and requirements scripts. Controls verbosity of log output.

### log_rotation_mb

**Type:** `integer`
**Required:** No
**Default:** `3`

Maximum log file size in megabytes before rotation. Scripts use a 2-file rotation scheme
(`.log` and `.log.old`).

**Note:** Scripts try the Intune folder first:
`C:\ProgramData\Microsoft\IntuneManagementExtension\Logs\` (creating the parent directory if
it does not exist and verifying write access). If that fails (e.g., permissions), they fall back
to `C:\ProgramData\NAPT\` (system) or `%LOCALAPPDATA%\NAPT\` (user). If both fail, a warning is
written to stderr and the script runs without a log file.

## Environment Variable Substitution

NAPT supports environment variable substitution throughout recipe files using `${VARIABLE_NAME}`
syntax.

### Where It Works

- **Discovery configuration:** API tokens, authentication headers
- **PSADT app_vars:** Any variable value
- **Special variable:** `${discovered_version}` is automatically substituted with the discovered
  version

### Syntax

```yaml
discovery:
  token: "${GITHUB_TOKEN}"
  headers:
    Authorization: "Bearer ${API_TOKEN}"

psadt:
  app_vars:
    AppVersion: "${discovered_version}"  # NAPT auto-substitution
    AppVendor: "${ORG_NAME}"             # Environment variable
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

**Note:** For CI/CD, set environment variables in your pipeline configuration (GitHub Actions,
Azure DevOps, etc.).

## Complete Example

```yaml
apiVersion: napt/v1

name: "Example Application"
id: "napt-example"

discovery:
  strategy: api_github
  repo: "owner/repo"
  asset_pattern: ".*-x64\\.exe$"
  version_pattern: "v?([0-9.]+)"

intune:
  detection:
    display_name: "Example Application"
    architecture: "x64"

psadt:
  app_vars:
    AppName: "Example Application"
    AppVersion: "${discovered_version}"
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
