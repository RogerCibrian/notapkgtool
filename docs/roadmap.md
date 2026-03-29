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
| Recipe Schema Redesign | ✅ Completed | User-Facing | High | High |
| Microsoft Intune Upload | ✅ Completed | User-Facing | High | Very High |
| `napt auth setup` Command | 💡 Idea | User-Facing | Low | High |
| Deployment Wave Management | 🔬 Investigating | User-Facing | Very High | High |
| Pre/Post Install/Uninstall Script Support | 💡 Idea | User-Facing | Low | Medium |
| Enhanced CLI Help Menu | 💡 Idea | User-Facing | Low | Medium |
| Intune Upload Settings Overrides | 💡 Idea | User-Facing | Low | Medium |
| PowerShell Validation | 💡 Idea | Code Quality | High | High |
| Recipe Linting & Best Practices | 💡 Idea | Code Quality | High | Medium |
| Unrecognized Config Field Warnings | ✅ Completed | Code Quality | Low | Medium |
| Typed Config with Dataclasses | 💡 Idea | Code Quality | Medium | Medium |
| EXE Version Extraction | 💡 Idea | Technical | High | Medium |
| Parallel Package Building | 💡 Idea | Technical | Medium | Medium |
| IntuneWinAppUtil Version Tracking | 💡 Idea | Technical | Low | Low |
| Minify Scripts at Intune Upload | 💡 Idea | Technical | Medium | Medium |

**Summary:**

- ✅ **Completed**: 3
- 🔬 **Investigating**: 1
- 💡 **Ideas**: 11
- **Total**: 15 features

---

## Active Work

### Investigating 🔬

#### Deployment Wave Management

**Status**: 🔬 Investigating

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

**Related**: `intune.detection.architecture` drives default Intune targeting;
see [Recipe Reference](recipe-reference.md#architecture)

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
- Warns about unknown fields (e.g., deprecated keys from old schema versions)


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

- Requires Intune upload implementation (or a separate "prepare for upload" step that emits minified content)

**Related**: Intune default policy limit is 4 MB total; NAPT detection + requirements scripts are ~40 KB per app (~70–100 apps depending on code signing)

---

## Declined / Won't Implement

---

## Recently Completed

#### Recipe Schema Redesign ✅

**Status**: ✅ Completed

**Complexity**: High

**Value**: High

**Description**: Restructured the recipe and config schema to eliminate design
awkwardness accumulated during early development. All changes were breaking and
landed on branch `refactor/recipe-schema-redesign`.

**Changes made:**

- Removed `app:` wrapper — `name`, `id`, `discovery:`, `psadt:`, `intune:`, and
    `logging:` are now top-level fields in recipe files.
- `source:` renamed to `discovery:` for clarity.
- Removed `defaults:` wrapper from `org.yaml` and `vendor.yaml` — the deep
    merger now handles layering automatically without manual merge blocks.
- `win32.installed_check` replaced by `intune.detection` — all Intune
    configuration (upload metadata, build behavior, detection settings) is now
    in one place.
- `log_format`, `log_level`, `log_rotation_mb` moved out of `win32.installed_check`
    into a top-level `logging:` section, reflecting that they configure on-device
    script behavior rather than Intune.
- Added `directories:` section to replace `defaults.discover/build/package.output_dir`.

**Related**: See [Recipe Reference](recipe-reference.md) for the current schema.

---

#### Unrecognized Config Field Warnings ✅

**Status**: ✅ Completed

**Complexity**: Low

**Value**: Medium

**Description**: `napt validate` warns when recipes, org.yaml, or vendor files contain
unrecognized fields. Typo detection suggests similar field names
(e.g., "Did you mean 'display_name'?"). Implemented in `napt/validation.py`.

---

#### Microsoft Intune Upload ✅

**Status**: ✅ Completed

**Complexity**: High

**Value**: Very High

**Description**: `napt upload <recipe>` uploads `.intunewin` packages directly to
Microsoft Intune via the Graph API. Authentication is automatic via
`azure-identity` (`EnvironmentCredential` → `ManagedIdentityCredential` →
`DeviceCodeCredential`). Detection and requirements scripts are embedded inline
from build output. Developers set `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` and
complete the device code flow; CI/CD sets all three `AZURE_*` env vars.

---

#### Detection Script Generation ✅

**Status**: ✅ Completed

**Complexity**: High (3-5 days)

**Value**: High

**Description**: Automatic PowerShell detection and requirements script generation for Intune Win32 app deployments during build process. Detection scripts check if the app is installed at the required version (App entry); requirements scripts check if an older version is installed (Update entry). Both use the same registry checks, installer-type filtering, and CMTrace logging.

**Implementation Details**:

- Extracts app name from MSI ProductName (for MSI installers) or uses `intune.detection.display_name` (for non-MSI installers)
- Always generates detection script `{AppName}_{Version}-Detection.ps1`; generates requirements script `{AppName}_{Version}-Requirements.ps1` when `intune.build_types` is both or update_only
- Supports exact match or minimum version (installed >= expected); installer-type filtering (MSI strict, non-MSI permissive)
- Includes CMTrace-formatted logging with log rotation (NAPTDetections.log, NAPTRequirements.log)
- Configurable via `intune.detection` and `logging` sections in defaults or recipe

**Related**: Implemented in `napt/detection.py`, `napt/requirements.py`, and integrated into build process in `napt/build/manager.py`. See [User Guide - Detection and Requirements Scripts](user-guide.md#detection-and-requirements-scripts) and [Recipe Reference - Intune Configuration](recipe-reference.md#intune-configuration).

---

**v0.2.0** - PSADT building, packaging, and new discovery strategies
**v0.1.0** - Core validation, discovery, and configuration system

See [CHANGELOG.md](changelog.md) for detailed release history.
