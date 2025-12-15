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
| Microsoft Intune Upload | 🔬 Investigating | User-Facing | High | Very High |
| Deployment Wave Management | 🔬 Investigating | User-Facing | Very High | High |
| Detection Script Generation | 💡 Idea | User-Facing | High | High |
| Pre/Post Install/Uninstall Script Support | 💡 Idea | User-Facing | Low | Medium |
| Enhanced CLI Help Menu | 💡 Idea | User-Facing | Low | Medium |
| PowerShell Validation | 💡 Idea | Code Quality | High | High |
| Recipe Linting & Best Practices | 💡 Idea | Code Quality | High | Medium |
| One App Per Recipe File | 💡 Idea | Technical | Medium | Medium |
| EXE Version Extraction | 💡 Idea | Technical | High | Medium |
| Parallel Package Building | 💡 Idea | Technical | Medium | Medium |
| IntuneWinAppUtil Version Tracking | 💡 Idea | Technical | Low | Low |

**Summary:**

- 📋 **Ready**: 0
- 🔬 **Investigating**: 2
- 💡 **Ideas**: 9
- **Total**: 11 features

---

## Active Work

### Investigating 🔬

#### Microsoft Intune Upload
**Complexity**: High (3-5 days)  
**Value**: Very High

**Description**: Direct upload of .intunewin packages to Microsoft Intune via Graph API. Requires research into authentication strategies (OAuth, service principal, managed identity), Graph API endpoints and permissions, Win32 app metadata requirements, error handling, and rate limiting.

**Benefits**:

- Streamlines deployment workflow by eliminating manual upload steps
- Enables automation of Intune app publishing
- Reduces time from package creation to deployment
- Useful for organizations managing multiple apps and frequent updates

**Dependencies**:

- Requires Azure AD app registration
- May need different authentication approaches for different deployment scenarios

**Related**:

- [Microsoft Graph API - Win32 Apps](https://learn.microsoft.com/en-us/graph/api/resources/intune-apps-win32lobapp)
- [Intune App Upload Process](https://learn.microsoft.com/en-us/mem/intune/apps/apps-win32-app-management)

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

#### Detection Script Generation
**Status**: 💡 Idea  
**Complexity**: High (3-5 days)  
**Value**: High

**Description**: Automatically generate detection scripts for Intune that check if an application is already installed.

**Benefits**:

- Reduces manual work for Intune app creation
- Ensures consistent detection logic across all apps
- Leverages information we already have (ProductCode, version, paths)
- Supports both MSI and EXE installers with appropriate detection methods
- Prevents re-installation of already-installed apps
- Enables version-based detection for upgrades
- Useful for organizations creating multiple Win32 apps in Intune

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

**Related**: TODO in `notapkgtool/build/packager.py` - discovered during testing

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

#### One App Per Recipe File
**Status**: 💡 Idea  
**Complexity**: Medium (1-2 days)  
**Value**: Medium

**Description**: Change recipe schema to require exactly one app per recipe file (currently supports multiple but only processes first). Update validation, schema, and documentation to reflect single-app requirement.

**Benefits**:

- Simpler recipe structure (one file = one app)
- Clearer semantics (no confusion about which app is processed)
- Simplifies code that currently uses `apps[0]`
- Better organization (one recipe file per application)
- Easier to reason about and maintain

**Related**: Current implementation already processes only `apps[0]`, this would make schema match behavior

### Technical Enhancements

#### EXE Version Extraction
**Status**: 💡 Idea  
**Complexity**: High (3-5 days)  
**Value**: Medium

**Description**: Extract version information from PE (Portable Executable) headers for .exe installers.

**Benefits**:

- Enables version discovery for applications distributed as EXE
- Useful for vendors who don't provide version in URL or API

**Related**: Mentioned in `notapkgtool/discovery/url_download.py` docstring

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

**Related**: TODO in `notapkgtool/build/packager.py:47`

---

## Declined / Won't Implement

---

## Recently Completed

**v0.2.0** - PSADT building, packaging, and new discovery strategies  
**v0.1.0** - Core validation, discovery, and configuration system

See [CHANGELOG.md](changelog.md) for detailed release history.
