# Recipe reference

Field definitions for recipes and for `defaults/org.yaml` and vendor files,
which share the schema.

> **Tip:** For copy-paste workflows, see [Common tasks](common-tasks.md).
> For choosing a strategy, see
> [Discovery strategies](user-guide.md#discovery-strategies).

`napt validate` checks the recipe and its parent.
Values from `defaults/` are checked when any other command loads the recipe.
`napt validate` type-checks the `intune`, `logging`, and `deployment` sections,
`psadt.app_vars`, the `psadt.override_*` flags, and each strategy's required
fields and patterns, and warns on unknown keys in `intune`, `logging`, and
`deployment`.
Other keys are accepted as written: a wrong type in, for example,
`prerelease`, `token`, `brand_pack`, or `install` surfaces only when a command
uses the value.

## Top-level fields

```yaml
apiVersion: napt/v1          # Required: recipe format version
name: "Application Name"     # Required: display name
id: "napt-app-id"            # Required: identifier and folder name
discovery:                   # Required: how to find and download the installer
  strategy: api_github
  repo: "owner/repository"
  asset_pattern: ".*-x64\\.exe$"
psadt:                       # EXE needs install and uninstall
  install: |
    Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/S"
  uninstall: |
    Uninstall-ADTApplication -Name "Application Name"
intune:                      # Optional: Intune settings
  detection:                 # EXE needs display_name and architecture
    display_name: "Application Name"
    architecture: "x64"
logging:                     # Optional: on-device script logging
  log_rotation_mb: 3
```

A section key with nothing under it is a validation error; remove the key
instead.
`parent`, `directories`, `intunewin`, and `deployment` are the other top-level
keys; each has its own section below.

### apiVersion

**Type:** `string`
**Required:** Yes
**Values:** `napt/v1` (the only version so far)

Any other value is a validation warning.

### name

**Type:** `string`
**Required:** Yes

Display name of the Intune app entries (the update entry adds
[`update_name_prefix`](#update_name_prefix)) and the name recorded in
deployment state.
PSADT dialogs show `psadt.app_vars.AppName`, which is not filled from `name`.

### id

**Type:** `string`
**Required:** Yes
**Convention:** Lowercase, alphanumeric, hyphens (e.g., `napt-chrome`,
`napt-git`)

Names the app's folders, so it must work as a folder name as-is: letters,
digits, `.`, `-`, `_`, and `+`, starting with a letter or digit.
`napt validate` rejects anything else, including path separators and `..`.
Two recipe files with the same `id` stop `napt promote`.
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

Keep the parent outside the recipe directory that commands scan (for
example, `recipe-bases/` next to `recipes/`):
NAPT would otherwise load it as a recipe of its own.
Set `name` and `id` in the child, since they identify the app in Intune and
in NAPT's state, and two files with one `id` stop `napt promote`.

**Example (in `recipes/Google/chrome.override.yaml`):**
```yaml
parent: ../../recipe-bases/chromium-family.yaml
```

Name a recipe that declares `parent` as `<app>.override.yaml` so the
relationship shows in every listing.
`napt validate` warns when the field and the file name disagree in either
direction, and reports the parent it merged.

Relative paths a parent sets, such as `intune.logo_path`, resolve against
this file's directory, not the parent's.
See [Configuration layers](user-guide.md#configuration-layers) for where the
parent sits in the merge order and how lists merge, and
[Share a base recipe between apps](common-tasks.md#share-a-base-recipe-between-apps)
for the steps.

## Discovery configuration

`discovery` tells NAPT where to find the installer.
Its other fields depend on `strategy`.

- `strategy` (required): `api_github`, `api_json`, `url_download`, or
  `web_scrape`.

**Why `version_pattern` differs by strategy:**

- `web_scrape`: required; the version is inside a link URL.
- `api_github`: defaults to `v?([0-9.]+)`, since tags usually carry a `v`.
- `api_json`: off unless set; use it when the API wraps the value.
- `url_download`: none; the version comes from the installer, and a
  `version_pattern` set here is ignored.

For an EXE, the captured value is the version; see
[Discovery process](user-guide.md#discovery-process-napt-discover) for the
rules it must meet.
For an MSI or MSIX, the installer's own version is recorded instead.

### api_github strategy

**Configuration:**

```yaml
discovery:
  strategy: api_github
  repo: "owner/repository"          # Required: GitHub repository
  asset_pattern: ".*\\.exe$"        # Required: regex for the installer filename
  version_pattern: "v?([0-9.]+)"    # Optional: regex for the version in the tag
  token: "${GITHUB_TOKEN}"          # Optional: GitHub personal access token
  prerelease: false                 # Optional: currently has no effect
```

#### repo

**Type:** `string`
**Required:** Yes
**Format:** `owner/repository` (e.g., `git-for-windows/git`)

#### asset_pattern

**Type:** `string` (regex)
**Required:** Yes

Regex searched in each release asset's filename; the first match is
downloaded.
Matching is case-sensitive; prefix `(?i)` to ignore case.

**Examples:**
- `"Git-.*-64-bit\\.exe$"` - Matches Git installers for 64-bit
- `".*\\.msi$"` - Matches any MSI file
- `"app-.*-x64\\.exe$"` - Matches app installers for x64

**Note:** Escape special regex characters (e.g., `\\.` for literal dot).

#### version_pattern

**Type:** `string` (regex)
**Required:** No
**Default:** `"v?([0-9.]+)"`

Regex searched in the release's Git tag to extract the version.

**Examples:**
- `"v?([0-9.]+)"` - Extracts version from tags like `v2.51.2` or `2.51.2`
- `"release-([0-9]+\\.[0-9]+)"` - Extracts version from tags like `release-1.5`

**Note:** The first capture group is used as the version string; a pattern with
no capture group uses the whole match.
A pattern that does not match stops discovery with an error.

#### token

**Type:** `string`
**Required:** No
**Default:** None

GitHub personal access token for authenticated API requests.
Write it as `"${GITHUB_TOKEN}"` so the token stays out of the file (see
[Environment variables](#environment-variables-variable_name)).
An unset variable is not an error: the request is sent unauthenticated, so a
missing secret shows up only as a rate-limit error.

**When to use:**

- Avoid GitHub API rate limits (60 requests/hour unauthenticated, 5000/hour
  authenticated)
- Access private repositories

#### prerelease

**Type:** `boolean`
**Required:** No
**Default:** `false`

Currently has no effect.
NAPT reads GitHub's latest-release endpoint, which never returns a
pre-release, so `true` never selects one and `false` never raises an error.

### api_json strategy

**Configuration:**

```yaml
discovery:
  strategy: api_json
  api_url: "https://api.vendor.com/latest"   # Required: JSON API endpoint URL
  version_path: "version"                    # Required: JSONPath to version field
  download_url_path: "download_url"          # Required: JSONPath to download URL field
  version_pattern: "v?([0-9.]+)"             # Optional: regex to narrow the version value
  headers:                                   # Optional: HTTP headers for authentication
    Authorization: "${API_AUTH_HEADER}"      # Variable holds "Bearer <token>"
```

#### api_url

**Type:** `string` (URL)
**Required:** Yes

JSON API endpoint URL that returns version and download URL information.

#### version_path

**Type:** `string` (JSONPath)
**Required:** Yes

JSONPath expression to extract the version field from the API response.
Supports nested paths.

**Examples:**
- `"version"` - Direct field: `{"version": "1.2.3"}`
- `"data.version"` - Nested field: `{"data": {"version": "1.2.3"}}`
- `"release.latest.version"` - Deeply nested:
  `{"release": {"latest": {"version": "1.2.3"}}}`

#### download_url_path

**Type:** `string` (JSONPath)
**Required:** Yes

JSONPath expression to extract the download URL field from the API response.
Supports nested paths (same format as `version_path`).

#### version_pattern

**Type:** `string` (regex)
**Required:** No
**Default:** None (the value at `version_path` is used as is)

Regex applied to the value found at `version_path`.
Use it when the API wraps the version (`v2.0`, `2.0 (stable)`).

**Examples:**
- `"v?([0-9.]+)"` - Extracts `2.0` from `v2.0` or `2.0`
- `"([0-9.]+)"` - Extracts `2.0` from `2.0 (stable)`

**Note:** The first capture group is used as the version string; a pattern with
no capture group uses the whole match.
A pattern that does not match stops discovery with an error.

#### headers

**Type:** `object` (key-value pairs)
**Required:** No
**Default:** None

HTTP headers to include in the API request, typically for authentication.
A value that is exactly `${VARIABLE_NAME}` is replaced from the environment;
`Bearer ${TOKEN}` is sent as written, so put the whole header value in the
variable (see [Environment variables](#environment-variables-variable_name)).

**Example (fragment of `discovery`):**
```yaml
headers:
  Authorization: "${API_AUTH_HEADER}"   # Variable holds "Bearer <token>"
  X-API-Key: "${VENDOR_API_KEY}"
```

### url_download strategy

**Configuration:**

```yaml
discovery:
  strategy: url_download
  url: "https://vendor.com/installer.msi"   # Required: Stable download URL
```

#### url

**Type:** `string` (URL)
**Required:** Yes

Stable download URL for the installer.
It must not change between versions; if it does, use `web_scrape`.

The version is read from the file: MSI ProductVersion or MSIX Identity.
Other file types need `api_github`, `api_json`, or `web_scrape`.
How unchanged files are skipped:
[Skipping downloads](user-guide.md#skipping-downloads).

### web_scrape strategy

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

CSS selector to find the download link on the page.
Prefer it over `link_pattern` when the page's markup allows.
If both are set, `link_selector` is used and `link_pattern` is ignored.

**Examples:**
- `'a[href$=".msi"]'` - Matches links ending in `.msi`
- `'a.download-link'` - Matches links with `download-link` class
- `'#download-button'` - Matches element with `download-button` ID
- `'a[href*="installer"]'` - Matches links containing "installer"

**Note:** The selector should match exactly one link.
If multiple links match, the first match is used.

#### link_pattern

**Type:** `string` (regex)
**Required:** One of `link_selector` or `link_pattern`

Regular expression applied to the raw page HTML to find the download link when
a CSS selector cannot pin it down (for example, a URL embedded in a script
block).
The first capture group is the link; with no group, the whole match is.
The first match on the page is used.

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

Regex that extracts the version from the discovered download URL.
Capture groups feed `version_format`; with none, the whole match is the
version.

**Examples:**
- `"app-(\\d+\\.\\d+)\\.msi"` - Extracts `1.5` from `app-1.5.msi`
- `"7z(\\d{2})(\\d{2})-x64"` - Captures year and month from `7z2501-x64.msi`
  (groups: `25`, `01`)
- `"v([0-9.]+)"` - Extracts version from `v2.51.2` (captures `2.51.2`)

#### version_format

**Type:** `string` (format string)
**Required:** No
**Default:** Use first capture group as-is

Format string to combine multiple capture groups from `version_pattern`.
Uses Python format string syntax with `{0}`, `{1}`, etc. for capture groups.

**Examples:**
- `"{0}.{1}"` - Combines two groups: `"25"` + `"01"` → `"25.01"`
- `"{1}.{0}"` - Reverses order: `"01"` + `"25"` → `"01.25"`
- `"{0}.{1}.0"` - Pads to three parts: `"2"` + `"51"` → `"2.51.0"`

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

**Note:** Typically set in organization defaults (`defaults/org.yaml`) rather
than per-recipe.

### cache_dir

**Type:** `string` (path)
**Required:** No
**Default:** `"cache/psadt"`

Folder where `napt build` keeps downloaded PSADT releases.
Relative to the working directory, not the recipe.
Usually set in `defaults/org.yaml`.

### brand_pack

**Type:** `object`
**Required:** No
**Default:** None (PSADT's default assets are used)

Replaces PSADT's default dialog assets (logo, banner) with your organization's
files in every build.
Set in `defaults/org.yaml` rather than per-recipe.

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

- `path` is resolved relative to the `defaults/` directory (next to
  `org.yaml`), or the recipe's directory when there is no `defaults/org.yaml`.
  A path that does not exist is skipped with a verbose log line rather than
  an error.
- Each mapping copies the first file matching `source` to `target`, appending
  the source file's extension.
  Mappings whose glob matches nothing are skipped.

### app_vars

**Type:** `object` (key-value pairs)
**Required:** No
**Default:** Per key, below; merged from organization, vendor, and parent
layers

PSADT application variables set in the generated `Invoke-AppDeployToolkit.ps1`
file.
Only these keys are allowed; any other key is a validation error:

| Key | Default |
|-----|---------|
| `AppVendor` | None |
| `AppName` | None (see [`name`](#name)) |
| `AppVersion` | None (use `"{{discovered_version}}"`) |
| `AppLang` | `"EN"` |
| `AppRevision` | `"01"` |
| `AppSuccessExitCodes` | `[0]` |
| `AppRebootExitCodes` | `[1641, 3010]` |
| `AppProcessesToClose` | `[]` |
| `AppScriptVersion` | `"1.0.0"` |
| `AppScriptDate` | Today's date (`YYYY-MM-DD`) |
| `AppScriptAuthor` | `"napt"` |
| `RequireAdmin` | Computed from [`run_as_account`](#run_as_account) unless a configuration layer sets it |
| `InstallName` | None |
| `InstallTitle` | None |

NAPT sets `AppArch` itself from the installer architecture, so it is not in
the list.

String values support the build-time variables in
[Variable substitution](#variable-substitution); use `{{discovered_version}}`
in `AppVersion` so the version matches the downloaded installer.

Set shared values such as `AppVendor` in `defaults/org.yaml` or a vendor file
([Configuration layers](user-guide.md#configuration-layers)).

### override_msi_commands

**Type:** `boolean`
**Required:** No
**Default:** `false`
**Applies to:** MSI installers only

When `true`, uses recipe `install` and `uninstall` scripts instead of the
auto-generated MSI commands.

**Generated commands:**

- **Install (`intune.run_as_account: system`, default):**
  `Start-ADTMsiProcess -Action Install -FilePath '{filename}' -AdditionalArgumentList "ALLUSERS=1"`
- **Install (`user`):**
  `Start-ADTMsiProcess -Action Install -FilePath '{filename}'`
- **Uninstall:**
  `Uninstall-ADTApplication -Name '{ProductName}' -NameMatch 'Exact' -ApplicationType 'MSI'`

PSADT adds its default MSI arguments (`/qn REBOOT=ReallySuppress`) and
logging; `ALLUSERS=1` is appended to force a per-machine install.
Uninstall matches the MSI ProductName exactly (extracted at build time), not
the ProductCode, so it keeps working when vendors change the ProductCode
between versions.

**Behavior:**

- `false` (default): Auto-generated commands are used; recipe
  `install`/`uninstall` are ignored with a warning if set
- `true`: Recipe `install` and/or `uninstall` are used; auto-generated
  commands fill in any that are missing
- `true` but neither `install` nor `uninstall` set: Error (nothing to
  override with)
- Non-MSI installers: Flag is ignored

**When to use:** Apps that need MST transforms, extra MSI properties, or
uninstall logic that differs from the standard pipeline.

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

**Generated commands**, from the manifest, by `intune.run_as_account`:

- **Install (`system`, default):**
  `Add-AppxProvisionedPackage -Online -PackagePath (Join-Path $adtSession.DirFiles '{filename}') -SkipLicense`
- **Uninstall (`system`, default):**
  `Get-AppxProvisionedPackage -Online | Where-Object { $_.DisplayName -eq '{identity_name}' } | Remove-AppxProvisionedPackage -Online`
- **Install (`user`):**
  `Add-AppxPackage -Path (Join-Path $adtSession.DirFiles '{filename}')`
- **Uninstall (`user`):**
  `Get-AppxPackage -Name '{identity_name}' | Remove-AppxPackage`

**Behavior:**

- `false` (default): Auto-generated commands are used; recipe
  `install`/`uninstall` are ignored with a warning if set
- `true`: Recipe `install` and/or `uninstall` are used; auto-generated
  commands fill in any that are missing
- `true` but neither `install` nor `uninstall` set: Error (nothing to
  override with)
- Non-MSIX installers: Flag is ignored

**When to use:** Apps that require a license file during provisioning or
uninstall logic that differs from the standard pipeline.

**Example:**
```yaml
psadt:
  override_msix_commands: true
  install: |
    Add-AppxProvisionedPackage -Online -PackagePath (Join-Path $adtSession.DirFiles "{{installer_filename}}") -LicensePath "$($adtSession.DirFiles)\license.xml"
  uninstall: |
    Get-AppxProvisionedPackage -Online | Where-Object { $_.DisplayName -eq "Vendor.App" } | Remove-AppxProvisionedPackage -Online
```

### install

**Type:** `string` (multiline)
**Required:** For EXE installers (checked by `napt build`, not
`napt validate`); auto-generated for MSI and MSIX unless overridden

PowerShell script executed during installation.
Inserted into the generated `Invoke-AppDeployToolkit.ps1` in the installation
section.

Supports the same build-time variables as `app_vars` (see
[Variable substitution](#variable-substitution)); these are substituted when
the script is generated and are not PowerShell variables.

**PowerShell variables** (available at deploy time):

- `$($adtSession.DirFiles)`: Path to the installer files directory
- `$adtSession.AppName`, `$adtSession.AppVersion`, etc.: Values from `app_vars`

**Note:** PSADT resolves a relative `-FilePath` against the `Files` directory
and does not expand wildcards.
Use `{{installer_filename}}` instead of a wildcard pattern.

**Example (EXE installer, fragment of `psadt`):**
```yaml
install: |
  Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/S"
```

### uninstall

**Type:** `string` (multiline)
**Required:** For EXE installers (checked by `napt build`, not
`napt validate`); auto-generated for MSI and MSIX unless overridden

PowerShell script executed during uninstallation.
Same available variables as `install`.

**Example (EXE installer, fragment of `psadt`):**
```yaml
uninstall: |
  Uninstall-ADTApplication -Name "Application Name"
```

## Intune configuration

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

Prefix added to the app name for the Update app entry in Intune.
The Update app display name is `update_name_prefix + name`.

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

Minimum Windows 10/11 feature update required to install the app, enforced
during Intune assignment.
Format: `"Windows10_<release>"` or `"Windows11_<release>"` where release is
the feature update name (e.g., `"Windows10_21H2"`, `"Windows10_22H2"`,
`"Windows11_23H2"`).
Older four-digit release names are also accepted (e.g., `"Windows10_1809"`).

### install_command

**Type:** `string`
**Required:** No
**Default:** `"Invoke-AppDeployToolkit.exe -DeploymentType Install -DeployMode Silent"`

Command line used by Intune to install the app.
Rarely needs changing unless you need custom PSADT deployment parameters.

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

When `true`, the "Uninstall" action is available in the Company Portal for
Available assignments.
Set to `false` to prevent self-service uninstall for this app.

### run_as_account

**Type:** `string`
**Required:** No
**Default:** `"system"`
**Allowed values:** `"system"`, `"user"`

Execution account for the installer and the requirements script.
Use `"system"` for most enterprise deployments.
Use `"user"` for apps that must be installed in the user's profile context.

**MSIX installers:** This field also controls which AppX cmdlets are
auto-generated and which package store the detection and requirements
scripts query:

| Value | Install cmdlet | Detection |
|-------|---------------|-----------|
| `"system"` (default) | `Add-AppxProvisionedPackage` (all users) | `Get-AppxProvisionedPackage` |
| `"user"` | `Add-AppxPackage` (current user) | `Get-AppxPackage` |

**`RequireAdmin` default:** NAPT sets `psadt.app_vars.RequireAdmin` to
`false` for `user` and `true` for `system`, but only when no configuration
layer (org, vendor, parent, or recipe) sets `RequireAdmin`.
PSADT will error if `RequireAdmin` is `true` but the process is not running
as an administrator.
Do not set it in `defaults/org.yaml` if any app runs as `user`.
If your environment grants local admin to users and you want PSADT to enforce
it, set `RequireAdmin: true` explicitly in that recipe's `psadt.app_vars`.

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
Leave as `false` unless your organization enforces PowerShell script signing
policy.

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
**Default:** The name of the folder that contains the recipe file (e.g.,
`recipes/Google/chrome.yaml` → `"Google"`)

Publisher name shown in Intune and the Company Portal.
Override when the folder name doesn't match the official publisher name.

### privacy_url

**Type:** `string` (URL)
**Required:** No
**Default:** None

Link to the vendor's privacy policy.
Shown in the Intune portal.

### info_url

**Type:** `string` (URL)
**Required:** No
**Default:** None

Link to more information about the app.
Shown in the Intune portal.

### logo_path

**Type:** `string` (path)
**Required:** No
**Default:** None

Path to a PNG or JPEG (`.png`, `.jpg`, `.jpeg`) icon file to use as the app
icon in Intune and the Company Portal.
The file must be under 700KB (Intune rejects icons over 750KB).
Relative paths are resolved from the recipe file's location.
Set in `defaults/org.yaml` or a vendor file, the path falls back to
`defaults/` when no file exists next to the recipe.

When `logo_path` is not set, `napt build` extracts an icon from the installer
into `icons/{id}.png` and `napt upload` uses that file automatically.
Setting `logo_path` always wins and disables extraction.
See [App icons](user-guide.md#app-icons) for the extraction rules.

### developer

**Type:** `string`
**Required:** No
**Default:** None

Developer or maintainer name.
Shown in the Intune portal's app details.

### owner

**Type:** `string`
**Required:** No
**Default:** None

Business owner of the application.
Shown in the Intune portal's app details.

### detection

These fields apply to MSI and EXE installers; MSIX takes its name and
architecture from its manifest.
How the scripts work:
[Detection and requirements scripts](user-guide.md#detection-and-requirements-scripts).

```yaml
intune:
  detection:
    display_name: "Application Name"
    architecture: "x64"
    exact_match: false
    override_msi_display_name: false
```

#### display_name

**Type:** `string`
**Required:** For EXE installers (checked by `napt build`, not
`napt validate`); ignored for MSI unless `override_msi_display_name` is set,
and for MSIX (a warning is logged if set)

Application name used in scripts to match registry `DisplayName`.
For MSI, the MSI `ProductName` is used instead, since it is what the registry
shows.
This value is also used in generated script filenames.

**Note:** The value is sanitized for use in Windows filenames (spaces become
hyphens, invalid characters removed).
Script filenames follow the pattern `{DisplayName}_{Version}-Detection.ps1`
and `{DisplayName}_{Version}-Requirements.ps1`.

**Build-time variables:** `{{discovered_version}}` is replaced with the
release's version.
Use this when the registry DisplayName includes the version number (e.g.,
"7-Zip 25.01 (x64)").
This is the only build-time variable supported here; `{{installer_filename}}`
never appears in a registry DisplayName.

**Wildcards:** When `display_name` contains wildcards (`*` or `?`), scripts
use PowerShell's `-like` operator instead of exact `-eq` matching:

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

For a wildcard example, see
[`override_msi_display_name`](#override_msi_display_name).

#### architecture

**Type:** `string`
**Required:** For EXE installers (checked by `napt build`, not
`napt validate`); ignored for MSI and MSIX (a warning is logged if set)
**Allowed values:** `x86`, `x64`, `arm64`, `any`

Specifies the installer's binary architecture.
Controls which registry views detection and requirements scripts check, and
which device architectures the app is offered to in Intune.
For MSI, it is read from the MSI Summary Information `Template` property; for
MSIX, from the manifest.

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

If `true`, the detection script requires an exact version match.
If `false`, detection passes if the installed version is greater than or equal
to the required version.

- `exact_match: false` (default): Allows users to have newer versions without
  triggering reinstall
- `exact_match: true`: Requires exact version match (useful for compliance
  scenarios)

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

**Example (wildcard):**
```yaml
intune:
  detection:
    display_name: "7-Zip * (x64 edition)"  # Matches any 7-Zip x64 version
    override_msi_display_name: true
```

## IntuneWinAppUtil configuration

The `intunewin` section controls the Microsoft packaging tool `napt package`
uses.
Usually set in `defaults/org.yaml`.

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
- Specific version: `"1.8.6"` - Pin to a known-good release for reproducible
  packaging

Each release is cached independently under `cache/tools/{version}/`, so
changing the pin never overwrites a previously downloaded tool.

## Logging configuration

The `logging` section controls on-device logging for detection and
requirements scripts.
Usually set in `defaults/org.yaml`.

```yaml
logging:
  log_rotation_mb: 3      # Optional: max log file size in MB
```

### log_rotation_mb

**Type:** `integer`
**Required:** No
**Default:** `3`

Maximum log file size in megabytes before rotation.
Scripts use a 2-file rotation scheme (`.log` and `.log.old`).
Log format and locations are described in
[Detection and requirements scripts](user-guide.md#detection-and-requirements-scripts).

## Directories configuration

The `directories` section sets where commands read and write their files.
It is org policy: set it in `defaults/org.yaml`.
Paths are relative to the working directory.
Command-line flags override these values for one run (see
[Directory flag defaults](user-guide.md#directory-flag-defaults)); `napt upload`
has no directory flags and reads its locations from this section only.

```yaml
directories:
  discover: "downloads"
  build: "builds"
  package: "packages"
  icons: "icons"
  state: "state"
```

| Key | Default | Holds |
|-----|---------|-------|
| `discover` | `"downloads"` | Installers written by `napt discover`, read by `napt build` |
| `build` | `"builds"` | Builds written by `napt build`, read by `napt package` |
| `package` | `"packages"` | Packages written by `napt package`, read by `napt upload` |
| `icons` | `"icons"` | Icons extracted by `napt build`, read by `napt upload` |
| `state` | `"state"` | Deployment state and promotion plan files |

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

A recorded pending release must always match the package, whether or not
this is set.
When enabled, `napt upload` also fails when no pending release is recorded,
so nothing reaches Intune without a recorded release.
Enable this when publishes are gated through review of committed deployment
state.

For a manual upload under this policy, run `napt discover` first.
Republishing an already-published binary (for example, to
[fix a broken published app](common-tasks.md#fix-a-broken-published-app))
has no pending release; add a `pending` entry to the app's deployment state
file by hand, with the published release's `version`, `sha256`, and `url`.

### rings

**Type:** `list`
**Required:** No
**Default:** `[]`

Ordered deployment rings for update promotion.
Each ring requires a unique `name` and a non-empty `groups` list;
`promote_after_days` (optional) sets how many days a version holds the ring
before becoming eligible for the next one.
Without it the ring is a manual gate: releases hold it until you change the
configuration.
Leave it off the last ring.

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
New installs move to a release in the same plan that puts it in the first
ring, before it has baked through the rings.

### retain_versions

**Type:** `integer`
**Required:** No
**Default:** `1`

How many superseded versions stay in Intune for rollback before deletion.
`0` deletes a version as soon as it holds no rings.
Enforced by `napt promote apply`; only NAPT-stamped apps are ever deleted.

## Variable substitution

### NAPT build-time variables: `{{...}}`

NAPT substitutes these while generating the package (they are not PowerShell
variables):

| Variable | Value | Supported fields |
|----------|-------|------------------|
| `{{discovered_version}}` | The release's version: the installer's own for MSI and MSIX, the strategy's for EXE (see [The installer's version is the version](user-guide.md#the-installers-version-is-the-version)) | `psadt.app_vars` (string values), `psadt.install`, `psadt.uninstall`, `intune.detection.display_name` |
| `{{installer_filename}}` | Exact filename of the downloaded installer | `psadt.app_vars` (string values), `psadt.install`, `psadt.uninstall` |

`napt build` logs a warning if an `app_vars` value or an install/uninstall
script contains a `{{snake_case}}` token that is not a supported variable.

### Environment variables: `${VARIABLE_NAME}`

Environment variable substitution exists for secrets that must not be
committed to YAML.
It works **only** in `discovery.token` (`api_github`) and the values of
`discovery.headers` (`api_json`).

Only a whole value that is exactly `${VARIABLE_NAME}` is replaced; text around
it is sent as written, so `"Bearer ${API_TOKEN}"` reaches the server
literally.
For a bearer token, put the whole header value in the variable:

```yaml
discovery:
  strategy: api_json
  api_url: "https://api.vendor.com/latest"
  version_path: "version"
  download_url_path: "download_url"
  headers:
    Authorization: "${API_AUTH_HEADER}"   # API_AUTH_HEADER="Bearer <token>"
```

An unset variable is not an error, and is logged only at verbose level: the
header is dropped, or the `token` request goes out unauthenticated.

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

- [PSADT reference](https://psappdeploytoolkit.com/): PSADT functions used in
  `install` and `uninstall`
