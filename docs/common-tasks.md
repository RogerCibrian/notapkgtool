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

   A newly uploaded release enters the first ring; a release that has held
   its ring for `promote_after_days` advances to the next.
   Eligible actions are written to `state/plan.json`; review the file, or
   commit it and gate the apply on a pull request.

3. **Apply** — execute the plan against Intune:

   ```bash
   napt promote apply
   ```

   Ring groups are assigned to the release's `[Update]` entry as required
   installs; the displaced older release is unassigned and retired per
   `deployment.retain_versions`.
   Every apply also prints a drift check — discrepancies between
   deployment state and Intune (removed assignments, admin-made changes,
   stray apps) are warned about, never corrected.
   Use `napt promote plan --check-drift` for the same report without
   applying anything.
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
  that diff. Merging approves the release — a workflow builds, packages,
  and uploads it, with the hash gate guaranteeing the approved binary is
  exactly what ships.
- **Promotion PRs** (one, batched): `napt promote plan` writes
  `state/plan.json` when releases are eligible to enter or advance
  rings; CI commits it to a branch and opens a PR. Merging approves the
  promotions — a workflow runs `napt promote apply`, which executes the
  plan as an allowlist.
  To hold one promotion, delete its entry from the plan file in the PR;
  the next scheduled plan will re-propose it.

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
      - name: Discover all recipes
        shell: bash
        run: |
          git ls-files 'recipes/*.yaml' 'recipes/**/*.yaml' | while read -r recipe; do
            napt discover "$recipe"
          done
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
            gh pr create --head "napt/discover-$app" \
              --title "Publish approval: $app" \
              --body "Merging approves publishing this release to Intune." \
              || true  # PR already open; the force-push updated it
          done
```

### Workflow 2: publish (on merge of a publish PR)

```yaml
name: publish
on:
  push:
    branches: [main]
    paths: ["state/deployment/**"]
concurrency: napt-writeback
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
      - name: Publish every app with an approved pending release
        shell: bash
        run: |
          git ls-files 'recipes/*.yaml' 'recipes/**/*.yaml' | while read -r recipe; do
            id=$(python -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1], encoding='utf-8'))['id'])" "$recipe")
            state="state/deployment/$id.json"
            [ -f "$state" ] || continue
            pending=$(python -c "import json, sys; print(json.load(open(sys.argv[1], encoding='utf-8')).get('pending') is not None)" "$state")
            [ "$pending" = "True" ] || continue
            # Installers are machine-local (never committed), so this
            # runner must fetch the binary. --stateless keeps the
            # approved pending untouched: if the vendor swapped binaries
            # since review, the upload hash gate refuses.
            napt discover "$recipe" --stateless
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
          git diff --cached --quiet || {
            git commit -m "chore: Record published releases [skip ci]"
            git push
          }
```

**Advised: persist installers between discover and publish.**
As written, the publish runner re-downloads from the vendor, which
couples an already-approved publish to the vendor still serving that
exact binary — if the file was pulled or replaced in the meantime, the
hash gate refuses and the approval is stranded until the next release is
reviewed.
Caching the downloaded installer at discover time removes that
dependency: an object store (S3, Azure Blob), a GitHub Actions cache
keyed on the pending release's sha256, or a self-hosted runner with a
persistent `downloads/` directory all work.
On the publish runner, restore the cache and skip the `--stateless`
discover step on a hit.
This is safe by construction — the hash gate validates whatever binary
the runner provides against the approved sha256, so a cache can never
ship the wrong bytes.
It also preserves installers for retained releases, which the vendor may
no longer serve if you ever need to republish one.

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
      - name: Plan promotions (with drift report)
        run: napt promote plan --check-drift
      - name: Open or update the promotion PR
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          # git status sees untracked files (a first-ever plan) too
          [ -z "$(git status --porcelain -- state/plan.json)" ] && exit 0
          git config user.name "napt-bot"
          git config user.email "napt-bot@users.noreply.github.com"
          git checkout -B napt/promotion-plan origin/main
          git add state/plan.json
          git commit -m "feat: Plan ring promotions"
          git push -f origin napt/promotion-plan
          gh pr create --head napt/promotion-plan \
            --title "Promotion plan" \
            --body "Merging approves these ring promotions. Delete an entry from state/plan.json to hold it." \
            || true  # PR already open; the force-push updated it
```

### Workflow 4: promotion apply (on merge of the promotion PR)

```yaml
name: promote-apply
on:
  push:
    branches: [main]
    paths: ["state/plan.json"]
concurrency: napt-writeback
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
      - name: Apply the approved plan
        run: napt promote apply
      - name: Write back ring positions and consume the plan
        shell: bash
        run: |
          git config user.name "napt-bot"
          git config user.email "napt-bot@users.noreply.github.com"
          git add state
          git diff --cached --quiet || {
            git commit -m "chore: Record applied promotions [skip ci]"
            git push
          }
```

**Notes:**

- Promotions merged but applied later are always safe: bake time only
  grows, and apply validates every entry against current state anyway.
- All four workflows are idempotent — re-running any of them converges
  to the same result (upload adopts existing apps, apply skips
  already-applied actions).
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
