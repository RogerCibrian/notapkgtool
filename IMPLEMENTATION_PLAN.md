# Detection Script Generation - Implementation Plan

**Feature Branch:** `feature/detection-script-generation`  
**Status:** In Progress  
**Target Complexity:** High (3-5 days)  
**Target Value:** High

## Overview

Implement automatic generation of Intune Win32 app detection scripts with CMTrace-formatted logging. Detection scripts will search Windows registry uninstall keys for applications by name and version, with intelligent log location selection and rotation.

## Goals

1. **Automatic Detection Script Generation** - Generate PowerShell detection scripts during PSADT package building
2. **CMTrace Logging** - Industry-standard log format for Intune troubleshooting
3. **Intelligent Log Locations** - Primary: Intune logs folder (auto-collected), Fallback: LOCALAPPDATA
4. **Log Rotation** - Simple rotation strategy (main + .old files, 10MB max)
5. **MSI ProductName Extraction** - Enhance MSI extraction to get ProductName for accurate detection matching
6. **Configurable** - Organization defaults + per-recipe overrides

## Architecture

### New Modules

1. **`notapkgtool/detection.py`** - Detection script generation logic
   - `DetectionConfig` dataclass (configuration)
   - `generate_detection_script()` function (PowerShell template)
   - CMTrace log format helpers

2. **Enhanced `notapkgtool/versioning/msi.py`**
   - `MSIMetadata` dataclass (ProductName, ProductVersion, ProductCode)
   - `extract_msi_metadata()` function (multi-property extraction)

### Modified Modules

1. **`notapkgtool/build/manager.py`**
   - Integrate detection script generation in `build_package()`
   - Save `detection.ps1` to build directory

2. **`notapkgtool/results.py`**
   - Add `detection_script_path` to `BuildResult` (optional)

### Configuration Schema

```yaml
# Organization defaults (defaults/org.yaml)
detection:
  log_format: "cmtrace"       # Only CMTrace in Phase 1
  log_level: "INFO"           # INFO or DEBUG
  log_rotation_mb: 10         # Rotate at 10MB
  exact_match: false          # Fuzzy vs exact name matching

# Per-recipe override (optional)
apps:
  - name: "Google Chrome"
    detection:
      log_level: "DEBUG"      # Override for debugging
      exact_match: true       # Exact name match for this app
```

## Detection Script Features

### Registry Search Strategy
- Search paths: `HKLM:\SOFTWARE\...\Uninstall`, `HKLM:\SOFTWARE\WOW6432Node\...\Uninstall`, `HKCU:\SOFTWARE\...\Uninstall`
- Match by DisplayName (exact or fuzzy)
- Version comparison using PowerShell `[version]` parsing with fallback to string comparison
- Exit codes: 0 (detected), 1 (not detected)

### Logging Strategy

**Log Locations:**
```
System context:
  Primary:  C:\ProgramData\Microsoft\IntuneManagementExtension\Logs\NAPTDetections.log
  Fallback: C:\ProgramData\NAPT\NAPTDetections.log

User context:
  Primary:  C:\ProgramData\Microsoft\IntuneManagementExtension\Logs\NAPTDetectionsUser.log
  Fallback: %LOCALAPPDATA%\NAPT\NAPTDetectionsUser.log
```

**Log Format:** CMTrace
```
<![LOG[Message]LOG]!><time="14:30:52.123+000" date="12-03-2024" component="NAPT-Detection-Chrome" context="SYSTEM" type="1" thread="4567" file="detection.ps1">
```

**Log Rotation:**
- Check file size at script start
- If > 10 MB: delete `.log.old`, rename `.log` → `.log.old`, create new `.log`
- Only 2 files maintained (current + old)

**Log Levels:**
- Type 1 (Info): Normal operations, detection results
- Type 2 (Warning): Fallback location used, version format issues
- Type 3 (Error): Registry access failures, exceptions

### PowerShell Template Structure

1. **Header** - Script metadata (generated timestamp, recipe path, strategy)
2. **Parameters** - Injected values (app name, version, exact match, log format, etc.)
3. **Logging Setup** - Determine context, select log location with fallback
4. **CMTrace Writer Function** - Format and write CMTrace log entries
5. **Log Rotation Logic** - Check size, rotate if needed
6. **Version Comparison Function** - PowerShell version parsing with fallback
7. **Registry Search** - Iterate uninstall keys, match by name and version
8. **Exit with Logging** - Log result and exit with appropriate code

## Implementation Phases

### Phase 1: MSI Metadata Extraction (Task 1-2)
**Time:** 0.5-1 day

- Extend `notapkgtool/versioning/msi.py`
- Create `MSIMetadata` dataclass
- Implement `extract_msi_metadata()` using existing backend infrastructure
- Query multiple properties: `ProductName`, `ProductVersion`, `ProductCode`
- Reuse existing backends: msilib, _msi, PowerShell COM, msitools
- Unit tests with real MSI files

**Success Criteria:**
- Can extract ProductName from Chrome MSI
- Works cross-platform (Windows, Linux, macOS)
- Proper error handling with chained exceptions

### Phase 2: Detection Module Core (Task 3-5)
**Time:** 1-1.5 days

- Create `notapkgtool/detection.py` module
- Implement `DetectionConfig` dataclass
- Create PowerShell template with CMTrace logging
- Implement `generate_detection_script()` function
- Template parameters: app name, version, log format, exact match, etc.

**Success Criteria:**
- Can generate valid PowerShell script from config
- CMTrace log format is correct
- Template includes all required logic (context detection, location selection, registry search)

### Phase 3: Logging & Rotation Logic (Task 6-7)
**Time:** 0.5-1 day

- Implement CMTrace format writer in PowerShell
- Add log location selection logic (primary + fallback)
- Implement log rotation (10MB check, rename, cleanup)
- Add context detection (SYSTEM vs user)
- Non-blocking logging (script continues if logging fails)

**Success Criteria:**
- Logs to correct location based on context and permissions
- Rotation works correctly at 10MB threshold
- CMTrace viewer can read the logs
- Script doesn't fail if logging fails

### Phase 4: Build Integration (Task 8)
**Time:** 0.5 day

- Modify `notapkgtool/build/manager.py`
- Extract MSI metadata during build
- Generate detection script
- Save `detection.ps1` to build directory
- Update `BuildResult` with detection script path

**Success Criteria:**
- `napt build` creates detection.ps1 in build directory
- Detection script has correct app name and version
- Works for both MSI and EXE installers (EXE uses recipe AppName)

### Phase 5: Configuration Schema (Task 9)
**Time:** 0.5 day

- Add detection configuration to `defaults/org.yaml`
- Update validation schema
- Support per-recipe overrides
- Default values: CMTrace format, INFO level, 10MB rotation

**Success Criteria:**
- Can configure detection at org level
- Can override per-recipe
- Validation catches invalid configurations

### Phase 6: Testing (Task 10-11)
**Time:** 1 day

- Unit tests for MSI metadata extraction
- Unit tests for detection script generation
- Integration tests for build process
- Manual testing: Run generated scripts on Windows
- Test CMTrace log viewing

**Success Criteria:**
- All unit tests pass
- Integration tests pass
- Generated scripts detect real apps correctly
- Logs viewable in CMTrace

### Phase 7: Documentation (Task 12-13)
**Time:** 0.5 day

- Update `docs/user-guide.md` - Detection Script Generation section
- Update `docs/recipe-reference.md` - Detection configuration schema
- Update `docs/roadmap.md` - Move feature to completed
- Add examples to recipes

**Success Criteria:**
- Documentation explains how detection works
- Configuration options documented
- Examples provided

## Testing Strategy

### Unit Tests

```python
# tests/test_versioning_msi.py
def test_extract_msi_metadata():
    """Test extracting ProductName, ProductVersion, ProductCode from MSI."""
    # Use real MSI file from fixtures
    # Verify all properties extracted

# tests/test_detection.py
def test_generate_detection_script():
    """Test detection script generation with various configs."""
    # Test CMTrace format output
    # Test different log levels
    # Test exact vs fuzzy matching
```

### Integration Tests

```python
# tests/test_build.py
def test_build_generates_detection_script():
    """Test that build_package creates detection.ps1."""
    # Build a package
    # Verify detection.ps1 exists
    # Verify content has correct app name/version
```

### Manual Testing (Windows)

1. Build Chrome package
2. Run generated `detection.ps1` (Chrome installed)
3. Verify exit code 0 (detected)
4. Check CMTrace log in Intune folder
5. Run on machine without Chrome
6. Verify exit code 1 (not detected)
7. Test as SYSTEM context (PsExec)
8. Test as standard user (fallback location)

## File Changes Summary

### New Files
- `notapkgtool/detection.py` - Detection script generation module
- `tests/test_detection.py` - Detection tests
- `IMPLEMENTATION_PLAN.md` - This file

### Modified Files
- `notapkgtool/versioning/msi.py` - Add MSIMetadata and extract_msi_metadata()
- `notapkgtool/build/manager.py` - Integrate detection generation
- `notapkgtool/results.py` - Add detection_script_path to BuildResult
- `defaults/org.yaml` - Add detection configuration
- `tests/test_versioning_msi.py` - Add metadata extraction tests
- `tests/test_build.py` - Add detection integration tests
- `docs/user-guide.md` - Add Detection Script Generation section
- `docs/recipe-reference.md` - Document detection configuration
- `docs/roadmap.md` - Move feature to completed

## Dependencies

- No new Python dependencies required
- Uses existing MSI backend infrastructure
- PowerShell template is embedded in Python module (no external files)

## Risks & Mitigations

### Risk: MSI ProductName doesn't match registry DisplayName
**Mitigation:** Default to fuzzy matching (DisplayName contains ProductName)

### Risk: EXE installers don't have ProductName
**Mitigation:** Use recipe's AppName from psadt.app_vars.AppName

### Risk: Standard users can't write to Intune logs folder
**Mitigation:** Graceful fallback to %LOCALAPPDATA%\NAPT\

### Risk: Log rotation conflicts with concurrent scripts
**Mitigation:** Simple 2-file rotation minimizes window, rotation at start (not during logging)

### Risk: CMTrace format generation is complex
**Mitigation:** Thoroughly test format, validate with real CMTrace viewer

## Success Metrics

- ✅ Detection scripts generated for all built packages
- ✅ Logs viewable in CMTrace with proper formatting
- ✅ 90%+ of logs auto-collected via Intune diagnostics (primary location success rate)
- ✅ No detection failures due to logging issues (non-blocking)
- ✅ All tests passing (unit + integration)
- ✅ Documentation complete and accurate

## Next Steps After Completion

1. Monitor real-world usage and log quality
2. Collect feedback on detection accuracy
3. Consider adding file-based detection for EXEs without registry entries
4. Consider adding custom detection script support (user-provided override)
5. Integrate with Intune upload feature (use detection script in Graph API calls)

## Notes

- This implementation focuses on **registry-based detection only** (Phase 1)
- File-based detection for edge cases can be added later if needed
- Only CMTrace format in Phase 1, plain text can be added later if requested
- Log verbosity (INFO vs DEBUG) controlled via configuration, not runtime flags


