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

## Ideas (Not Assigned to Release)

### PowerShell Validation
**Status**: 💡 Idea  
**Complexity**: Medium (2-3 days)  
**Value**: High

**Description**: Validate PowerShell syntax in recipe install/uninstall blocks to catch errors before deployment.

**Approach Options**:
- Basic structural checks (balanced braces, quotes)
- PowerShell parser integration (PSParser tokenizer)
- Hybrid: Basic checks + optional advanced validation

**Benefits**:
- Catch syntax errors at recipe validation time
- Prevent broken deployments
- Better developer experience

**Related**: TODO in `notapkgtool/build/packager.py` - discovered during testing

---

### Recipe Creation Tutorial
**Status**: 💡 Idea  
**Complexity**: Low (1-2 days)  
**Value**: High

**Description**: Step-by-step tutorial for creating recipes from scratch.

**Potential Content**:
- Recipe structure and required fields
- Choosing the right discovery strategy
- Testing recipes with napt validate/discover
- Common patterns and examples
- Troubleshooting tips

**Benefits**:
- Lower barrier to entry for new users
- Reduces trial-and-error in recipe development
- Consolidates recipe knowledge in one place

**Waiting On**: Recipe schema stabilization and user feedback on patterns

---

### EXE Version Extraction
**Status**: 💡 Idea  
**Complexity**: Medium (2-3 days)  
**Value**: Medium

**Description**: Extract version information from PE (Portable Executable) headers for .exe installers.

**Technical Details**:
- New version types: `exe_file_version`, `exe_product_version`
- Use `pefile` library for cross-platform support
- Fallback to PowerShell on Windows

**Use Cases**:
- Applications distributed as EXE (Git, VS Code, etc.)
- Vendors who don't provide version in URL or API

**Related**: Mentioned in `notapkgtool/discovery/http_static.py` docstring

---

### IntuneWinAppUtil Version Tracking
**Status**: 💡 Idea  
**Complexity**: Low (1-2 days)  
**Value**: Low

**Description**: Track version of IntuneWinAppUtil.exe in cache metadata instead of always using latest from master.

**Current Behavior**: Downloads from `master` branch (always latest)

**Proposed Enhancement**:
- Track tool version in cache metadata
- Allow pinning to specific commit/release
- Auto-detect when tool updates available
- Optional config setting for tool version/source

**Benefits**:
- Reproducible builds (pin to known-good version)
- Control over tool updates
- Better for air-gapped environments

**Related**: TODO in `notapkgtool/build/packager.py:47`

---

### Recipe Linting & Best Practices
**Status**: 💡 Idea  
**Complexity**: High (5+ days)  
**Value**: Medium

**Description**: Advanced recipe validation beyond syntax checking.

**Features**:
- Validate PSADT function names exist in v4
- Warn on deprecated patterns or old v3 functions
- Check for common anti-patterns
- Suggest improvements (e.g., use Uninstall-ADTApplication)
- Style guide enforcement

**Benefits**:
- Higher quality recipes
- Consistent code style
- Educational for new users

---

### Parallel Package Building
**Status**: 💡 Idea  
**Complexity**: Medium (3-4 days)  
**Value**: Medium

**Description**: Build multiple PSADT packages in parallel for faster multi-app workflows.

**Technical Details**:
- Use Python multiprocessing or asyncio
- Parallel PSADT downloads and builds
- Maintain state consistency
- Progress reporting for multiple builds

**Use Cases**:
- Organizations with 50+ apps
- Monthly update cycles
- CI/CD pipelines

---

### Detection Script Generation
**Status**: 💡 Idea  
**Complexity**: Medium (3-4 days)  
**Value**: High

**Description**: Automatically generate detection scripts for Intune that check if an application is already installed.

**Approach Options**:
- For MSI: Generate script that checks ProductCode in registry
- For EXE: Generate script that checks file version or registry keys
- Template-based generation with recipe hints
- Support for custom detection logic in recipes

**Benefits**:
- Reduces manual work for Intune app creation
- Ensures consistent detection logic
- Leverages information we already have (ProductCode, version, paths)

**Use Cases**:
- Automatic detection for Win32 apps in Intune
- Prevent re-installation of already-installed apps
- Version-based detection for upgrades

**Technical Considerations**:
- Need to handle both MSI and EXE installers
- PowerShell detection script format for Intune
- Support for custom registry keys or file paths
- Version comparison in detection script

---

### Pre/Post Install/Uninstall Script Support
**Status**: 💡 Idea  
**Complexity**: Low (1-2 days)  
**Value**: Medium

**Description**: Add support for pre-install, post-install, pre-uninstall, and post-uninstall script blocks in recipes.

**Proposed Recipe Format**:
```yaml
psadt:
  pre_install: |
    # Close running processes
    # Backup user data
  install: |
    # Main installation
  post_install: |
    # Configure settings
    # Create shortcuts
  pre_uninstall: |
    # Backup settings
  uninstall: |
    # Main uninstallation
  post_uninstall: |
    # Clean up user data
```

**Benefits**:
- More granular control over deployment lifecycle
- Separation of concerns (prep vs install vs cleanup)
- Aligns with PSADT's deployment phase structure
- Cleaner recipe organization

**Implementation**:
- Add new fields to recipe schema
- Insert into appropriate sections of Invoke-AppDeployToolkit.ps1
- Map to PSADT's Pre-Installation, Installation, Post-Installation sections
- Validate all script blocks

**Related**: PSADT already has these phases in the template structure

---

### Enhanced CLI Help Menu
**Status**: 💡 Idea  
**Complexity**: Low (1 day)  
**Value**: Medium

**Description**: Improve the `napt -h` help output with more detailed information, examples, and better organization.

**Potential Enhancements**:
- Add examples for common workflows in help text
- Group commands by category (Discovery, Building, Packaging)
- Show performance characteristics of strategies
- Add tips for troubleshooting (--verbose, --debug flags)
- Include links to online documentation
- Better formatting with colors/sections (via rich or similar)

**Benefits**:
- Better discoverability of features
- Reduces need to consult docs for basic usage
- Improves new user onboarding experience
- Quick reference for command options

**Related**: CLI help currently minimal, relies on online documentation

---

## Investigating (Research Phase)

### Microsoft Intune Upload
**Status**: 🔬 Investigating  
**Complexity**: High (7-10 days)  
**Value**: Very High

**Description**: Direct upload of .intunewin packages to Microsoft Intune via Graph API.

**Research Needed**:
- Authentication strategy (OAuth, service principal, managed identity?)
- Graph API endpoints and permissions required
- Win32 app metadata requirements
- Error handling and retry logic
- Rate limiting considerations

**Blockers**:
- Need to decide on authentication approach
- Requires Azure AD app registration
- May need different auth for different deployment scenarios

**References**:
- [Microsoft Graph API - Win32 Apps](https://learn.microsoft.com/en-us/graph/api/resources/intune-apps-win32lobapp)
- [Intune App Upload Process](https://learn.microsoft.com/en-us/mem/intune/apps/apps-win32-app-management)

---

### Deployment Wave Management
**Status**: 🔬 Investigating  
**Complexity**: Very High (10-15 days)  
**Value**: High

**Description**: Phased deployment with rings (Pilot → Production) and gradual rollout.

**Features Under Consideration**:
- Ring definitions (Pilot, UAT, Production)
- Assignment group management
- Rollout scheduling (% of users per day)
- Health monitoring integration
- Rollback capabilities

**Dependencies**:
- Requires Intune upload implementation first
- Requires Graph API for assignment groups
- May need separate monitoring/alerting

**Blockers**:
- Complex domain requiring deep Intune knowledge
- Needs real-world deployment patterns study

---

## Ready for Implementation

### Update Policy Enforcement
**Status**: 📋 Ready  
**Complexity**: Low (1-2 days)  
**Value**: Medium

**Description**: Complete the `policy/updates.py` module with actual logic.

**Current State**: Module exists with data structures, no implementation

**Requirements**:
- Implement version comparison logic
- Implement hash comparison logic
- Support all strategy types (version_only, hash_or_version, etc.)
- Integration with state tracking

**Design**: Already specified in `defaults/org.yaml` config

---

## Completed ✅

### 0.2.0 Features
- ✅ PSADT package building (`napt build`)
- ✅ .intunewin package creation (`napt package`)
- ✅ PSADT Template_v4 download and caching
- ✅ Invoke-AppDeployToolkit.ps1 generation
- ✅ Custom branding support
- ✅ GitHub releases discovery strategy
- ✅ HTTP JSON API discovery strategy
- ✅ URL regex discovery strategy
- ✅ Integration testing framework
- ✅ State schema v2 migration

### 0.1.0 Features
- ✅ Recipe validation
- ✅ Version discovery
- ✅ HTTP downloads with caching
- ✅ MSI version extraction
- ✅ Configuration system (3-layer merging)

---

## Declined / Won't Implement

### Built-in PR Creation
**Reason**: NAPT should focus on discovery and packaging. Git operations and PR creation should remain in CI/CD workflows (GitHub Actions, etc.). This keeps NAPT platform-agnostic and focused on its core mission.

---

## How to Use This Roadmap

### Adding New Ideas
1. Add to "Ideas" section with status 💡
2. Include complexity estimate and value assessment
3. Describe the problem it solves
4. No need to design the solution yet

### Promoting Ideas
When an idea becomes clearer:
1. Move to "Investigating" 🔬 if research needed
2. Move to "Ready for Implementation" 📋 when well-defined
3. Assign to milestone when scheduling work
4. Move to "Completed" when released

### Declining Ideas
If we decide not to pursue something:
1. Move to "Declined / Won't Implement"
2. Add brief rationale
3. Keep for future reference (prevents re-discussion)

---

**Last Updated**: 2025-11-07  
**Next Review**: After 0.2.0 release

