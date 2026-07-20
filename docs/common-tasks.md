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
apiVersion: napt/v1

name: "Git for Windows"
id: "napt-git"

discovery:
  strategy: api_github
  repo: "git-for-windows/git"
  asset_pattern: "Git-.*-64-bit\\.exe$"
  version_pattern: "v?([0-9.]+)\\.windows"

intune:
  detection:
    display_name: "Git"
    architecture: "x64"

psadt:
  app_vars:
    AppName: "Git for Windows"
    AppVersion: "{{discovered_version}}"
  install: |
    Start-ADTProcess -FilePath "Git-{{discovered_version}}-64-bit.exe" -ArgumentList "/VERYSILENT /NORESTART"
  uninstall: |
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
# recipes/7-Zip/7zip-x64-msi.yaml
apiVersion: napt/v1

name: "7-Zip (x64) MSI"
id: "napt-7zip-x64-msi"

discovery:
  strategy: web_scrape
  page_url: "https://www.7-zip.org/download.html"
  link_selector: 'a[href$="-x64.msi"]'
  version_pattern: "7z(\\d{2})(\\d{2})-x64"
  version_format: "{0}.{1}"

intune:
  detection:
    display_name: "7-Zip * (x64 edition)"  # Wildcard matches any 7-Zip x64 version
    override_msi_display_name: true         # Override MSI ProductName which includes version

psadt:
  app_vars:
    AppName: "7-Zip"
    AppVersion: "{{discovered_version}}"
```

**Install/uninstall commands are auto-generated for MSI:**

- **No `psadt.install` / `psadt.uninstall` needed** - NAPT generates
  `Start-ADTMsiProcess -Action Install` with the exact downloaded filename
  (plus `ALLUSERS=1` for system deployments) and
  `Uninstall-ADTApplication` matching the MSI's ProductName exactly
- **Uninstall survives ProductCode changes** - Matching is by name, not
  ProductCode, and the name is re-extracted from each downloaded MSI
- **Custom commands** - Set `psadt.override_msi_commands: true` and provide
  your own `install`/`uninstall` (e.g., for MST transforms or extra MSI
  properties)

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
- `intune.detection`: Configure when vendor includes version in DisplayName (e.g., "7-Zip 25.01")
  - `display_name`: Pattern with wildcards to match the installed app name
  - `override_msi_display_name`: Set to `true` to override MSI's versioned DisplayName

## Create a Recipe for a JSON API Endpoint

Use this when the vendor provides a JSON API with version and download URL.

**Example: Generic JSON API**

1. Create the recipe file:

```yaml
# recipes/Vendor/app.yaml
apiVersion: napt/v1

name: "Application Name"
id: "napt-app"

discovery:
  strategy: api_json
  api_url: "https://api.vendor.com/latest"
  version_path: "version"          # JSONPath to version field (e.g., "version" or "data.version")
  download_url_path: "download_url"
  headers:                         # Optional HTTP headers (e.g., for authentication)
    Authorization: "Bearer ${API_TOKEN}"

psadt:
  app_vars:
    AppName: "Application Name"
    AppVersion: "{{discovered_version}}"
  install: |
    Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/S"
  uninstall: |
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

## Create a Recipe for an MSIX Installer

Use this when the application distributes an `.msix` installer. NAPT extracts
metadata from `AppxManifest.xml` and auto-generates install/uninstall commands.

**Example: Slack (MSIX via JSON API)**

1. Create the recipe file:

```yaml
# recipes/Slack/slack.yaml
apiVersion: napt/v1

name: "Slack"
id: "napt-slack"

discovery:
  strategy: api_json
  api_url: "https://slack.com/api/desktop.latestRelease?arch=x64&variant=msix&redirect=false"
  version_path: "version"
  download_url_path: "url"

# No psadt.install or psadt.uninstall needed!
# NAPT auto-generates from MSIX manifest based on intune.run_as_account:
#   system (default): Add-AppxProvisionedPackage -Online -PackagePath "..." -SkipLicense
#                     Get-AppxProvisionedPackage -Online | Where-Object { ... } | Remove-AppxProvisionedPackage -Online
#   user:             Add-AppxPackage -Path "$($adtSession.DirFiles)\slack.msix"
#                     Get-AppxPackage -Name "com.tinyspeck.slackdesktop" | Remove-AppxPackage

psadt:
  app_vars:
    AppName: "Slack"
    AppVersion: "{{discovered_version}}"
```

2. Validate and test:

```bash
napt validate recipes/Slack/slack.yaml
napt discover recipes/Slack/slack.yaml --verbose
```

**What makes MSIX different:**

- **No `psadt.install` / `psadt.uninstall` needed** - NAPT auto-generates
  commands from the MSIX manifest based on `intune.run_as_account`
- **No `intune.detection` needed** - Detection queries the AppX package
  database by identity name (not registry scanning); the store queried
  matches `intune.run_as_account`
- **Architecture auto-detected** - Extracted from `ProcessorArchitecture` in
  the MSIX manifest
- **`RequireAdmin` auto-defaulted** - Defaults to `false` for
  `run_as_account: "user"` since per-user installs don't require elevation

**Choosing install scope:**

Use `intune.run_as_account` to control whether the install is provisioned for
all users or installed for the current user only:

```yaml
intune:
  run_as_account: "system"  # Default: provisioned (all users)
  # run_as_account: "user"  # Per-user install
```

**Overriding auto-generated commands:**

Only needed for non-standard cases such as license files.
Set `override_msix_commands: true`:

```yaml
psadt:
  override_msix_commands: true
  install: |
    Add-AppxProvisionedPackage -Online -PackagePath "$($adtSession.DirFiles)\app.msix" -LicensePath "$($adtSession.DirFiles)\license.xml" -SkipLicense
  uninstall: |
    Get-AppxProvisionedPackage -Online | Where-Object { $_.DisplayName -eq "Vendor.App" } | Remove-AppxProvisionedPackage -Online
```

## Create a Recipe for a Fixed Download URL

Use this when the vendor has a stable download URL (like Chrome enterprise MSI).

**Example: Google Chrome**

1. Create the recipe file:

```yaml
# recipes/Google/chrome.yaml
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

2. Validate and test:

```bash
napt validate recipes/Google/chrome.yaml
napt discover recipes/Google/chrome.yaml --verbose
```

**What to customize:**

- `url`: Direct download URL (must be stable, not version-specific)
- `app_vars`: Application name, architecture, and other PSADT variables

**Note:** MSI files (`.msi` extension) are automatically detected and versions are extracted from the MSI ProductVersion property. Install/uninstall commands are auto-generated from the MSI (set `psadt.override_msi_commands: true` for custom commands). No additional configuration needed.

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
   discovery:
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
discovery:
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

name: "Google Chrome"
id: "napt-chrome"

discovery:
  strategy: url_download
  url: "https://dl.google.com/..."

intune:
  publisher: "Google LLC"
  description: "Google Chrome browser for enterprise deployment."
  privacy_url: "https://policies.google.com/privacy"
  info_url: "https://chromeenterprise.google"

psadt:
  # ... rest of recipe
```

### Override Upload Behavior

Control how Intune handles installation, restarts, and script execution
per-recipe using the `intune:` section.
All fields have sensible defaults and can also be set in `defaults/org.yaml`
for org-wide policy.

```yaml
intune:
  # Run installer and scripts as the logged-in user instead of SYSTEM.
  # Required for apps that install into the user profile. Default: "system".
  run_as_account: "user"

  # Suppress any device restart after install (useful for background updates).
  # Default: "basedOnReturnCode". Allowed: allow, suppress, force, basedOnReturnCode.
  device_restart_behavior: "suppress"

  # Increase timeout for large or slow installers. Default: 60.
  max_run_time_minutes: 120

  # Feature the app in Company Portal. Default: false.
  is_featured: true

  # Prevent self-service uninstall from Company Portal. Default: true.
  allow_available_uninstall: false

  # Require scripts to be code-signed before Intune will run them. Default: false.
  enforce_signature_check: true

  # Run installer and scripts in a 32-bit PowerShell context. Default: false.
  run_as_32_bit: true
```

See [recipe-reference.md](recipe-reference.md#intune-configuration) for all
allowed values.

### Require recorded releases before upload

For review-gated publish workflows, make `napt upload` refuse anything that
was not recorded at discovery.
Set once in `defaults/org.yaml`:

```yaml
deployment:
  require_pending: true
```

With this enabled, an upload fails unless the app's deployment state has a
pending release matching the package's installer hash.
For a legitimate manual upload under this policy, run `napt discover` first,
or add a pending entry (version, sha256, url) to
`state/deployment/<id>.json`.

### Promote updates through rings

Roll updates out gradually: pilot devices first, everyone else after the
release has proven itself.

1. **Define rings once in `defaults/org.yaml`** (groups are Entra ID
   display names or object IDs):

   ```yaml
   deployment:
     rings:
       - name: "pilot"
         groups: ["Pilot Devices"]
         promote_after_days: 2
       - name: "production"
         groups: ["Production Devices"]
     install:
       intent: "available"
       groups: ["All Users"]
   ```

2. **Plan** — compute what is eligible (read-only):

   ```bash
   napt promote plan
   ```

   A newly uploaded release starts its rollout in the first ring; a
   release that has held its ring for `promote_after_days` is promoted to
   the next.
   The same plan also points new installs (the install entry) at the new
   release, so net-new devices get it as soon as the first ring does.
   Eligible actions are written per app to `state/plans/<app-id>.json`;
   review the files, or commit them and gate the apply on a pull request.
   Every action opens with a plain-English summary sentence and carries
   the details behind it — the release, the groups it will assign, the
   version it replaces, and for a promotion out of a held ring, when the
   release entered it and the ring's bake threshold — so the files read
   as the review record.

3. **Apply** — execute the plan against Intune:

   ```bash
   napt promote apply
   ```

   Ring groups are assigned to the release's `[Update]` entry as required
   installs; the displaced older release is unassigned and retired per
   `deployment.retain_versions`.
   Each app's plan file is consumed after that app applies fully, and one
   app's failure keeps its plan file for retry without blocking the rest.
   Every apply also prints a drift check — discrepancies between
   deployment state and Intune (removed assignments, admin-made changes,
   stray apps) are warned about, never corrected.
   Use `napt promote plan --check-drift` for the same report without
   applying anything.
   Both commands also fail fast on a group typo or deleted Entra ID
   group: an authenticated plan refuses to write plans that name an
   unresolvable group, and apply checks every group an app's plan is
   about to assign before touching that app, so a bad group fails that
   app with zero changes instead of a half-applied plan.
   Run `napt status` to see where every app stands.

Run plan and apply on a schedule and promotion becomes automatic: each
release baked long enough moves one ring further on the next run.
A ring without `promote_after_days` is a manual gate — releases hold it
until you change the configuration.

### Set a custom app icon

`napt build` extracts an icon from the installer to `icons/{id}.png`
automatically, and `napt upload` sends it to Intune.
Most apps need no configuration.

When extraction finds no usable icon (the build prints a warning), or you
want a different image, you have two options:

**Option 1: Set logo_path in the recipe (recommended)**

```yaml
intune:
  # Relative paths resolve from the recipe file's location
  logo_path: "assets/7zip-logo.png"
```

The icon file lives in the recipe repo, so the fix travels to every
machine.
`logo_path` always wins over the icons directory and disables extraction
for that recipe.
Use a 256x256 PNG or JPEG under 700KB for best results in Company Portal.

**Option 2: Drop a PNG into the icons directory**

```bash
# The file name must match the recipe id
cp my-better-icon.png icons/napt-7zip-x64-msi.png
```

NAPT never overwrites an existing file in `icons/`, so your curated icon
survives future builds on this machine.
The icons directory is a machine-local output (gitignored), so this fix
does not travel with the repo.
Delete the file and rebuild to force re-extraction.

### Fix a broken published app

You published an app, installs are failing — a bad install command, wrong
detection settings, a missing PSADT step.
You fixed the recipe, and now Intune needs to match.

**The fix: delete the broken app and publish fresh.**

Intune throttles retries after repeated failures (the Global Retry
Schedule), and republishing content to the same app does not reliably
reset it.
A fresh app object gets a clean evaluation on every device:

1. Delete the broken app entries (install and `[Update]`) in the Intune
   portal.
   Deleting first matters: NAPT recognizes its own apps by their
   provenance stamp, so re-running upload against the existing broken app
   would adopt it instead of creating a new one.
2. Rebuild and upload:
   ```bash
   napt build recipes/Vendor/app.yaml
   napt package recipes/Vendor/app.yaml
   napt upload recipes/Vendor/app.yaml
   ```
   Upload finds no stamped apps, creates fresh entries, and records the
   new app IDs in deployment state automatically.
3. Recreate the assignments the old app had.

If the vendor has shipped a newer version since the broken publish, you
can also just run the normal pipeline — the new release creates new app
entries anyway, and the broken version's entries can be deleted.

**Exception: no device has attempted the install yet.**

If you caught the problem before any assignment took effect — the app is
still unassigned, or you spotted a wrong command during portal review —
there is no retry throttling to escape, and an in-place fix is faster:

```bash
napt build recipes/Vendor/app.yaml
napt package recipes/Vendor/app.yaml
napt upload recipes/Vendor/app.yaml --force
```

`--force` updates the existing app entries in place — metadata and a fresh
content version together — and keeps the app IDs.
It never creates duplicates.

## Automate NAPT with GitHub Actions

NAPT performs no git or CI operations itself — it reads and writes
deterministic files and leaves the choreography to your pipeline.
This section is a reference setup for a fully review-gated flow on
GitHub Actions.
Adapt names, schedules, and branch rules to your org.

**The model.** Two PR streams gate everything:

- **Publish PRs** (one per app): `napt discover` records a pending
  release in `state/deployment/<id>.json`; CI opens a per-app PR with
  that diff. The title carries the decision
  (`Publish Google Chrome 140.0.7339.128`) and the body is a generated
  fact sheet: version, installer URL, hash, what merging does, how to
  hold. Merging approves the release — a workflow builds, packages,
  and uploads it, with the hash gate guaranteeing the approved binary is
  exactly what ships.
- **Promotion PRs** (one, batched): `napt promote plan` writes one
  `state/plans/<id>.json` file per app with that app's eligible
  promotions; CI commits them to a branch and opens a PR whose body
  opens with a risk line (`**This plan:** 2 to pilot, 1 to production`),
  lists every app's plan summaries and the run's drift warnings, and
  carries a `promotes-to-production` label when the final ring is
  targeted. Merging
  approves the promotions — a workflow runs `napt promote apply`, which
  executes each app's plan as an allowlist, independently.
  To hold one app's promotions, delete its plan file in the PR; the
  next scheduled plan will re-propose it, and the other apps merge and
  apply unaffected.

**Writeback commits.** After upload and apply, NAPT has recorded new
facts (Intune app IDs, ring positions) in the working tree that must
reach `main`, so those workflows push a `[skip ci]` commit.
Two consequences to set up once:

- The workflow identity needs permission to push to `main` — either
  allow the Actions bot through branch protection or use a bot/app
  token with bypass rights.
- `[skip ci]` keeps the writeback from re-triggering workflows.

**Secrets.** `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and
`AZURE_TENANT_ID` for the app registration
(see [App Registration Setup](user-guide.md#app-registration-setup)).

**Recommended org.yaml hardening:**

```yaml
deployment:
  require_pending: true   # nothing reaches Intune without a reviewed release
```

### Workflow 1: discover (opens publish PRs)

```yaml
name: discover
on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:
permissions:
  contents: write
  pull-requests: write
jobs:
  discover:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install napt
      - name: Restore installers and discovery cache from the last run
        uses: actions/cache/restore@v4
        with:
          path: |
            downloads
            cache
          key: installers-
          restore-keys: installers-
      - name: Discover all recipes
        shell: bash
        run: |
          git ls-files 'recipes/*.yaml' 'recipes/**/*.yaml' | while read -r recipe; do
            napt discover "$recipe"
          done
      - name: Cache installers for publish and the next discover
        uses: actions/cache/save@v4
        with:
          path: |
            downloads
            cache
          key: installers-${{ github.run_id }}
      - name: Open one PR per app with a new pending release
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          git config user.name "napt-bot"
          git config user.email "napt-bot@users.noreply.github.com"
          # Stage first so brand-new (untracked) state files are seen too
          git add state/deployment
          changed=$(git diff --cached --name-only -- state/deployment)
          [ -z "$changed" ] && exit 0
          # Writes pr-body.md and prints the PR title for one app's
          # state file. The title is the decision (imperative, display
          # name + version); the body layers facts, then what merging
          # does, then how to say no.
          pr_meta() {
          python - "$1" <<'PY'
          import json
          import sys
          from pathlib import Path

          import yaml

          state_path = Path(sys.argv[1])
          app_id = state_path.stem
          state = json.loads(state_path.read_text(encoding="utf-8"))
          name = app_id
          for recipe in Path("recipes").rglob("*.y*ml"):
              try:
                  data = yaml.safe_load(recipe.read_text(encoding="utf-8"))
              except yaml.YAMLError:
                  continue
              if isinstance(data, dict) and data.get("id") == app_id:
                  name = data.get("name") or app_id
                  break
          pending = state.get("pending")
          deployed = state.get("deployed") or {}
          if pending is None:
              # Discovery cleared the pending slot: the vendor serves
              # the already-deployed release. The diff only records it.
              Path("pr-body.md").write_text(
                  f"**Name:** {name}\n\n"
                  "Discovery found the vendor serving the already-"
                  "deployed release, so this diff only clears the "
                  "app's pending slot. Merging records that; nothing "
                  "is published.\n",
                  encoding="utf-8",
              )
              print(f"Clear pending release for {name}")
              raise SystemExit
          current = deployed.get("version") or "none - first deployment"
          Path("pr-body.md").write_text(
              f"**Name:** {name}\n"
              f"**New version:** {pending['version']}\n"
              f"**Currently deployed:** {current}\n"
              f"**Installer:** {pending['url']}\n"
              f"**SHA-256:** `{pending['sha256']}`\n"
              "\n"
              "**Merging approves this exact binary.** The publish "
              "workflow builds, packages, and uploads it; the upload "
              "hash gate refuses any file that does not match the "
              "SHA-256 above.\n"
              "\n"
              "**To hold:** leave this PR open - nothing ships until "
              "it merges.\n"
              "**Closing is not a durable rejection:** the next "
              "discover run re-proposes the release, and a newer "
              "vendor release replaces this PR's content "
              "automatically.\n",
              encoding="utf-8",
          )
          print(f"Publish {name} {pending['version']}")
          PY
          }
          # Snapshot all changes on a temp branch, then carve out one
          # branch per app so each PR reviews exactly one state file.
          git checkout -b napt/discover-snapshot
          git commit -m "temp: discovery snapshot"
          for f in $changed; do
            app=$(basename "$f" .json)
            git checkout -B "napt/discover-$app" origin/main
            git checkout napt/discover-snapshot -- "$f"
            git commit -m "feat: Record pending release for $app"
            git push -f origin "napt/discover-$app"
            title=$(pr_meta "$f")
            # Refresh the title and body on every force-push so a
            # superseding release never leaves a stale decision open.
            gh pr create --head "napt/discover-$app" \
              --title "$title" --body-file pr-body.md \
              || gh pr edit "napt/discover-$app" \
                --title "$title" --body-file pr-body.md
          done
```

### Workflow 2: publish (on merge of a publish PR)

```yaml
name: publish
on:
  push:
    branches: [main]
    paths: ["state/deployment/**"]
# Serializes publish runs (bursts of merges dedupe to the newest run).
# Deliberately NOT shared with promote-apply: a merge that touches both
# deployment state and the plan file triggers both workflows, and runs
# sharing a group cancel each other instead of queueing.
concurrency: napt-publish
permissions:
  contents: write
jobs:
  publish:
    runs-on: windows-latest
    env:
      AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
      AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install napt
      - name: Restore cached installers
        uses: actions/cache/restore@v4
        with:
          path: |
            downloads
            cache
          key: installers-
          restore-keys: installers-
      - name: Publish every app with an approved pending release
        shell: bash
        run: |
          git ls-files 'recipes/*.yaml' 'recipes/**/*.yaml' | while read -r recipe; do
            id=$(python -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1], encoding='utf-8'))['id'])" "$recipe")
            state="state/deployment/$id.json"
            [ -f "$state" ] || continue
            pending=$(python -c "import json, sys; print(json.load(open(sys.argv[1], encoding='utf-8')).get('pending') is not None)" "$state")
            [ "$pending" = "True" ] || continue
            # Use the cached installer when its hash matches the approved
            # release; otherwise fetch from the vendor. --stateless keeps
            # the approved pending untouched, and the upload hash gate
            # refuses anything that does not match it.
            psha=$(python -c "import json, sys; print(json.load(open(sys.argv[1], encoding='utf-8'))['pending']['sha256'])" "$state")
            if ! sha256sum "downloads/$id/"* 2>/dev/null | grep -q "^$psha "; then
              napt discover "$recipe" --stateless
              # Fail fast when the vendor no longer serves the approved
              # binary (the upload hash gate would refuse it anyway).
              sha256sum "downloads/$id/"* 2>/dev/null | grep -q "^$psha " || {
                echo "::error::$id: vendor no longer serves the approved release ($psha); the approval is stranded until a new discover PR supersedes it"
                exit 1
              }
            fi
            napt build "$recipe"
            napt package "$recipe"
            napt upload "$recipe"
          done
      - name: Write back recorded app IDs
        shell: bash
        run: |
          git config user.name "napt-bot"
          git config user.email "napt-bot@users.noreply.github.com"
          git add state/deployment
          git diff --cached --quiet && exit 0
          git commit -m "chore: Record published releases [skip ci]"
          # main may have advanced while this run published (more merges,
          # another workflow's writeback). State files are per-app, so a
          # rebase cannot conflict.
          for attempt in 1 2 3; do
            git push && exit 0
            git pull --rebase origin main
          done
          git push
```

**Why the installer cache steps matter.**
Without them, the publish runner re-downloads from the vendor, which
couples an already-approved publish to the vendor still serving that
exact binary — a pulled or replaced file strands the approval at the
hash gate.
The cache steps above hand the publish runner the very binary that was
reviewed; the sha256 check in the loop falls back to a fresh download
when the cache is stale or evicted (GitHub evicts caches unused for
about a week), so the flow degrades gracefully.
This is safe by construction — the upload hash gate validates whatever
binary the runner provides, so a cache can never ship the wrong bytes.

The restore step in the discover workflow serves a second purpose:
bandwidth.
`napt discover` records each vendor's `ETag`/`Last-Modified` headers in
`cache/discovery.json` and sends them as conditional request headers on
the next run; when the vendor answers HTTP 304, the previously
downloaded installer is reused without transferring a byte.
A fresh runner starts with neither the header cache nor the files, so
restoring `cache/` and `downloads/` from the last run is what lets the
scheduled discover skip re-downloading installers that have not changed
— which adds up quickly for recipe sets full of large installers.
Keep the `path` lists of the save and restore steps identical:
`actions/cache` makes the path list part of the cache version, so a
mismatched list reads as a silent cache miss.

For long-lived archival — including installers for retained releases the
vendor no longer serves — replace the cache steps with an object store
(S3, Azure Blob) or a self-hosted runner with a persistent `downloads/`
directory.

### Workflow 3: promotion plan (opens the promotion PR)

```yaml
name: promote-plan
on:
  schedule:
    - cron: "0 7 * * *"
  workflow_dispatch:
permissions:
  contents: write
  pull-requests: write
jobs:
  plan:
    runs-on: windows-latest
    env:
      AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
      AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install napt
      - name: Plan promotions (with drift report and writeback recovery)
        shell: bash
        # tee keeps the log so the PR body below can carry the drift
        # warnings; bash's default pipefail preserves the exit code.
        run: napt promote plan --check-drift --reconcile | tee plan.log
      - name: Open or update the promotion PR
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          # git status sees untracked files (a first-ever plan) too.
          # Watch all of state/: --reconcile may have repaired a
          # deployment state file whose publish writeback was lost.
          [ -z "$(git status --porcelain -- state)" ] && exit 0
          git config user.name "napt-bot"
          git config user.email "napt-bot@users.noreply.github.com"
          git checkout -B napt/promotion-plan origin/main
          git add state
          git commit -m "feat: Plan ring promotions"
          git push -f origin napt/promotion-plan
          # Writes pr-body.md from the plan files themselves: the risk
          # line first, then each app's action summaries (the same
          # sentences NAPT wrote into the files), the hold instruction,
          # and the plan run's drift warnings. Prints "production" when
          # the plan assigns the final ring (ring policy is org-wide,
          # so the last ring comes from org.yaml).
          label=$(python - <<'PY'
          import json
          from pathlib import Path

          import yaml

          org = yaml.safe_load(
              Path("defaults/org.yaml").read_text(encoding="utf-8")
          ) or {}
          rings = [r["name"] for r in org.get("deployment", {}).get("rings", [])]
          last_ring = rings[-1] if rings else None

          counts = {}
          assigns = 0
          stanzas = []
          final_ring_hit = False
          for path in sorted(Path("state/plans").glob("*.json")):
              plan = json.loads(path.read_text(encoding="utf-8"))
              lines = [f"**{plan['name']}** (`{plan['app_id']}`)"]
              for action in plan["actions"]:
                  lines.append(f"- {action['summary']}")
                  if action["type"] == "promote":
                      counts[action["ring"]] = counts.get(action["ring"], 0) + 1
                      if action["ring"] == last_ring:
                          final_ring_hit = True
                  else:
                      assigns += 1
              stanzas.append("\n".join(lines))

          ordered = [r for r in rings if r in counts]
          ordered += [r for r in counts if r not in rings]
          bits = [f"{counts[r]} to {r}" for r in ordered]
          if assigns:
              bits.append(f"{assigns} install assignment(s)")
          risk = ", ".join(bits) if bits else (
              "no ring changes - this refresh carries recovered "
              "deployment state only"
          )

          drift = []
          in_section = False
          for line in Path("plan.log").read_text(encoding="utf-8").splitlines():
              if "DRIFT CHECK" in line:
                  in_section = True
              elif in_section and "[WARNING]" in line:
                  drift.append("- " + line.split("[WARNING]", 1)[1].strip())

          parts = [f"**This plan:** {risk}"]
          if stanzas:
              parts.extend(stanzas)
              parts.append(
                  "**Merging approves and applies every action above.**"
              )
              parts.append(
                  "**To hold one app:** delete its "
                  "`state/plans/<app-id>.json` file from this PR - the "
                  "other apps apply unaffected, and the next plan run "
                  "re-proposes whatever is still eligible."
              )
          if drift:
              parts.append(
                  "**Drift warnings** (deployment state vs. the tenant "
                  "at plan time):\n" + "\n".join(drift)
              )
          Path("pr-body.md").write_text(
              "\n\n".join(parts) + "\n", encoding="utf-8"
          )
          print("production" if final_ring_hit else "")
          PY
          )
          # Title stays generic and stable (only one promotion PR is
          # ever open; title churn breaks email threading) - the risk
          # signal lives in the body's first line and the label.
          gh pr create --head napt/promotion-plan \
            --title "Promotion plan" --body-file pr-body.md \
            || gh pr edit napt/promotion-plan --body-file pr-body.md
          if [ "$label" = "production" ]; then
            gh label create promotes-to-production \
              --description "This plan assigns the final ring" \
              --color D93F0B --force
            gh pr edit napt/promotion-plan --add-label promotes-to-production
          else
            gh pr edit napt/promotion-plan \
              --remove-label promotes-to-production || true
          fi
```

### Workflow 4: promotion apply (on merge of the promotion PR)

```yaml
name: promote-apply
on:
  push:
    branches: [main]
    paths: ["state/plans/**"]
# Own group (not shared with publish) - see the publish workflow's
# concurrency comment.
concurrency: napt-promote-apply
permissions:
  contents: write
jobs:
  apply:
    runs-on: windows-latest
    env:
      AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
      AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install napt
      # Apply exits 1 when any app's plan fails, but other apps may
      # have applied — continue so the writeback records their ring
      # positions and consumed plans; a final step fails the run.
      - name: Apply the approved plans
        id: apply
        continue-on-error: true
        run: napt promote apply
      - name: Write back ring positions and consume the plans
        shell: bash
        run: |
          git config user.name "napt-bot"
          git config user.email "napt-bot@users.noreply.github.com"
          git add state
          git diff --cached --quiet && exit 0
          git commit -m "chore: Record applied promotions [skip ci]"
          # Same rebase-and-retry as the publish writeback.
          for attempt in 1 2 3; do
            git push && exit 0
            git pull --rebase origin main
          done
          git push
      - name: Surface a failed apply
        if: steps.apply.outcome == 'failure'
        run: exit 1
```

**Notes:**

- Promotions merged but applied later are always safe: bake time only
  grows, and apply validates every entry against current state anyway.
- Apply treats each app's plan file as an independent unit: a failure
  (an unresolvable group, a Graph error) fails that app, keeps its plan
  file on `main` for the next apply, and never blocks the other apps —
  which is why the writeback above runs even when the apply step fails.
- Resolving a failed app depends on the failure class.
  A transient Graph error needs no fix: re-run the apply workflow —
  already-applied actions skip, the rest complete, and the plan file is
  consumed.
  An unresolvable group needs the configuration fixed (or the Entra ID
  group restored) and then a re-plan, not just a re-run: plan files bake
  in group names at plan time, so the fix reaches Intune when the next
  scheduled plan regenerates the file and the promotion PR carries the
  corrected plan.
  Until then, apply keeps failing that one app — and only that one.
  A corrupted state file restores from git history like any other
  committed file.
- All four workflows are idempotent — re-running any of them converges
  to the same result (upload adopts existing apps, apply skips
  already-applied actions).
- A publish whose writeback push fails (branch protection, a crashed
  runner) self-heals: the next plan run's `--reconcile` re-records the
  publication from tenant evidence, the promotion PR carries the repair,
  and the recovered release is planned for its first ring in the same
  run. Re-running the failed publish also converges, just sooner.
- `windows-latest` runners are required for `napt package`
  (IntuneWinAppUtil.exe is Windows-only). The discover workflow alone
  could run on Linux with `msitools` installed for MSI version
  extraction.

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

4. **If version format changed, clear the cache:**
   ```bash
   # Delete cache entry for this app
   # Or delete the entire discovery cache to start fresh
   rm cache/discovery.json
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
   discovery:
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

### Issue: "Discovery cache corrupted"

**Problem:** `cache/discovery.json` has invalid JSON or is corrupted.

**Solution:**

NAPT automatically handles cache corruption:

1. Creates backup of corrupted file: `cache/discovery.json.backup`

2. Creates a fresh cache file automatically

3. Reports the issue with an error message

The cache is already fixed - just run your command again. Alternatively, use `--stateless` to bypass state tracking temporarily:

```bash
napt discover recipes/app.yaml --stateless
```

**Note:** Deployment state files (`state/deployment/`) are authoritative and are never auto-replaced.
If one is corrupted, fix the JSON or restore the file from a backup.

## What's Next?

- **[User Guide](user-guide.md)** - Deep dive into discovery strategies, state management, and configuration
- **[Creating Recipes](user-guide.md#discovery-strategies)** - Detailed strategy configuration guides
- **[Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)** - Browse working recipe examples
