# NAPT Test Suite

Comprehensive test coverage for the NAPT project with 198 tests covering all functionality.

## Test Structure

```
tests/
├── conftest.py                  # Shared fixtures and test configuration
├── test_config.py              # Configuration loading and merging (11 tests)
├── test_core.py                # Core orchestration (5 tests)
├── test_discovery.py           # Discovery strategies (61 tests)
├── test_download.py            # HTTP download functionality (11 tests)
├── test_integration.py         # End-to-end integration (4 tests)
├── test_state.py               # State tracking and caching (17 tests)
├── test_validation.py          # Recipe validation (27 tests)
├── test_versioning.py          # Version comparison (21 tests)
├── test_psadt_release.py       # PSADT GitHub integration (13 tests)
├── test_build_manager.py       # Build orchestration (13 tests)
├── test_build_template.py      # Script generation (20 tests)
├── test_packager.py            # .intunewin creation (8 tests)
├── fixtures/
│   └── test.yaml              # Test fixture data
└── scripts/
    ├── smoke_test_chrome.py           # Manual smoke test for Chrome
    ├── showcase_version_check.py      # Demo script for version comparison
    └── manual_test_http_json.py       # Manual HTTP JSON API testing
```

## Running Tests

### Run All Tests
```bash
pytest tests/
```

### Run Specific Test File
```bash
pytest tests/test_versioning.py
```

### Run with Verbose Output
```bash
pytest tests/ -v
```

### Run with Coverage
```bash
pytest tests/ --cov=notapkgtool --cov-report=html
```

## Test Coverage

### Configuration Tests (`test_config.py`)
- ✅ Basic YAML loading
- ✅ Three-layer merging (org → vendor → recipe)
- ✅ Deep merge behavior for dicts
- ✅ List replacement (not merge)
- ✅ Scalar value overwriting
- ✅ Vendor detection from directory structure
- ✅ Dynamic value injection (AppScriptDate)
- ✅ Error handling (invalid YAML, empty files, wrong types)

**11 tests covering configuration system**

### Core Orchestration Tests (`test_core.py`)
- ✅ Successful recipe validation
- ✅ Error handling for missing apps
- ✅ Error handling for missing strategy
- ✅ Error handling for unknown strategies
- ✅ Error handling for missing files

**5 tests covering core workflow**

### Discovery Tests (`test_discovery.py`)
- ✅ Strategy registry and lookup
- ✅ Custom strategy registration
- ✅ HTTP static strategy with MSI
- ✅ URL regex strategy with pattern matching
- ✅ GitHub release strategy with asset selection
- ✅ HTTP JSON API strategy with JSONPath
- ✅ ETag caching support (HTTP 304)
- ✅ Missing URL/configuration error handling
- ✅ Missing version type error handling
- ✅ Unsupported version type error handling
- ✅ Download failure error handling
- ✅ Version extraction failure error handling
- ✅ GitHub API errors (404, rate limits)
- ✅ JSON API errors (invalid responses)

**61 tests covering all discovery strategies**

### Download Tests (`test_download.py`)
- ✅ Basic successful download
- ✅ Following redirects
- ✅ Content-Disposition header parsing
- ✅ Checksum validation (success and failure)
- ✅ Content-type validation
- ✅ Atomic writes (no .part leftovers)
- ✅ Conditional requests with ETag (304 Not Modified)
- ✅ Conditional requests with Last-Modified
- ✅ Conditional request with modified content (200 OK)
- ✅ Destination folder creation

**11 tests covering download functionality**

### Integration Tests (`test_integration.py`)
- ✅ End-to-end discover_recipe workflow
- ✅ Config + discovery integration
- ✅ Download error propagation
- ✅ Version extraction error propagation

**4 tests covering integration scenarios**

### State Tracking Tests (`test_state.py`)
- ✅ State file creation and default structure
- ✅ Save and load round-trip
- ✅ Corrupted file handling with backup
- ✅ StateTracker class operations
- ✅ Cache operations (get, update)
- ✅ Version change detection
- ✅ Schema v2 structure (filesystem-first)

**17 tests covering state management**

### Validation Tests (`test_validation.py`)
- ✅ Valid recipe validation (all strategies)
- ✅ Missing file handling
- ✅ Invalid YAML syntax detection
- ✅ Empty file handling
- ✅ Missing required fields (apiVersion, apps, source, strategy)
- ✅ Strategy-specific validation (http_static, github_release, url_regex, http_json)
- ✅ Multiple apps validation
- ✅ Verbose mode output
- ✅ ValidationError exception handling

**27 tests covering recipe validation**

### Versioning Tests (`test_versioning.py`)
- ✅ Basic semantic version comparison
- ✅ Major.minor.patch ordering
- ✅ Prerelease tag ordering (alpha < beta < rc)
- ✅ Version prefix handling (v1.2.3)
- ✅ MSI 3-part numeric comparison
- ✅ EXE 4-part numeric comparison
- ✅ Lexicographic fallback
- ✅ is_newer_any() function
- ✅ Version key generation and sorting
- ✅ DiscoveredVersion dataclass
- ✅ Edge cases (empty strings, long versions, mixed formats)
- ✅ Real-world Chrome versions

**21 tests covering version comparison**

### PSADT Tests (`test_psadt_release.py`)
- ✅ Fetch latest version from GitHub API
- ✅ Version extraction (with/without 'v' prefix)
- ✅ Cache validation
- ✅ Download and extraction workflow
- ✅ Error handling (API errors, missing assets, invalid releases)

**13 tests covering PSADT release management**

### Build Manager Tests (`test_build_manager.py`)
- ✅ Finding installer files (by URL, pattern, most recent)
- ✅ Build directory creation
- ✅ PSADT file copying
- ✅ Installer copying to Files/
- ✅ Branding application
- ✅ Error handling (missing files, invalid structure)

**13 tests covering build orchestration**

### Build Template Tests (`test_build_template.py`)
- ✅ PowerShell value formatting (strings, bools, arrays, etc.)
- ✅ String escaping (quotes)
- ✅ $adtSession variable building
- ✅ Organization defaults merging with recipe overrides
- ✅ ${discovered_version} placeholder substitution
- ✅ Auto-generated fields (AppScriptDate, DeployAppScriptVersion)
- ✅ Template $adtSession block replacement
- ✅ Recipe code insertion (install/uninstall)
- ✅ Multi-line code indentation

**20 tests covering script generation**

### Packager Tests (`test_packager.py`)
- ✅ Build structure validation
- ✅ .intunewin package creation
- ✅ --clean-source option
- ✅ Error handling (invalid structure, missing directories)

**8 tests covering .intunewin packaging**

## Total Coverage

**198 tests** covering all functionality:
- Configuration system (11 tests) ✅
- Core orchestration (5 tests) ✅
- Discovery strategies (61 tests) ✅
- HTTP downloads (11 tests) ✅
- State tracking (17 tests) ✅
- Recipe validation (27 tests) ✅
- Version comparison (21 tests) ✅
- Integration workflows (4 tests) ✅
- PSADT release management (13 tests) ✅
- Build orchestration (13 tests) ✅
- Script generation (20 tests) ✅
- Package creation (8 tests) ✅
- Error handling (comprehensive) ✅

## Test Fixtures

### conftest.py Fixtures
- `tmp_test_dir` - Temporary directory for test artifacts
- `fixtures_dir` - Path to fixtures directory
- `sample_yaml_path` - Path to sample YAML
- `sample_recipe_data` - Complete recipe structure
- `sample_org_defaults` - Organization defaults
- `create_yaml_file` - Factory for creating temporary YAML files
- `mock_download_response` - Mock HTTP download response data

## Mocking Strategy

Tests use:
- **requests-mock**: For HTTP request mocking
- **unittest.mock**: For internal function patching
- **pytest fixtures**: For test data and configuration

## Continuous Integration

Tests are designed to run:
- ✅ On Windows (primary platform)
- ✅ On Linux (with msitools)
- ✅ On macOS (with msitools)
- ✅ Without network access (all external calls mocked)
- ✅ In parallel (isolated test directories)

## Adding New Tests

When adding tests:
1. Use appropriate fixtures from `conftest.py`
2. Follow existing naming conventions
3. Group related tests in classes
4. Add docstrings explaining what's being tested
5. Mock external dependencies (network, filesystem)
6. Ensure tests are idempotent and isolated

## Test Philosophy

- **Fast**: All 198 tests run in < 1 second
- **Isolated**: No test depends on another
- **Deterministic**: Same input → same output
- **Comprehensive**: Cover happy paths and error cases
- **Readable**: Clear test names and documentation
- **No Network**: All external calls mocked (requests-mock)
- **No Real Files**: MSI extraction mocked where needed

## Test Performance

```bash
$ pytest tests/ -q
........................................................................ [ 36%]
........................................................................ [ 72%]
......................................................                   [100%]
198 passed in 0.50s
```

**Average:** ~2.5ms per test

## Key Testing Patterns

### Mocking External Dependencies

**HTTP Requests:**
```python
def test_example(requests_mock):
    requests_mock.get("https://api.example.com/data", json={"version": "1.0"})
    # Your test code
```

**File Operations:**
```python
from unittest.mock import patch

@patch("notapkgtool.module.some_function")
def test_example(mock_func, tmp_path):
    mock_func.return_value = "mocked"
    # Your test code
```

### Using Fixtures

**Temporary Directories:**
```python
def test_example(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")
    # Test operates in isolated tmp_path
```

**Sample Data:**
```python
def test_example(sample_org_defaults):
    # Use pre-built test configuration
    assert "psadt" in sample_org_defaults["defaults"]
```

## Coverage by Module

| Module | Tests | Coverage |
|--------|-------|----------|
| `config/` | 11 | Full |
| `core.py` | 5 | Full |
| `discovery/` | 61 | Full (all 4 strategies) |
| `io/download.py` | 11 | Full |
| `state/` | 17 | Full |
| `validation.py` | 27 | Full |
| `versioning/` | 21 | Full |
| `psadt/` | 13 | Full |
| `build/` | 41 | Full |
| **Total** | **198** | **Full** |

