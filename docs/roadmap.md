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
| Microsoft Intune Upload | ✅ Completed | User-Facing | High | Very High |
| Deployment Wave Management | 🔬 Investigating | User-Facing | Very High | High |
| Pre/Post Install/Uninstall Script Support | 💡 Idea | User-Facing | Low | Medium |
| Enhanced CLI Help Menu | 💡 Idea | User-Facing | Low | Medium |
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
- 📋 **Ready**: 0
- 🔬 **Investigating**: 1
- 💡 **Ideas**: 10
- **Total**: 12 features

---

## Active Work

### Completed ✅

#### Microsoft Intune Upload
**Complexity**: High
**Value**: Very High

**Description**: `napt upload <recipe>` uploads `.intunewin` packages directly to
Microsoft Intune via the Graph API. Authentication is automatic via
`azure-identity` (`EnvironmentCredential` → `ManagedIdentityCredential` →
`AzureCliCredential`). Detection and requirements scripts are embedded inline
from build output. No auth configuration required — run `az login` for dev,
set `AZURE_*` env vars for CI/CD.

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
