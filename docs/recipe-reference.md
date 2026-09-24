# Recipe reference

Complete documentation of every recipe field and configuration pattern.

> **Tip:** For practical examples and workflows, see [Common Tasks](common-tasks.md). For strategy selection guidance, see [Discovery Strategies](user-guide.md#discovery-strategies) in the User Guide.

## Top-level fields

```yaml
apiVersion: napt/v1        # Required: Recipe format version
parent: ../_base/app.yaml  # Optional: Recipe merged beneath this one
name: "Application Name"   # Required: Display name
id: "napt-app-id"          # Required: Unique identifier
discovery:                  # Required: How to find and download the installer
  strategy: api_github
  # ... strategy-specific fields
psadt:                      # Optional for MSI/MSIX; EXE needs install and uninstall
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
**Values:** `napt/v1` (the only version so far)

Recipe format version.

### name

**Type:** `string`
**Required:** Yes

Display name for the application. Used in PSADT dialogs and package metadata.

### id

**Type:** `string`
**Required:** Yes
**Convention:** Lowercase, alphanumeric, hyphens (e.g., `napt-chrome`, `napt-git`)

Unique identifier for the application.
It names the app's folders, so it must work as a folder name as-is: letters,
digits, `.`, `-`, `_`, and `+`, starting with a letter or digit.
`napt validate` rejects anything else, including path separators and `..`.
Used to generate:

- Download directory: `downloads/{id}/{version}/`
- Build directory: `builds/{id}/{version}/`
- Package directory: `packages/{id}/{version}/`

### parent

**Type:** `string`
**Required:** No

Path to another recipe, relative to this file's directory, that is merged
beneath this one.
This recipe wins wherever both set a value; the parent fills in everything
else.
A parent is an ordinary recipe and cannot declare a `parent` of its own.
`name` and `id` must be set in this file when the parent's values are not
wanted, since they identify the app in Intune and in NAPT's state.

Name a recipe that declares `parent` as `<app>.override.yaml` so the
relationship shows in every listing.
`napt validate` warns when the field and the file name disagree in either
direction, and reports the parent it merged.

Relative paths a parent sets, such as `intune.logo_path`, resolve against
this file's directory, not the parent's.
See [Configuration layers](user-guide.md#configuration-layers) for where the
parent sits in the merge order and how lists merge.

## Discovery configuration

The `discovery` section defines how NAPT finds and downloads the installer. The structure
depends on the chosen `strategy`.

**Common Fields (All Strategies):**

- `strategy`: Required. One of: `api_github`, `api_json`, `url_download`, `web_scrape`

**Why `version_pattern` differs by strategy:** the regex exists to pull a
version out of something that is not one, so each strategy needs it in
proportion to how raw its source is.
`web_scrape` requires it, because the version is buried in a link URL.
`api_github` defaults it to `v?([0-9.]+)`, because Git tags conventionally
carry a `v`.
`api_json` leaves it off unless you set it, because a JSON version field is
usually already a version; add it only when the API wraps the value.
`url_download` has no such field, because the version is read from the
installer itself.

### api_github strategy

**Best for:** Open-source projects on GitHub with releases and semantic versioned tags.

**Configuration:**

```yaml
discovery:
  strategy: api_github
  repo: "owner/repository"          # Required: GitHub repository in owner/repo format
  asset_pattern: ".*\\.exe$"        # Required: Regex pattern to match installer filename
  version_pattern: "v?([0-9.]+)"    # Optional: Regex pattern to extract version from Git tag
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
**Required:** No
**Default:** `"v?([0-9.]+)"`

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

#### prerelease

**Type:** `boolean`
**Required:** No
**Default:** `false`

Whether a release marked as a pre-release on GitHub may be selected. NAPT always
looks at the most recent release only; when it is a pre-release and this field
is `false`, discovery fails with an error rather than walking back to an older
stable release. Set to `true` for projects whose latest release is routinely a
pre-release.

### api_json strategy

**Best for:** Vendors with JSON REST APIs, cloud services with version endpoints, or APIs
requiring authentication.

**Configuration:**

```yaml
discovery:
  strategy: api_json
  api_url: "https://api.vendor.com/latest"   # Required: JSON API endpoint URL
  version_path: "version"                    # Required: JSONPath to version field
  download_url_path: "download_url"          # Required: JSONPath to download URL field
  version_pattern: "v?([0-9.]+)"             # Optional: regex to narrow the version value
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

#### version_pattern

**Type:** `string` (regex)
**Required:** No
**Default:** None (the value at `version_path` is used as is)

Regular expression applied to the value found at `version_path`. Use it when the
API wraps the version in a prefix or suffix that a device would misread: version
comparison on the device takes each part's leading digits, so `"v2.0"` reads as
version 0. For that reason `napt discover` refuses a version that does not start
with a digit, and the error names the value to capture.

**Examples:**
- `"v?([0-9.]+)"` - Extracts `2.0` from `v2.0` or `2.0`
- `"([0-9.]+)"` - Extracts `2.0` from `2.0 (stable)`

**Note:** The first capture group is used as the version string; a pattern with
no capture group uses the whole match. A pattern that does not match stops
discovery with an error.

#### headers

**Type:** `object` (key-value pairs)
**Required:** No
**Default:** None

HTTP headers to include in the API request, typically for authentication.
Values support `${VARIABLE_NAME}` substitution (see
[Variable substitution](#variable-substitution)).

**Example:**
```yaml
headers:
  Authorization: "Bearer ${API_TOKEN}"
  X-API-Key: "${VENDOR_API_KEY}"
```

### url_download strategy

**Best for:** Vendors with stable download URLs and MSI or MSIX installers, which carry their own version.

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

Downloads the file from `url`, using HTTP conditional requests (ETags) to skip
unchanged files. MSI files supply their version from the ProductVersion
property and MSIX files from their Identity, with no configuration; other file
types need a version-first strategy (api_github, api_json, web_scrape) instead.

### web_scrape strategy

**Best for:** Vendors with download pages listing installers when no direct download URL or API
is available.

**Configuration:**

```yaml
discovery:
  strategy: web_scrape
  page_url: "https://vendor.com/download"           # Required: URL of vendor download page
  link_selector: 'a[href$=".msi"]'                  # One of link_selector or link_pattern
  version_pattern: "app-(\\d+\\.\\d+)\\.msi"        # Required: Regex to extract version from URL
  version_format: "{0}"                              # Optional: Format string for captured groups
```

#### page_url

**Type:** `string` (URL)
**Required:** Yes

URL of the vendor download page that contains links to installer files.

#### link_selector

**Type:** `string` (CSS selector)
**Required:** One of `link_selector` or `link_pattern`

CSS selector to find the download link on the page. Uses standard CSS selector syntax.
Preferred over `link_pattern` when the page structure allows it.

**Examples:**
- `'a[href$=".msi"]'` - Matches links ending in `.msi`
- `'a.download-link'` - Matches links with `download-link` class
- `'#download-button'` - Matches element with `download-button` ID
- `'a[href*="installer"]'` - Matches links containing "installer"

**Note:** The selector should match exactly one link. If multiple links match, the first match
is used.

#### link_pattern

**Type:** `string` (regex)
**Required:** One of `link_selector` or `link_pattern`

Regular expression applied to the raw page HTML to find the download link when
a CSS selector cannot pin it down (for example, a URL embedded in a script
block). Must contain exactly one capture group around the link URL; the first
match is used.

**Example:**

```yaml
discovery:
  strategy: web_scrape
  page_url: "https://vendor.example.com/downloads"
  link_pattern: 'href="(/files/app-v[0-9.]+-x64\.msi)"'
  version_pattern: "app-v([0-9.]+)-x64"
```

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
- `"{0}.{1}.0"` - Pads to three parts: `"2"` + `"51"` → `"2.51.0"`

The combined result is the version, so it must still start with a digit.

## PSADT configuration

The `psadt` section defines PowerShell deployment scripts and PSADT variables:

```yaml
psadt:
  release: "latest"                      # Optional: PSADT release version
  app_vars:                              # Optional: PSADT application variables
    AppName: "Application Name"
    AppVersion: "{{discovered_version}}" # Substituted at build time
  install: |                             # Required for EXE; auto-generated for MSI/MSIX
    Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/S"
  uninstall: |                           # Required for EXE; auto-generated for MSI/MSIX
    Uninstall-ADTApplication -Name "Application Name"
```

### release

**Type:** `string`
**Required:** No
**Default:** `"latest"`

PSADT release version to use. Can be:

- `"latest"` - Use the latest PSADT release from GitHub
- Specific version: `"4.1.7"` - Use a specific PSADT version

**Note:** Typically set in organization defaults (`defaults/org.yaml`) rather than per-recipe.

### brand_pack

**Type:** `object`
**Required:** No
**Default:** None (PSADT's default assets are used)

Replaces PSADT's default dialog assets (logo, banner) with your organization's
files in every build. Set in `defaults/org.yaml` rather than per-recipe.

```yaml
psadt:
  brand_pack:
    path: brand-packs/my-company        # Folder holding your assets
    mappings:
      - source: "AppIcon.*"             # Glob, relative to path
        target: "Assets/AppIcon"        # Destination in the build, without extension
      - source: "Banner.Classic.*"
        target: "Assets/Banner.Classic"
```

- `path` is resolved relative to the directory containing `defaults/` (or the
  recipe's directory when there is none). A path that does not exist is
  skipped with a verbose log line rather than an error.
- Each mapping copies the first file matching `source` to `target`, appending
  the source file's extension. Mappings whose glob matches nothing are skipped.

### app_vars

**Type:** `object` (key-value pairs)
**Required:** No
**Default:** Merged from organization and vendor defaults

PSADT application variables set in the generated `Invoke-AppDeployToolkit.ps1` file.

**Common Variables:**

- `AppName`: Display name shown in PSADT dialogs
- `AppVersion`: Application version (use `{{discovered_version}}` for auto-substitution)
- `AppVendor`: Vendor name (typically set in vendor defaults)
- `AppLang`: Application language

NAPT sets `AppArch` itself from the installer architecture; `napt validate`
rejects it as an `app_vars` key.

Values support the build-time variables in
[Variable substitution](#variable-substitution); use `{{discovered_version}}`
in `AppVersion` so the version matches the downloaded installer.

For org-wide values such as `AppVendor`, set them once in `defaults/org.yaml`
(or a vendor file) instead of repeating them per recipe; the configuration
layers are deep-merged into every recipe.

### override_msi_commands

**Type:** `boolean`
**Required:** No
**Default:** `false`
**Applies to:** MSI installers only

When `true`, uses recipe `install` and `uninstall` scripts instead of the
auto-generated MSI commands.

**MSI auto-generation:** For MSI installers, NAPT auto-generates install and
uninstall commands from the downloaded MSI's metadata:

- **Install (`intune.run_as_account: system`, default):** `Start-ADTMsiProcess -Action Install -FilePath '{filename}' -AdditionalArgumentList "ALLUSERS=1"`
- **Install (`user`):** `Start-ADTMsiProcess -Action Install -FilePath '{filename}'`
- **Uninstall:** `Uninstall-ADTApplication -Name '{ProductName}' -NameMatch 'Exact' -ApplicationType 'MSI'`

PSADT's configuration supplies the silent-install arguments (`/qn REBOOT=ReallySuppress`)
and verbose MSI logging automatically; `-AdditionalArgumentList` appends `ALLUSERS=1`
to those defaults to force a per-machine installation.
Uninstall matches the MSI ProductName exactly (extracted at build time), not the
ProductCode, so it keeps working when vendors change the ProductCode between versions.

**Behavior:**

- `false` (default): Auto-generated commands are used; recipe `install`/`uninstall` are ignored with a warning if set
- `true`: Recipe `install` and/or `uninstall` are used; auto-generated commands fill in any that are missing
- `true` but neither `install` nor `uninstall` set: Error (nothing to override with)
- Non-MSI installers: Flag is ignored

**When to use:** Apps that need MST transforms, extra MSI properties, or uninstall
logic that differs from the standard pipeline.

**Example:**
```yaml
psadt:
  override_msi_commands: true
  install: |
    Start-ADTMsiProcess -Action Install -FilePath "{{installer_filename}}" -Transforms "custom.mst" -AdditionalArgumentList "ALLUSERS=1 DISABLE_UPDATES=1"
  uninstall: |
    Uninstall-ADTApplication -Name "Legacy App Name"
```

### override_msix_commands

**Type:** `boolean`
**Required:** No
**Default:** `false`
**Applies to:** MSIX installers only

When `true`, uses recipe `install` and `uninstall` scripts instead of the
auto-generated MSIX commands.

**MSIX auto-generation:** For MSIX installers, NAPT auto-generates install and
uninstall commands from manifest metadata.
The commands vary based on `intune.run_as_account`:

- **Install (`system`, default):** `Add-AppxProvisionedPackage -Online -PackagePath (Join-Path $adtSession.DirFiles '{filename}') -SkipLicense`
- **Uninstall (`system`, default):** `Get-AppxProvisionedPackage -Online | Where-Object { $_.DisplayName -eq '{identity_name}' } | Remove-AppxProvisionedPackage -Online`
- **Install (`user`):** `Add-AppxPackage -Path (Join-Path $adtSession.DirFiles '{filename}')`
- **Uninstall (`user`):** `Get-AppxPackage -Name '{identity_name}' | Remove-AppxPackage`

**Behavior:**

- `false` (default): Auto-generated commands are used; recipe `install`/`uninstall` are ignored with a warning if set
- `true`: Recipe `install` and/or `uninstall` are used; auto-generated commands fill in any that are missing
- `true` but neither `install` nor `uninstall` set: Error (nothing to override with)
- Non-MSIX installers: Flag is ignored

**When to use:** Apps that require a license file during provisioning or uninstall
logic that differs from the standard pipeline.

**Example:**
```yaml
psadt:
  override_msix_commands: true
  install: |
    Add-AppxProvisionedPackage -Online -PackagePath "$($adtSession.DirFiles)\app.msix" -LicensePath "$($adtSession.DirFiles)\license.xml" -SkipLicense
  uninstall: |
    Get-AppxProvisionedPackage -Online | Where-Object { $_.DisplayName -eq "Vendor.App" } | Remove-AppxProvisionedPackage -Online
```

### install

**Type:** `string` (multiline)
**Required:** Yes (EXE); auto-generated for MSI and MSIX unless overridden

PowerShell script executed during installation. Inserted into the generated
`Invoke-AppDeployToolkit.ps1` in the installation section.

Supports the same build-time variables as `app_vars` (see
[Variable substitution](#variable-substitution)); these are substituted when
the script is generated and are not PowerShell variables.

**PowerShell variables** (available at deploy time):

- `$($adtSession.DirFiles)`: Path to the installer files directory
- `$adtSession.AppName`, `$adtSession.AppVersion`, etc.: Values from `app_vars`

**Commonly Used PSADT Functions:**

- `Start-ADTProcess`: Execute EXE installers with parameters
- `Start-ADTMsiProcess`: Install MSI files with parameters
- `Uninstall-ADTApplication`: Uninstall applications by name

**Note:** PSADT resolves a relative `-FilePath` against the `Files` directory
and does not expand wildcards.
Use `{{installer_filename}}` instead of a wildcard pattern.

**Example (EXE installer):**
```yaml
install: |
  Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/S"
```

### uninstall

**Type:** `string` (multiline)
**Required:** Yes (EXE); auto-generated for MSI and MSIX unless overridden

PowerShell script executed during uninstallation. Same available variables as `install`.

**Example (EXE installer):**
```yaml
uninstall: |
  Uninstall-ADTApplication -Name "Application Name"
```

## Intune configuration

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
  device_restart_behavior: "basedOnReturnCode"        # Optional: allow, suppress, force, basedOnReturnCode
  max_run_time_minutes: 60                           # Optional: max installer runtime
  enforce_signature_check: false                     # Optional: require script signing
  run_as_32_bit: false                               # Optional: run in 32-bit context
  description: "App description for Intune portal"  # Optional: app description
  publisher: "Vendor Name"                           # Optional: publisher name override
  privacy_url: "https://vendor.com/privacy"          # Optional: privacy information URL
  info_url: "https://vendor.com"                     # Optional: information URL
  logo_path: "brand-packs/logos/app.png"             # Optional: path to app icon
  developer: "Developer Name"                        # Optional: developer field
  owner: "IT Team"                                   # Optional: business owner field
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

Controls which Intune Win32 app entries `napt upload` creates and whether
`napt build` generates the requirements script (the detection script is always
generated):

- `"both"` (default): Generate detection and requirements scripts;
  `napt upload` creates an install entry (detection only) and an update entry
  (detection + requirements)
- `"app_only"`: Generate detection script only;
  `napt upload` creates the install entry only
- `"update_only"`: Generate detection and requirements scripts;
  `napt upload` creates the update entry only

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
Older four-digit release names are also accepted (e.g., `"Windows10_1809"`).

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

**MSIX installers:** This field also controls which AppX cmdlets are
auto-generated and which package store is queried by detection and
requirements scripts:

| Value | Install cmdlet | Detection |
|-------|---------------|-----------|
| `"system"` (default) | `Add-AppxProvisionedPackage` (all users) | `Get-AppxProvisionedPackage` |
| `"user"` | `Add-AppxPackage` (current user) | `Get-AppxPackage` |

**`RequireAdmin` default:** For user-context installs, NAPT defaults
`psadt.app_vars.RequireAdmin` to `false`.
PSADT will error if `RequireAdmin` is `true` but the process is not running
as an administrator.
If your environment grants local admin to users and you want PSADT to enforce
it, set `RequireAdmin: true` explicitly in `psadt.app_vars`.

### device_restart_behavior

**Type:** `string`
**Required:** No
**Default:** `"basedOnReturnCode"`
**Allowed values:** `"allow"`, `"suppress"`, `"force"`, `"basedOnReturnCode"`

Controls how Intune handles device restarts after install:

| Value | Behavior |
|-------|----------|
| `"basedOnReturnCode"` | Restart based on the installer's return code (PSADT signals 3010/1641) |
| `"allow"` | Intune may restart the device if needed |
| `"suppress"` | Suppress any restart, even if the installer requests one |
| `"force"` | Force a restart after install completes |

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

Path to a PNG or JPEG (`.png`, `.jpg`, `.jpeg`) icon file to use as the app icon in Intune and the Company Portal.
The file must be under 700KB (Intune rejects icons over 750KB).
Relative paths are resolved from the recipe file's location.
When set in `defaults/org.yaml` (or a vendor file) and no file exists at the recipe-relative location, the path resolves from the `defaults/` directory instead, so an org-wide logo can live next to `org.yaml`.

When `logo_path` is not set, `napt build` extracts an icon from the installer into `icons/{id}.png` and `napt upload` uses that file automatically.
Setting `logo_path` always wins and disables extraction.
See [App icons](user-guide.md#app-icons) for the extraction rules.

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

### detection

The `intune.detection` subsection configures detection and requirements script generation for
Intune Win32 app deployments.

**MSI/EXE installers:** Scripts check Windows uninstall registry keys to determine
application installation state.

**MSIX installers:** Scripts use `Get-AppxPackage` to query the AppX package database by
package identity name. The `display_name`, `architecture`, and `override_msi_display_name`
fields are not used for MSIX (metadata is extracted from `AppxManifest.xml`).

```yaml
# MSI/EXE detection configuration
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

**Template Variable Support:** `{{discovered_version}}` is automatically substituted with the
discovered version. Use this when the registry DisplayName includes the version number (e.g.,
"7-Zip 25.01 (x64)").
This is the only build-time variable supported here; `{{installer_filename}}` never appears
in a registry DisplayName.

**Wildcard Support:** When `display_name` contains wildcards (`*` or `?`), scripts use
PowerShell's `-like` operator instead of exact `-eq` matching:

| Wildcard | Meaning | Example |
|----------|---------|---------|
| `*` | Matches zero or more characters | `"7-Zip *"` matches "7-Zip 24.09", "7-Zip 25.01 (x64)" |
| `?` | Matches exactly one character | `"7-Zip ??.??"` matches "7-Zip 24.09" but not "7-Zip 24.9" |

**Example with version in DisplayName:**
```yaml
intune:
  detection:
    display_name: "7-Zip {{discovered_version}} (x64)"  # Matches "7-Zip 25.01 (x64)"
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
| `x86` | 32-bit only | x86, x64, ARM64 (all Windows can run x86 via WOW64) |
| `x64` | 64-bit only | x64, ARM64 (ARM64 Windows 11 supports x64 emulation) |
| `arm64` | 64-bit only | ARM64 only (native binary) |
| `any` | All views | x86, x64, ARM64 (permissive) |

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

When `true`, uses the `display_name` field instead of the MSI
`ProductName` for detection scripts.

**When to use:** When the MSI ProductName contains a version
number that changes with each release (e.g., "7-Zip 25.01").

**Behavior:**

- `false` (default): Uses MSI ProductName (authoritative source)
- `true`: Uses `display_name` field (must be set)
- Non-MSI installers: Flag is ignored (a warning is logged if set)

**Example:**
```yaml
intune:
  detection:
    display_name: "7-Zip * (x64 edition)"
    override_msi_display_name: true
```

See [Detection and requirements scripts](user-guide.md#detection-and-requirements-scripts)
in the User Guide for how the generated scripts work and where they are stored.

## IntuneWinAppUtil configuration

The `intunewin` section controls the Microsoft packaging tool `napt package`
uses. Set in `defaults/org.yaml`; it is not a per-recipe setting.

```yaml
intunewin:
  release: "latest"   # Optional: IntuneWinAppUtil.exe release
```

### release

**Type:** `string`
**Required:** No
**Default:** `"latest"`

Which `IntuneWinAppUtil.exe` release to download and run. Can be:

- `"latest"` - Use the latest release from Microsoft's GitHub repository
- Specific version: `"1.8.6"` - Pin to a known-good release for reproducible packaging

Each release is cached independently under `cache/tools/{version}/`, so changing
the pin never overwrites a previously downloaded tool.

## Logging configuration

The `logging` section controls on-device logging for detection and requirements scripts.
Logs are written in CMTrace format (compatible with the Configuration Manager Trace Log
Tool).

```yaml
logging:
  log_rotation_mb: 3      # Optional: max log file size in MB
```

This setting is typically configured in `defaults/org.yaml` rather than per-recipe.

### log_rotation_mb

**Type:** `integer`
**Required:** No
**Default:** `3`

Maximum log file size in megabytes before rotation. Scripts use a 2-file rotation scheme
(`.log` and `.log.old`).
Log file locations are described in
[Detection and requirements scripts](user-guide.md#detection-and-requirements-scripts).

## Deployment configuration

The `deployment` section controls upload strictness and deployment promotion.
These settings are org policy: configure them in `defaults/org.yaml` and
override per-recipe only when an app needs different treatment.

```yaml
deployment:
  require_pending: false        # Optional: require a recorded pending release
  rings:                        # Optional: rings for update promotion
    - name: "pilot"
      groups: ["sg-intune-pilot"]
      promote_after_days: 2
    - name: "production"
      groups: ["sg-intune-all-workstations"]
  install:                      # Optional: install entry assignment
    intent: "available"
    groups: ["All Users"]
  retain_versions: 1            # Optional: superseded versions kept for rollback
```

Groups may be Entra ID display names or object IDs.
Display names are resolved via the Graph API, which requires the
`Group.Read.All` application permission (see
[App Registration Setup](user-guide.md#app-registration-setup)).

Two names are reserved for Intune's built-in targets: `"All Users"` and
`"All Devices"` assign the corresponding virtual group instead of looking
up an Entra ID group.
The reserved names always win: a real Entra ID group that shares one of
these display names must be referenced by its object ID.

### require_pending

**Type:** `boolean`
**Required:** No
**Default:** `false`

When enabled, `napt upload` fails if the app's deployment state has no
pending release matching the package (nothing reaches Intune without a
recorded release).
Enable this when publishes are gated through review of committed deployment
state.
For a manual upload under this policy, run `napt discover` first or add a
pending entry (version, sha256, url) to the app's deployment state file.

### rings

**Type:** `list`
**Required:** No
**Default:** `[]`

Ordered deployment rings for update promotion.
Each ring requires a unique `name` and a non-empty `groups` list;
`promote_after_days` (optional) sets how many days a version holds the ring
before becoming eligible for the next one.

Rings are evaluated by `napt promote plan` and executed by
`napt promote apply` (ring groups are assigned to the `[Update]` entry as
required installs).

### install

**Type:** `dict`
**Required:** No
**Default:** `intent: "available"`, `groups: []`

Assignment for the install entry (net-new installs).
`intent` is `"available"` (Company Portal) or `"required"`.
No install assignment happens unless groups are configured; a common
org-wide choice is `groups: ["All Users"]` for Company Portal
self-service.
The assignment is planned by `napt promote plan` and executed once per
release by `napt promote apply`.
The cutover happens with the release's first promotion: the same plan
that starts a release's rollout in the first ring also points new
installs at it, so net-new devices receive the release before it has
baked through the rings.

### retain_versions

**Type:** `integer`
**Required:** No
**Default:** `1`

How many superseded versions stay in Intune for rollback before deletion.
`0` deletes a version as soon as it holds no rings.
Enforced by `napt promote apply`; only NAPT-stamped apps are ever deleted.

## Variable substitution

Recipes use two distinct substitution mechanisms with different syntax.

### NAPT build-time variables: `{{...}}`

NAPT substitutes these while generating the package (they are not PowerShell
variables):

| Variable | Value | Supported fields |
|----------|-------|------------------|
| `{{discovered_version}}` | The release's version: the installer's own for MSI and MSIX, the strategy's for EXE (see [The installer's version is the version](user-guide.md#the-installers-version-is-the-version)) | `psadt.app_vars`, `psadt.install`, `psadt.uninstall`, `intune.detection.display_name` |
| `{{installer_filename}}` | Exact filename of the downloaded installer | `psadt.app_vars`, `psadt.install`, `psadt.uninstall` |

`napt build` logs a warning if an `app_vars` value or an install/uninstall
script contains a `{{snake_case}}` token that is not a supported variable.

### Environment variables: `${VARIABLE_NAME}`

Environment variable substitution exists for secrets that must not be committed
to YAML.
It works **only** in `discovery.token` and `discovery.headers`.

For non-secret org-wide values (e.g., `AppVendor`), use the configuration layers
(`defaults/org.yaml`, `defaults/vendors/{Vendor}.yaml`) instead.

### Syntax

```yaml
discovery:
  token: "${GITHUB_TOKEN}"               # Environment variable (secrets only)
  headers:
    Authorization: "Bearer ${API_TOKEN}" # Environment variable (secrets only)

psadt:
  app_vars:
    AppVersion: "{{discovered_version}}" # NAPT build-time substitution
  install: |
    Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/S"
```

For setting the variables locally and in CI/CD, see
[Handle authentication tokens](common-tasks.md#handle-authentication-tokens).

## Complete example

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
    AppVersion: "{{discovered_version}}"
  install: |
    Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/S"
  uninstall: |
    Uninstall-ADTApplication -Name "Example Application"
```

## See also

- [Common Tasks](common-tasks.md) - Practical workflows and examples
- [Discovery Strategies](user-guide.md#discovery-strategies) - Strategy selection guide
- [User Guide](user-guide.md) - Complete user documentation
- [PSADT Reference](https://psappdeploytoolkit.com/) - Complete PSADT function reference
