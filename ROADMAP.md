# NAPT Roadmap

## Philosophy

This roadmap is a living document showing potential future directions for NAPT. Features listed here are **ideas and possibilities, not commitments**. Priorities may shift based on:

- User feedback and real-world usage
- Discovered technical challenges or opportunities
- New insights from development experience
- Community contributions

**Status Legend**:
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

### v0.2.0 Features
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

### v0.1.0 Features
- ✅ Recipe validation
- ✅ Version discovery
- ✅ HTTP downloads with caching
- ✅ MSI version extraction
- ✅ Configuration system (3-layer merging)

---

## Declined / Won't Implement

### Built-in PR Creation
**Reason**: NAPT should focus on discovery and packaging. Git operations and PR creation should remain in CI/CD workflows (GitHub Actions, etc.). This keeps NAPT platform-agnostic and focused on its core mission.

**Documentation**: Documented in `.cursor/rules/napt-mission.mdc`

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
**Next Review**: After v0.2.0 release

