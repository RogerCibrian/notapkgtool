# NAPT Roadmap

## Philosophy

This roadmap is a living document showing potential future directions for NAPT. Features listed here are **ideas and possibilities, not commitments**. Priorities may shift based on:

- User feedback and real-world usage
- Discovered technical challenges or opportunities
- New insights from development experience
- Community contributions

**Status Legend:**

- 💡 **Idea**: Unformed thought, needs refinement
- 🔬 **Investigating**: Researching feasibility/approach
- 📋 **Ready**: Well-defined, ready for implementation
- 🚧 **In Progress**: Actively being developed
- ✅ **Completed**: Implemented and released

---

## Quick Reference

| Feature | Status | Category | Complexity | Value |
|---------|--------|----------|------------|-------|
| Recipe Schema Redesign | 📋 Ready | User-Facing | High | High |
| Microsoft Intune Upload | ✅ Completed | User-Facing | High | Very High |
| `napt auth setup` Command | 💡 Idea | User-Facing | Low | High |
| Deployment Wave Management | 🔬 Investigating | User-Facing | Very High | High |
| Pre/Post Install/Uninstall Script Support | 💡 Idea | User-Facing | Low | Medium |
| Enhanced CLI Help Menu | 💡 Idea | User-Facing | Low | Medium |
| Intune Upload Settings Overrides | 💡 Idea | User-Facing | Low | Medium |
| PowerShell Validation | 💡 Idea | Code Quality | High | High |
| Recipe Linting & Best Practices | 💡 Idea | Code Quality | High | Medium |
| Unrecognized Config Field Warnings | 💡 Idea | Code Quality | Low | Medium |
| Typed Config with Dataclasses | 💡 Idea | Code Quality | Medium | Medium |
| EXE Version Extraction | 💡 Idea | Technical | High | Medium |
| Parallel Package Building | 💡 Idea | Technical | Medium | Medium |
| IntuneWinAppUtil Version Tracking | 💡 Idea | Technical | Low | Low |
| Minify Scripts at Intune Upload | 💡 Idea | Technical | Medium | Medium |

**Summary:**

- ✅ **Completed**: 1
- 📋 **Ready**: 1
- 🔬 **Investigating**: 1
- 💡 **Ideas**: 12
- **Total**: 15 features

---

## Active Work

### Completed ✅

#### Microsoft Intune Upload
**Complexity**: High
**Value**: Very High

**Description**: `napt upload <recipe>` uploads `.intunewin` packages directly to
Microsoft Intune via the Graph API. Authentication is automatic via
`azure-identity` (`EnvironmentCredential` → `ManagedIdentityCredential` →
`DeviceCodeCredential`). Detection and requirements scripts are embedded inline
from build output. Developers set `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` and
complete the device code flow; CI/CD sets all three `AZURE_*` env vars.

### Investigating 🔬

#### Deployment Wave Management
**Complexity**: Very High (5-10 days)  
**Value**: High

**Description**: Phased deployment with rings (Pilot → Production) and gradual rollout.

**Benefits**:

- Enables controlled, staged deployments to reduce risk
- Supports ring-based deployment (Pilot, UAT, Production)
- Allows gradual rollout with percentage-based scheduling
- Provides rollback capabilities for failed deployments
- Useful for organizations requiring careful change management

**Dependencies**:

- Requires Intune upload implementation first
- Requires Graph API for assignment groups
- May need separate monitoring/alerting

---

## Future Ideas (By Category)

> **Note:** Categories are organized by how they impact users:
>
> - **User-Facing Features**: Features and improvements that directly help recipe developers use NAPT more effectively, including new capabilities, UX enhancements, documentation, and tooling.
> - **Code Quality & Validation**: Tools that validate and improve recipe quality, including syntax checking, linting, and best practices enforcement.
> - **Technical Enhancements**: Internal improvements and infrastructure enhancements that improve performance, add backend capabilities, or optimize the tool's operation.

### User-Facing Features

#### Recipe Schema Redesign

**Status**: 📋 Ready
**Complexity**: High (3-5 days)
**Value**: High

**Description**: Restructure the recipe and config schema to eliminate design
awkwardness that accumulated during early development.
All changes are breaking; do this in a dedicated branch before v1.0.0.
Suggested branch: `refactor/recipe-schema-redesign`.

**Problems being solved:**

- The `defaults:` wrapper in `org.yaml` and `vendor.yaml` is redundant.
    The file is already called `defaults/org.yaml`.
    The wrapper also forces org-level settings (e.g., `defaults.psadt.*`) and
    recipe-level settings (e.g., `app.psadt.*`) onto different paths, requiring
    manual merging blocks throughout the codebase
    (see `_generate_detection_script` and `_generate_requirements_script` in
    `napt/build/manager.py`).
- `app.win32.installed_check` nests Intune detection configuration under a
    vague `win32` key.
    Everything in `installed_check` generates Intune detection and requirements
    scripts and belongs alongside other Intune configuration.
- `log_format`, `log_level`, and `log_rotation_mb` are inside
    `win32.installed_check` despite configuring on-device script behavior, not
    Intune.
    They apply equally to both detection and requirements scripts.
- The `intune:` section only holds upload metadata while detection
    configuration lives in `app.win32.installed_check` — all of it is
    Intune-specific but split across two unrelated locations.

**Target schema — three top-level sections alongside `app:`:**

```yaml
# defaults/org.yaml — no defaults: wrapper
apiVersion: napt/v1

psadt:
  release: "latest"
  app_vars:
    AppScriptAuthor: "IT Team"

intune:
  minimum_supported_windows_release: "21H2"
  build_types: "both"
  detection:
    exact_match: false

logging:
  log_format: "cmtrace"
  log_level: "INFO"
  log_rotation_mb: 3
```

```yaml
# recipes/Google/chrome.yaml (MSI — intune.detection omitted, auto-detected)
apiVersion: napt/v1

app:
  name: "Google Chrome"
  id: "napt-chrome"
  source:
    strategy: url_download
    url: "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"
  psadt:
    install: |
      Start-ADTMsiProcess -Action Install -Path "$dirFiles\googlechromestandaloneenterprise64.msi" -Parameters "ALLUSERS=1"
    uninstall: |
      Uninstall-ADTApplication -Name "Google Chrome"

psadt:
  app_vars:
    AppName: "Google Chrome"
    AppVersion: "${discovered_version}"

intune:
  publisher: "Google"
```

```yaml
# recipes/Git/git.yaml (EXE — intune.detection required)
apiVersion: napt/v1

app:
  name: "Git for Windows"
  id: "napt-git"
  source:
    strategy: api_github
    repo: "git-for-windows/git"
    asset_pattern: "Git-.*-64-bit\\.exe$"
    version_pattern: "v?([0-9.]+)\\.windows"
  psadt:
    install: |
      Start-ADTProcess -Path "$dirFiles\Git-${discovered_version}-64-bit.exe" -Parameters "/VERYSILENT /NORESTART"
    uninstall: |
      Uninstall-ADTApplication -Name "Git"

psadt:
  app_vars:
    AppName: "Git for Windows"
    AppVersion: "${discovered_version}"

intune:
  publisher: "Git"
  detection:
    display_name: "Git"
    architecture: "x64"
```

**Key design decisions:**

- `app:` contains only app identity and deployment scripts
    (`source:`, `psadt.install`, `psadt.uninstall`).
    No Intune or logging knowledge.
- `psadt:` at the top level holds PSADT variables (`app_vars`) and settings
    (`release`) that benefit from org/vendor/recipe layering.
    Since org.yaml and recipes now share the same top-level keys, the deep
    merger handles layering automatically — no manual merging needed.
- `intune:` holds everything driven by or sent to the Intune API:
    upload metadata (`publisher`, `description`,
    `minimum_supported_windows_release`), build behavior (`build_types`), and
    `detection:` (what the scripts check: `display_name`, `architecture`,
    `exact_match`).
    For MSI installers, `intune.detection` is omitted entirely — display name
    and architecture are auto-detected from the MSI `Template` property.
- `logging:` holds on-device script execution settings: `log_format`,
    `log_level`, `log_rotation_mb`.
    These apply equally to detection and requirements scripts and are not
    Intune-specific.
    `logging:` was chosen over `endpoint:` or `scripts:` because it accurately
    describes the current scope.
    If non-logging endpoint script settings are added later, reconsider the
    name at that time.

**Benefits:**

- Recipes are significantly simpler — `app:` is clean and self-contained
- No more `defaults:` nesting indentation in org.yaml and vendor.yaml
- All Intune configuration in one place
- Manual merge blocks in `napt/build/manager.py` can be deleted
- Consistent mental model: `intune:` = what goes to Intune,
    `logging:` = what runs on the device

**Files to change:**

- `napt/config/defaults.py` — restructure `DEFAULT_CONFIG` and
    `ORG_YAML_TEMPLATE` to match new schema
- `napt/config/loader.py` — remove any special-casing for `defaults:` key
- `napt/validation.py` — update all section schemas and field paths
- `napt/build/manager.py` — remove manual merge blocks, read from new paths
- `napt/upload/manager.py` — read `intune.*` and `logging.*` from new paths
- `napt/detection.py` and `napt/requirements.py` — update config key references
- `defaults/org.yaml` — rewrite to new schema
- `recipes/**/*.yaml` — migrate all recipes to new schema
- `docs/recipe-reference.md` — rewrite Win32 Configuration and Intune
    Configuration sections to reflect new structure
- `docs/common-tasks.md`, `docs/user-guide.md` — update all config examples
- `tests/` — update config fixtures and validation tests

#### `napt auth setup` Command

**Status**: 💡 Idea
**Complexity**: Low (few hours to 1 day)
**Value**: High

**Description**: Automates app registration creation in Microsoft Entra ID
using the Azure CLI.
Runs `az ad app create`, adds `DeviceManagementApps.ReadWrite.All` application
and delegated permissions, grants admin consent, and outputs the `AZURE_CLIENT_ID`
and `AZURE_TENANT_ID` values to set.
Creates a natural namespace for future `napt auth status` and `napt auth logout`
subcommands.

**Benefits**:

- Reduces one-time setup from a multi-step portal workflow to a single command
- Requires only `az login` as a prerequisite — no portal navigation needed
- Outputs exact env vars to set, eliminating copy-paste errors
- Enables future auth management subcommands

**Prerequisites**:

- Azure CLI installed and authenticated with an account that can create app registrations

#### Intune Upload Settings Overrides

**Status**: 💡 Idea
**Complexity**: Low (few hours to 1 day)
**Value**: Medium

**Description**: Expose per-recipe overrides for Intune upload settings that
currently use fixed defaults.
Planned fields under `intune:`:

- `allowed_architectures` — override device targeting (e.g., `"x64"` to
exclude ARM64 for apps with known emulation issues)
- `requirement_rule.display_name` — custom display name for the requirements
rule shown in the Intune portal
- `requirement_rule.run_as_account` — `system` or `user` context for the
requirements script
- `requirement_rule.run_as_32_bit` — run requirements script as 32-bit process
- `requirement_rule.enforce_signature_check` — require a signed requirements
script

**Benefits**:

- Fine-grained control over deployment targeting without changing the recipe
architecture field
- Handles edge cases (apps with x64 emulation issues on ARM64, per-app
requirement rule naming)
- Consistent with NAPT's layered config approach — overrides at recipe level,
defaults at org level

**Related**: `architecture` field in `win32.installed_check` drives default
Intune targeting; see [Recipe Reference](recipe-reference.md#architecture)

#### Pre/Post Install/Uninstall Script Support
**Status**: 💡 Idea  
**Complexity**: Low (few hours to 1 day)  
**Value**: Medium

**Description**: Add support for pre-install, post-install, pre-uninstall, and post-uninstall script blocks in recipes, allowing separate script sections for each deployment phase.

**Benefits**:

- More granular control over deployment lifecycle
- Separation of concerns (prep vs install vs cleanup)
- Aligns with PSADT's deployment phase structure
- Cleaner recipe organization
- Enables better error handling and rollback capabilities

**Related**: PSADT already has these phases in the template structure

#### Enhanced CLI Help Menu
**Status**: 💡 Idea  
**Complexity**: Low (few hours to 1 day)  
**Value**: Medium

**Description**: Improve the `napt -h` help output with more detailed information, examples, and better organization.

**Benefits**:

- Better discoverability of features
- Reduces need to consult docs for basic usage
- Improves new user onboarding experience
- Quick reference for command options
- Examples for common workflows directly in help text
- Grouped commands by category (Discovery, Building, Packaging)
- Tips for troubleshooting (--verbose, --debug flags)

**Related**: CLI help currently minimal, relies on online documentation

### Code Quality & Validation

#### PowerShell Validation
**Status**: 💡 Idea  
**Complexity**: High (3-5 days)  
**Value**: High

**Description**: Validate PowerShell syntax in recipe install/uninstall blocks to catch errors before deployment.

**Benefits**:

- Catch syntax errors at recipe validation time
- Prevent broken deployments
- Better developer experience
- Reduces debugging time during deployment

**Related**: TODO in `napt/build/packager.py` - discovered during testing

#### Recipe Linting & Best Practices
**Status**: 💡 Idea
**Complexity**: High (3-5 days)
**Value**: Medium

**Description**: Advanced recipe validation beyond syntax checking, including PSADT function validation, deprecation warnings, anti-pattern detection, and style guide enforcement.

**Benefits**:

- Higher quality recipes
- Consistent code style across all recipes
- Educational for new users
- Validates PSADT function names exist in v4
- Warns on deprecated patterns or old v3 functions
- Suggests improvements (e.g., use Uninstall-ADTApplication)
- Warns about unknown fields at app level (e.g., deprecated `detection` vs `win32.installed_check`)

#### Unrecognized Config Field Warnings
**Status**: 💡 Idea
**Complexity**: Low (few hours to 1 day)
**Value**: Medium

**Description**: Warn users when config files (org.yaml, vendor files, recipes) contain unrecognized fields.
Helps catch typos, deprecated fields, and fields from newer NAPT versions.

**Benefits**:

- Catches typos early (e.g., `pstdt` instead of `psadt`)
- Alerts users to deprecated fields they should migrate
- Identifies fields from newer NAPT versions when running older versions
- Helps maintain clean, intentional configuration
- Warning (not error) allows forward compatibility while informing users

#### Typed Config with Dataclasses
**Status**: 💡 Idea
**Complexity**: Medium (1-3 days)
**Value**: Medium

**Description**: Convert the dict-based default configuration to typed dataclasses once the schema and naming are finalized.
Provides IDE autocomplete, type checking, and catches config key typos at development time.

**Benefits**:

- IDE autocomplete when accessing config values
- Type checking with mypy catches errors early
- Typos in config keys caught by IDE instead of runtime
- Self-documenting structure with type hints
- Better refactoring support

**Prerequisites**:

- Schema should be stable (post-1.0 or when churn slows)
- Current dict approach works well for rapid iteration

### Technical Enhancements

#### EXE Version Extraction
**Status**: 💡 Idea  
**Complexity**: High (3-5 days)  
**Value**: Medium

**Description**: Extract version information from PE (Portable Executable) headers for .exe installers.

**Benefits**:

- Enables version discovery for applications distributed as EXE
- Useful for vendors who don't provide version in URL or API

**Related**: Mentioned in `napt/discovery/url_download.py` docstring

#### Parallel Package Building
**Status**: 💡 Idea  
**Complexity**: Medium (1-3 days)  
**Value**: Medium

**Description**: Build multiple PSADT packages in parallel for faster multi-app workflows.

**Benefits**:

- Significantly faster builds for organizations with 50+ apps
- Reduces time for monthly update cycles
- Improves CI/CD pipeline performance
- Progress reporting for multiple concurrent builds

#### IntuneWinAppUtil Version Tracking
**Status**: 💡 Idea  
**Complexity**: Low (few hours to 1 day)  
**Value**: Low

**Description**: Track version of IntuneWinAppUtil.exe in cache metadata instead of always using latest from master, allowing pinning to specific commits/releases and optional configuration for tool version/source.

**Benefits**:

- Reproducible builds (pin to known-good version)
- Control over tool updates
- Better for air-gapped environments
- Auto-detect when tool updates are available

**Related**: TODO in `napt/build/packager.py:47`

#### Minify Scripts at Intune Upload
**Status**: 💡 Idea  
**Complexity**: Medium (1-3 days)  
**Value**: Medium

**Description**: Minify detection and requirements scripts in memory when preparing them for Intune upload, so the payload sent to Intune is smaller while on-disk build output stays readable. Conservative approach: strip comment-only lines, blank lines, and trailing whitespace (no AST). Optional: PowerShell-invoked AST-based minifier for greater reduction.

**Benefits**:

- Reduces per-app script size in the Intune policy payload
- Helps organizations approaching the Intune 4 MB policy limit
- On-disk scripts remain readable and easy to debug
- No change to build output or script behavior; minification only in the upload path

**Dependencies**:

- Requires Intune upload implementation (or a separate “prepare for upload” step that emits minified content)

**Related**: Intune default policy limit is 4 MB total; NAPT detection + requirements scripts are ~40 KB per app (~70–100 apps depending on code signing)

---

## Declined / Won't Implement

---

## Recently Completed

#### Detection Script Generation ✅
**Status**: ✅ Completed  
**Complexity**: High (3-5 days)  
**Value**: High

**Description**: Automatic PowerShell detection and requirements script generation for Intune Win32 app deployments during build process. Detection scripts check if the app is installed at the required version (App entry); requirements scripts check if an older version is installed (Update entry). Both use the same registry checks, installer-type filtering, and CMTrace logging.

**Implementation Details**:

- Extracts app name from MSI ProductName (for MSI installers) or uses `win32.installed_check.display_name` (for non-MSI installers)
- Always generates detection script `{AppName}_{Version}-Detection.ps1`; generates requirements script `{AppName}_{Version}-Requirements.ps1` when `win32.build_types` is both or update_only
- Supports exact match or minimum version (installed >= expected); installer-type filtering (MSI strict, non-MSI permissive)
- Includes CMTrace-formatted logging with log rotation (NAPTDetections.log, NAPTRequirements.log)
- Configurable via `win32.installed_check` section in defaults or recipe

**Related**: Implemented in `napt/detection.py`, `napt/requirements.py`, and integrated into build process in `napt/build/manager.py`. See [User Guide - Detection and Requirements Scripts](user-guide.md#detection-and-requirements-scripts) and [Recipe Reference - Win32 Configuration](recipe-reference.md#win32-configuration).

---

**v0.2.0** - PSADT building, packaging, and new discovery strategies  
**v0.1.0** - Core validation, discovery, and configuration system

See [CHANGELOG.md](changelog.md) for detailed release history.
