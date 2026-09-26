# Common tasks

Copy-paste workflows.
For how each step works, see the [user guide](user-guide.md).

> **Tip:** Run `napt <command> --help` for options and examples.
> For example, `napt discover --help`.

## Initialize a new NAPT project

### Quick setup

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
[2/2] Creating configuration files...

======================================================================
INITIALIZATION RESULTS
======================================================================
Project Root:    /path/to/my-intune-packages

Created (4):
  [OK] recipes/
  [OK] defaults/vendors/
  [OK] state/deployment/
  [OK] defaults/org.yaml

======================================================================

[SUCCESS] Project initialized!
```

### What gets created

```
my-intune-packages/
├── defaults/
│   ├── org.yaml              # Organization-wide defaults (commented template)
│   └── vendors/              # Vendor-specific overrides (empty)
├── recipes/                  # Your recipe files go here
└── state/
    └── deployment/           # Per-app deployment state (written by discover, upload, promote)
```

`napt init` creates no `.gitignore`.
Add the folders NAPT writes on each machine to your own: `downloads/`,
`builds/`, `packages/`, `icons/`, and `cache/`.

### Handling existing files

`napt init` skips files that already exist:

```console
$ napt init
Initializing NAPT project in: /path/to/existing-project

[1/2] Creating directory structure...
[2/2] Creating configuration files...

======================================================================
INITIALIZATION RESULTS
======================================================================
Project Root:    /path/to/existing-project

Skipped (4):
  [SKIP] recipes/
  [SKIP] defaults/vendors/
  [SKIP] state/deployment/
  [SKIP] defaults/org.yaml

======================================================================

Note: Existing files were preserved. Use --force to overwrite.

[SUCCESS] Project initialized!
```

To overwrite existing files (with automatic backup):

```bash
napt init --force
```

This backs up `defaults/org.yaml` before replacing it (directories are never
touched):

```console
$ napt init --force
Initializing NAPT project in: /path/to/existing-project

[1/2] Creating directory structure...
[2/2] Creating configuration files...

======================================================================
INITIALIZATION RESULTS
======================================================================
Project Root:    /path/to/existing-project

Created (1):
  [OK] defaults/org.yaml

Backed Up (1):
  [OK] defaults/org.yaml -> org.yaml.backup

Skipped (3):
  [SKIP] recipes/
  [SKIP] defaults/vendors/
  [SKIP] state/deployment/

======================================================================

[SUCCESS] Project initialized!
```

### Next steps after init

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

## Create a recipe for a GitHub release app

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
    Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/VERYSILENT /NORESTART"
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

## Create a recipe for a vendor download page

Use this when the vendor has a download page listing installers (no API
available).

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

NAPT generates the install and uninstall commands from the MSI.
To supply your own (for example, an MST transform), see
[override_msi_commands](recipe-reference.md#override_msi_commands).

2. Validate and test:

```bash
napt validate recipes/7-Zip/7zip-x64-msi.yaml
napt discover recipes/7-Zip/7zip-x64-msi.yaml --verbose
```

**What to customize:**

- `page_url`: Vendor download page URL
- `link_selector`: CSS selector to find the download link
- `version_pattern`: Regex to extract version from URL
- `version_format`: Format string to transform version (optional)
- `intune.detection`: Configure when the vendor puts the version in the
  DisplayName (for example, "7-Zip 25.01")
  - `display_name`: Pattern with wildcards to match the installed app name
  - `override_msi_display_name`: Set to `true` to override the MSI's
    versioned DisplayName

## Create a recipe for a JSON API endpoint

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
  version_pattern: "v?([0-9.]+)"   # Optional: narrow the version value with a regex
  headers:                         # Optional HTTP headers (e.g., for authentication)
    Authorization: "${API_AUTH_HEADER}"

intune:
  detection:
    display_name: "Application Name"
    architecture: "x64"

psadt:
  app_vars:
    AppName: "Application Name"
    AppVersion: "{{discovered_version}}"
  install: |
    Start-ADTProcess -FilePath "{{installer_filename}}" -ArgumentList "/S"
  uninstall: |
    Uninstall-ADTApplication -Name "Application Name"
```

2. Set `API_AUTH_HEADER` in your environment (see
   [Handle authentication tokens](#handle-authentication-tokens)).

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

## Create a recipe for an MSIX installer

Use this when the application distributes an `.msix` installer.

**Example: Slack (MSIX via JSON API)**

1. Create the recipe file:

```yaml
# recipes/Slack/slack-msix.yaml
apiVersion: napt/v1

name: "Slack"
id: "napt-slack"

discovery:
  strategy: api_json
  api_url: "https://slack.com/api/desktop.latestRelease?arch=x64&variant=msix&redirect=false"
  version_path: "version"
  download_url_path: "download_url"

psadt:
  app_vars:
    AppName: "Slack"
    AppVersion: "{{discovered_version}}"
```

2. Validate and test:

```bash
napt validate recipes/Slack/slack-msix.yaml
napt discover recipes/Slack/slack-msix.yaml --verbose
```

NAPT generates install, uninstall, and detection from the MSIX manifest and
reads the architecture from it, so the recipe needs no `psadt.install`,
`psadt.uninstall`, or `intune.detection`.
`intune.run_as_account` picks a provisioned install (`system`, the default)
or a per-user one (`user`).
For license files or other custom commands, see
[override_msix_commands](recipe-reference.md#override_msix_commands).

## Create a recipe for a fixed download URL

Use this when the vendor has a stable download URL (like Chrome enterprise
MSI) and the installer is an MSI or MSIX.
`url_download` reads the version from the downloaded installer, which works
for those two types only; for any other installer use a version-first
strategy (`api_github`, `api_json`, or `web_scrape`).

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
- `app_vars`: Application name and other PSADT variables

**Note:** MSI installers supply their own version and install/uninstall
commands; see the 7-Zip example above.

## Handle authentication tokens

### Environment variables (recommended)

`discovery.token` and each value under `discovery.headers` are replaced
from the environment only when the whole value is exactly `${VAR}`.
A value such as `"Bearer ${API_TOKEN}"` is sent as written, so put the
full header value, scheme included, in the variable.
When the variable is not set, the header is dropped (or the `api_github`
request goes out unauthenticated) and discovery continues.

1. **Set the variable in your environment:**
   ```powershell
   # Windows
   $env:API_AUTH_HEADER="Bearer <token>"
   ```
   ```bash
   # Linux/macOS
   export API_AUTH_HEADER="Bearer <token>"
   ```

2. **Reference it in the recipe:**
   ```yaml
   discovery:
     strategy: api_json
     api_url: "https://api.vendor.com/latest"
     version_path: "version"
     download_url_path: "download_url"
     headers:
       Authorization: "${API_AUTH_HEADER}"
   ```

3. **In CI/CD, use secrets:**
   ```yaml
   # GitHub Actions
   - name: Discover version
     env:
       API_AUTH_HEADER: ${{ secrets.API_AUTH_HEADER }}
     run: napt discover recipes/Vendor/app.yaml
   ```

### Recipe-level tokens (less secure)

A token can also go in the recipe, where it is committed with the file:

```yaml
discovery:
  strategy: api_github
  repo: "owner/repo"
  token: "ghp_your_token_here"
```

## Test recipes before production

Run these checks on a new recipe, and again after editing one.

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
   # Installers are filed as downloads/<id>/<version>/<file>
   ls -lhR downloads/napt-app/
   ```

4. **Test build:**
   ```bash
   napt build recipes/Vendor/app.yaml --verbose
   ```

5. **Verify build structure:**
   ```bash
   # Check PSADT files are present
   ls builds/napt-app/*/packagefiles/Invoke-AppDeployToolkit.ps1
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

Upload a packaged app to Microsoft Intune.
Requires `napt package` to have run first.

### App registration setup (one time per organization)

Run as an Application Administrator (or a role above it):

```bash
# Creates the registration without the Entra portal
napt auth setup --tenant-id "<Directory (tenant) ID>"
```

To do it by hand, follow
[App registration setup](user-guide.md#app-registration-setup) in the user
guide (or run `napt auth setup ... --print-only` for the checklist).

### Developer setup (one time)

Sign in once with the IDs from the app registration:

```bash
napt auth login --tenant-id "<Directory (tenant) ID>" --client-id "<Application (client) ID>"
```

On Windows the OS account picker opens; elsewhere your browser does.
The IDs are remembered, so later sessions are just `napt auth login`, and
`napt upload` / `napt promote` run silently until the session expires.
`napt auth status` shows the account, tenant, and permissions in use;
`napt auth logout` clears the session.

### CI/CD setup (one time)

Use OIDC federation where your CI platform supports it, or a client secret
otherwise; [App registration setup](user-guide.md#app-registration-setup)
has both, including the federated credential and the `azure/login` job.
With a client secret, pass the three values as environment variables:

```yaml
- name: Upload to Intune
  env:
    AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
    AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
    AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
  run: napt upload recipes/Google/chrome.yaml
```

The app registration must have the `DeviceManagementApps.ReadWrite.All` and
`Group.Read.All` Microsoft Graph application permissions.

### Upload an app

```bash
napt upload recipes/Google/chrome.yaml
```

**Example output:**

```console
$ napt upload recipes/Google/chrome.yaml
Uploading package for recipe: /path/to/recipes/Google/chrome.yaml

[1/9] Locating .intunewin package...
[UPLOAD] Package matches pending release (sha256 <sha256>)
[2/9] Authenticating with Azure...
[3/9] Parsing package metadata...
[4/9] Creating app record for 'Google Chrome'...
[UPLOAD] Created Intune app: <app id>
[5/9] Uploading to Azure Blob Storage...
[6/9] Committing content version...
[7/9] Creating app record for '[Update] Google Chrome'...
[UPLOAD] Created Intune app: <update id>
[8/9] Uploading to Azure Blob Storage...
[9/9] Committing content version...
[STATE] Recorded published release <version> in <state file>
======================================================================
UPLOAD RESULTS
======================================================================
App ID:          napt-chrome
App Name:        Google Chrome
Version:         <version>
Intune Win32 App ID:    <app id>
Intune Win32 Update ID: <update id>
Package:         /path/to/packages/napt-chrome/<version>/Invoke-AppDeployToolkit.intunewin
Status:          success
======================================================================

[SUCCESS] Package uploaded to Intune successfully!
```

With `intune.build_types` set to `app_only` or `update_only`, upload shows
six steps.
When no pending release is recorded, the `Package matches` line becomes a
`No pending release recorded` warning (or an error under
[`require_pending`](#require-recorded-releases-before-upload)).

### Full pipeline example

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

### Override publisher and description

By default, the publisher is inferred from the vendor directory name
(for example, `recipes/Google/` gives `"Google"`).
Override it per recipe in the `intune:` section:

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
  app_vars:
    AppName: "Google Chrome"
    AppVersion: "{{discovered_version}}"
```

### Override upload behavior

Set these per recipe in the `intune:` section, or in `defaults/org.yaml` for
the whole organization:

```yaml
intune:
  # Run installer and scripts as the logged-in user instead of SYSTEM
  run_as_account: "user"

  # Suppress any device restart after install
  device_restart_behavior: "suppress"

  # Allow more time for large or slow installers
  max_run_time_minutes: 120

  # Feature the app in Company Portal
  is_featured: true

  # Prevent self-service uninstall from Company Portal
  allow_available_uninstall: false

  # Require scripts to be code-signed before Intune runs them
  enforce_signature_check: true

  # Run installer and scripts in a 32-bit PowerShell context
  run_as_32_bit: true
```

See [Intune configuration](recipe-reference.md#intune-configuration) for
defaults and allowed values.

### Require recorded releases before upload

For review-gated publish workflows, make `napt upload` refuse anything that
was not recorded at discovery.
Set once in `defaults/org.yaml`:

```yaml
deployment:
  require_pending: true
```

For a manual upload under this policy, run `napt discover` first.
Discover records nothing when the vendor serves the release that is already
published, so to republish that release add the pending entry by hand (see
[Fix a broken published app](#fix-a-broken-published-app)).
See [`require_pending`](recipe-reference.md#require_pending) for exact
behavior.

### Promote updates through rings

A release is assigned to the first ring's groups, then to each later ring
once it has held the previous one for `promote_after_days`.

1. **Define rings once in `defaults/org.yaml`** (groups are Entra ID
   display names or object IDs, or the reserved `All Users` and
   `All Devices`):

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

2. **Plan**: compute what is eligible (read-only):

   ```bash
   napt promote plan
   ```

   Plan writes one file per app with eligible actions to
   `state/plans/<app-id>.json`.
   Review the files, or commit them and gate apply on a pull request.
   [Promotion plan files](user-guide.md#promotion-plan-files) describes
   their contents.

3. **Apply**: execute the plan against Intune:

   ```bash
   napt promote apply
   ```

   Apply assigns each ring's groups to the release's `[Update]` entry as
   required installs, unassigns and retires the release it displaces, and
   consumes each app's plan file once that app applies.
   It also checks for drift and prints any discrepancies it finds.
   A plan run with `--check-drift` or `--reconcile` checks every group the
   plan would assign and writes no plan files, for any app, when one does
   not resolve; plain `napt promote plan` does not check groups.
   [napt promote](user-guide.md#napt-promote) covers failures, drift, and
   group checks.
   Run `napt status` to see where every app stands.

Run plan and apply on a schedule and promotion becomes automatic: each
release baked long enough moves one ring further on the next run.
A ring without `promote_after_days` is a manual gate; releases hold it
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

NAPT never overwrites a file in `icons/`.
The file stays on this machine only (keep `icons/` in your `.gitignore`);
delete it and rebuild to extract again.

### Fix a broken published app

You published an app, installs are failing: a bad install command, wrong
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
2. With `deployment.require_pending: true`, record the release again by
   hand.
   Upload refuses without a pending release, and `napt discover` records
   nothing while the vendor serves the published binary.
   In `state/deployment/<id>.json`, set `pending` to the published
   release's `version` and `sha256` and its download `url`:
   ```json
   "pending": {
     "version": "<published version>",
     "sha256": "<published sha256>",
     "url": "<installer download URL>"
   },
   ```
   If that version's installer is no longer in
   `downloads/<id>/<version>/`, fetch it with `napt discover --stateless`,
   which leaves the entry alone (a plain `napt discover` clears it again).
3. Rebuild and upload:
   ```bash
   napt build recipes/Vendor/app.yaml
   napt package recipes/Vendor/app.yaml
   napt upload recipes/Vendor/app.yaml
   ```
   Upload finds no stamped apps, creates fresh entries, and records the
   new app IDs in deployment state automatically.
4. Recreate the assignments the old app had.

If the vendor has shipped a newer version since the broken publish, you
can also just run the normal pipeline; the new release creates new app
entries anyway, and the broken version's entries can be deleted.

**Exception: no device has attempted the install yet.**

If you caught the problem before any assignment took effect (the app is
still unassigned, or you spotted a wrong command during portal review),
there is no retry throttling to escape, and an in-place fix is faster
(under `require_pending`, add the pending entry from step 2 first):

```bash
napt build recipes/Vendor/app.yaml
napt package recipes/Vendor/app.yaml
napt upload recipes/Vendor/app.yaml --force
```

`--force` updates the existing app entries in place (metadata and a fresh
content version together) and keeps the app IDs.
It never creates duplicates.

## Automate NAPT with GitHub Actions

NAPT performs no git or CI operations itself: it reads and writes
deterministic files and leaves the choreography to your pipeline.
What follows is a review-gated flow on GitHub Actions.
Adapt names, schedules, and branch rules to your org.

**The model.** Two PR streams gate everything:

- **Publish PRs** (one per app): `napt discover` records a pending
  release in `state/deployment/<id>.json`; CI opens a per-app PR with
  that diff.
  The title carries the decision
  (`Publish Google Chrome 140.0.7339.128`) and the body is a generated
  fact sheet: version, currently published version, installer URL,
  SHA-256, what merging does, and how to hold it (closing is not a durable
  rejection).
  A downgrade is titled `Publish <Name> <version> (downgrade from
  <published>)`, and when discovery empties the pending slot the PR is
  titled `Clear pending release for <Name>` and publishes nothing (see
  [Downgrades](user-guide.md#downgrades)).
  Merging approves the release: a workflow builds, packages,
  and uploads it, with the hash gate guaranteeing the approved binary is
  exactly what ships.
- **Promotion PRs** (one, batched): `napt promote plan` writes one
  `state/plans/<id>.json` file per app with that app's eligible
  promotions; CI commits them to a branch and opens a PR whose body
  opens with a risk line (`**This plan:** 2 to pilot, 1 to production`),
  lists every app's plan summaries and the run's drift warnings, and
  carries a `promotes-to-production` label when the final ring is
  targeted.
  Merging approves the promotions: a workflow runs `napt promote apply`,
  which executes each app's plan as an allowlist, independently.
  To hold one app's promotions, delete its plan file in the PR; the
  next scheduled plan will re-propose it, and the other apps merge and
  apply unaffected.

**Writeback commits.** After upload and apply, NAPT has recorded new
facts (Intune app IDs, ring positions) in the working tree that must
reach `main`, so those workflows push a `[skip ci]` commit.
Two consequences to set up once:

- The workflow identity needs permission to push to `main`, either
  allow the Actions bot through branch protection or use a bot/app
  token with bypass rights.
- `[skip ci]` keeps the writeback from re-triggering workflows.

**Secrets.** `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` for the app
registration, plus either a federated credential (OIDC, recommended; swap
the `env:` block in the examples below for an `azure/login` step) or
`AZURE_CLIENT_SECRET`
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
      - name: Restore installers from the last run
        uses: actions/cache/restore@v4
        with:
          path: downloads
          key: installers-
          restore-keys: installers-
      - name: Discover all recipes
        shell: bash
        # Actions' `shell: bash` runs with -e, so an unguarded loop would
        # end at the first failing recipe (a vendor outage, a version the
        # pattern cannot handle) and silently skip every recipe after it.
        # Failures are collected instead, the successful apps still get
        # their PRs below, and the last step fails the job.
        run: |
          : > discover-failures.txt
          git ls-files 'recipes/*.yaml' 'recipes/**/*.yaml' | while read -r recipe; do
            napt discover "$recipe" || {
              echo "::error::napt discover failed for $recipe"
              echo "$recipe" >> discover-failures.txt
            }
          done
      - name: Cache installers for publish and the next discover
        uses: actions/cache/save@v4
        with:
          path: downloads
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
          import subprocess
          import sys
          from pathlib import Path

          state_path = Path(sys.argv[1])
          state = json.loads(state_path.read_text(encoding="utf-8"))
          # The state file names its app; the filename backstops a
          # file saved before any name was recorded.
          name = state.get("name") or state_path.stem
          pending = state.get("pending")
          published = state.get("published") or {}
          if pending is None:
              # Discovery cleared the pending slot: the vendor serves
              # the already-published release. The diff only records it.
              Path("pr-body.md").write_text(
                  f"**Name:** {name}\n\n"
                  "Discovery found the vendor serving the already-"
                  "published release, so this diff only clears the "
                  "app's pending slot. Merging records that; nothing "
                  "is published.\n",
                  encoding="utf-8",
              )
              print(f"Clear pending release for {name}")
              raise SystemExit
          current = published.get("version") or "none - first deployment"
          # Ask napt whether the new version is lower than the published
          # one. It orders versions exactly as the detection script on a
          # device does, so the workflow never carries its own copy.
          status = json.loads(
              subprocess.run(
                  ["napt", "status", "--format", "json"],
                  capture_output=True, text=True, check=True,
              ).stdout
          )
          row = next(r for r in status if r["app_id"] == state_path.stem)
          warning = suffix = ""
          if row["pending_is_downgrade"]:
              suffix = f" (downgrade from {current})"
              warning = (
                  f"**This is a downgrade:** {pending['version']} is "
                  f"lower than the published {current}. Devices already "
                  f"on {current} will not move to it; merging changes "
                  "what new installs get.\n\n"
              )
          Path("pr-body.md").write_text(
              f"{warning}"
              f"**Name:** {name}\n"
              f"**New version:** {pending['version']}\n"
              f"**Currently published:** {current}\n"
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
          print(f"Publish {name} {pending['version']}{suffix}")
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
      - name: Fail the run if any recipe failed to discover
        shell: bash
        run: |
          [ -s discover-failures.txt ] || exit 0
          echo "Discovery failed for:"
          cat discover-failures.txt
          exit 1
```

One recipe's failure does not hold up the others: the discover step records
it, the PR step still opens publish PRs for every app that did discover a new
release, and the final step fails the run so the failure is not missed.
Each failed recipe is also annotated on the run summary.

### Workflow 2: publish (on merge of a publish PR)

```yaml
name: publish
on:
  push:
    branches: [main]
    paths: ["state/deployment/**"]
# Serializes publish runs (bursts of merges dedupe to the newest run).
# Deliberately NOT shared with promote-apply: a merge that touches both
# deployment state and plan files triggers both workflows, and runs
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
          path: downloads
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
            # the approved pending untouched, and napt build refuses any
            # file that does not match it. Downloads are filed by version
            # (downloads/<id>/<version>/<file>), hence the two-level glob.
            psha=$(python -c "import json, sys; print(json.load(open(sys.argv[1], encoding='utf-8'))['pending']['sha256'])" "$state")
            if ! sha256sum "downloads/$id/"*/* 2>/dev/null | grep -q "^$psha "; then
              napt discover "$recipe" --stateless
              # Fail fast when the vendor no longer serves the approved
              # binary (napt build would refuse it anyway).
              sha256sum "downloads/$id/"*/* 2>/dev/null | grep -q "^$psha " || {
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
exact binary; a pulled or replaced file strands the approval at the
hash gate.
The cache steps above hand the publish runner the very binary that was
reviewed; the sha256 check in the loop falls back to a fresh download
when the cache is stale or evicted (GitHub evicts caches unused for
about a week), so the flow degrades gracefully.
This is safe by construction: the upload hash gate validates whatever
binary the runner provides, so a cache can never ship the wrong bytes.

The restore step in the discover workflow serves a second purpose:
bandwidth.
`napt discover` skips the download when the installer has not changed;
[Skipping downloads](user-guide.md#skipping-downloads) explains how.
Everything it consults lives in `downloads/`, and a fresh runner starts
without it, so restoring `downloads/` from the last run is what lets the
scheduled discover skip re-downloading installers that have not changed,
which adds up quickly for recipe sets full of large installers.
Keep the `path` values of the save and restore steps identical:
`actions/cache` makes the path list part of the cache version, so a
mismatch reads as a silent cache miss.

For long-lived archival (including installers for retained releases the
vendor no longer serves) replace the cache steps with an object store
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
        # warnings. Actions' `shell: bash` runs with -eo pipefail, so
        # napt's exit code survives the pipe.
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
          git checkout -B napt/promote-plan origin/main
          git add state
          git commit -m "feat: Plan ring promotions"
          git push -f origin napt/promote-plan
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
          gh pr create --head napt/promote-plan \
            --title "Promotion plan" --body-file pr-body.md \
            || gh pr edit napt/promote-plan --body-file pr-body.md
          if [ "$label" = "production" ]; then
            gh label create promotes-to-production \
              --description "This plan assigns the final ring" \
              --color D93F0B --force
            gh pr edit napt/promote-plan --add-label promotes-to-production
          else
            gh pr edit napt/promote-plan \
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
      # have applied; continue so the writeback records their ring
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
  file on `main` for the next apply, and never blocks the other apps,
  which is why the writeback above runs even when the apply step fails.
- Resolving a failed app depends on the failure class.
  A transient Graph error needs no fix: re-run the apply workflow;
  already-applied actions skip, the rest complete, and the plan file is
  consumed.
  An unresolvable group needs the configuration fixed (or the Entra ID
  group restored) and then a re-plan, not just a re-run: plan files bake
  in group names at plan time, so the fix reaches Intune when the next
  scheduled plan regenerates the file and the promotion PR carries the
  corrected plan.
  Until then, apply keeps failing that one app, and only that one.
  A corrupted state file restores from git history like any other
  committed file.
- All four workflows are idempotent: re-running any of them converges
  to the same result (upload adopts existing apps, apply skips
  already-applied actions).
- A publish whose writeback push fails (branch protection, a crashed
  runner) self-heals: the next plan run's `--reconcile` re-records the
  publication from tenant evidence, the promotion PR carries the repair,
  and the recovered release is planned for its first ring in the same
  run. Re-running the failed publish also converges, just sooner.
- `windows-latest` runners are required for `napt package`
  (IntuneWinAppUtil.exe is Windows-only). The discover workflow alone
  could run on Linux with `msitools` installed, since discover reads the
  version out of every MSI it downloads.

## Share a base recipe between apps

When several recipes differ only in a few fields, put the shared part in
one file and name it as the `parent` of each app recipe.

1. Write the base in a folder outside `recipes/`, so neither the workflows
   nor `napt promote` pick it up as an app.
   It needs `apiVersion`, `name`, `id`, and a `discovery` block only
   because NAPT validates it as a recipe.
   ```yaml
   # recipe-bases/chromium-family.yaml
   apiVersion: napt/v1
   name: "Chromium base"
   id: "chromium-base"
   discovery:
     strategy: url_download
     url: "https://example.com/placeholder.msi"
   psadt:
     app_vars:
       AppProcessesToClose: ["chrome", "msedge"]
   intune:
     detection:
       exact_match: false
   ```

2. Write each app as a child named `<app>.override.yaml` that sets its own
   `name` and `id` and only what else differs.
   The `parent` path is relative to the child:
   ```yaml
   # recipes/Google/chrome.override.yaml
   apiVersion: napt/v1
   parent: ../../recipe-bases/chromium-family.yaml
   name: "Google Chrome"
   id: "napt-chrome"
   discovery:
     url: "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"
   ```
   The child replaces the app's plain recipe: delete
   `recipes/Google/chrome.yaml` when you add it.
   Two files with one `id` stop `napt promote` for every app.

3. Validate the child.
   The output names the parent it merged:
   ```bash
   napt validate recipes/Google/chrome.override.yaml
   ```

Run every command against the child, never the base.
The merge order and list behavior are in
[Configuration layers](user-guide.md#configuration-layers).

## Troubleshoot discovery failures

### Issue: "Unknown discovery strategy"

**Problem:** Recipe uses a strategy that doesn't exist or isn't registered.

**Solution:**

1. Check strategy name spelling (must be: `api_github`, `api_json`,
   `url_download`, or `web_scrape`)

2. Validate recipe: `napt validate recipes/App/app.yaml`

### Issue: "Failed to extract the version" or "Version path ... did not match"

**Problem:** NAPT can't extract the version from the downloaded file or API
response.

**Solution:**

1. Use `--debug` to see what NAPT is trying to parse:

   ```bash
   napt discover recipes/App/app.yaml --debug
   ```

2. For MSI files, verify the file is a valid MSI

3. For `api_json`, check that `version_path` points to the correct JSON field

4. For `web_scrape`, verify `version_pattern` regex matches the URL format

### Issue: "Version ... does not start with a number"

**Problem:** The discovered version starts with something other than a digit
(for example, `v2.0` or `latest`).
Devices compare versions numerically and would read it as 0.

**Solution:** Tighten `version_pattern` so its capture group keeps only the
part from the first digit on; the error message suggests the value.
For `api_json`, also check that `version_path` points at the version field.
See the strategy's fields in
[Discovery configuration](recipe-reference.md#discovery-configuration).

### Issue: "Discovered version ... cannot be used as a folder name"

**Problem:** The version contains characters other than letters, digits,
`.`, `-`, `_`, and `+`, so NAPT cannot use it as a download folder name.

**Solution:** Narrow `version_pattern` (or, for `api_json`, `version_path`)
so it captures only the version.
If the version comes from the installer itself (MSI or MSIX), check the
installer's metadata.

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
3. Set `GITHUB_TOKEN` in your environment (see
   [Handle authentication tokens](#handle-authentication-tokens))

### Issue: "download failed for ..."

**Problem:** Can't download the installer file.

**Solution:**

1. Check URL is accessible: `curl -I <url>` or open in browser

2. For `api_json` or `api_github`, check the token (see
   [Handle authentication tokens](#handle-authentication-tokens))

3. Use `--verbose` to see HTTP request/response details

### Issue: discover reuses an installer you want downloaded again

**Problem:** `napt discover` reports that the version is already downloaded
(or `File not modified`) and you want a fresh copy.

**Solution:**

Delete the app's folder and rediscover.
If a pending release is awaiting approval and the vendor no longer serves
it, keep that version's folder: build needs that exact file.

```bash
rm -r downloads/<app_id>
napt discover recipes/app.yaml
```

### Issue: "Corrupted deployment state file"

**Problem:** A file under `state/deployment/` has invalid JSON.

**Solution:**

Deployment state files are authoritative and are never auto-replaced.
Fix the JSON or restore the file from version control.

To run discovery once without reading or writing deployment state, use
`--stateless`:

```bash
napt discover recipes/app.yaml --stateless
```

### Issue: MSI version extraction fails on Linux/macOS

**Problem:** `napt discover` or `napt build` cannot read the MSI
ProductVersion on a non-Windows machine.

**Solution:** Install `msitools`, which provides the `msiinfo` backend:

```bash
sudo apt-get install msitools  # Debian/Ubuntu
sudo dnf install msitools      # RHEL/Fedora
brew install msitools          # macOS
```

## Related pages

- [User guide](user-guide.md): how discovery, state, and configuration work
- [Recipe reference](recipe-reference.md): every recipe field
- [Examples](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes):
  working recipes
