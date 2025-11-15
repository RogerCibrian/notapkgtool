# NAPT Test Suite

Comprehensive test coverage for the NAPT project with **189 tests** covering all functionality including discovery, state tracking, PSADT building, and packaging.

## Test Strategy: Hybrid Approach 🔺

NAPT uses a **Testing Pyramid** approach with three layers:

```
        /\
       /  \        E2E (Few) - Full workflows
      /    \       - Slow, high confidence
     /------\      
    /        \     Integration (Some) - Real data, cached
   /          \    - Medium speed, catches real-world issues  
  /------------\   
 /              \  Unit (Many) - Mocked data, fast
/________________\ - Fast iteration, catches logic errors
```

### Test Types

1. **Unit Tests** (Majority) - Fast, mocked data
   - Use fake fixtures and mocks
   - Test individual functions
   - Run in milliseconds
   - Default for local development

2. **Integration Tests** (Some) - Real data, cached
   - Download real PSADT Template_v4 (once per session)
   - Download real IntuneWinAppUtil.exe (cached)
   - Validate against actual external dependencies
   - Marked with `@pytest.mark.integration`

3. **E2E Tests** (Few) - Complete workflows
   - Full CLI command execution
   - End-to-end scenarios
   - Marked with `@pytest.mark.slow`

## Test Structure

```
tests/
├── conftest.py                     # Shared fixtures (unit + integration)
│
├── Unit Tests (Fast, Mocked)
├── test_config.py                 # Configuration loading (11 tests)
├── test_core.py                   # Core orchestration (8 tests)
├── test_discovery.py              # Discovery strategies (18 tests)
├── test_download.py               # HTTP downloads (11 tests)
├── test_state.py                  # State tracking (17 tests)
├── test_validation.py             # Recipe validation (27 tests)
├── test_versioning.py             # Version comparison (21 tests)
├── test_psadt_release.py          # PSADT GitHub integration (13 tests)
├── test_build_manager.py          # Build orchestration (13 tests)
├── test_build_template.py         # Script generation (20 tests)
├── test_packager.py               # .intunewin creation (8 tests)
│
├── Integration Tests (Real Data)
├── test_integration_build.py      # Build with real PSADT Template_v4
├── test_integration_packaging.py  # Packaging with real IntuneWinAppUtil.exe
├── test_integration.py            # End-to-end workflows (4 tests)
│
├── Fixtures & Helpers
├── fixtures/
│   └── test.yaml                 # Test fixture data
└── scripts/
    ├── smoke_test_chrome.py      # Manual smoke test
    ├── showcase_version_check.py # Version comparison demo
    └── manual_test_api_json.py  # HTTP JSON API testing
```

## Running Tests

### Prerequisites
```bash
# Activate virtual environment (PowerShell)
.venv\Scripts\Activate.ps1

# Or on Linux/macOS
source .venv/bin/activate
```

### Run Unit Tests Only (Fast - Default for Development)
```bash
# Run only unit tests (excludes integration tests)
pytest tests/ -m "not integration"

# Even faster - quiet mode
pytest tests/ -m "not integration" -q

# Shows: ~170 passed in 0.50s (unit tests only)
```

### Run All Tests (Unit + Integration)
```bash
# Runs everything including integration tests
pytest tests/

# Note: Integration tests download real PSADT (~5MB) once per session
# Subsequent runs use cached data
```

### Run Integration Tests Only
```bash
# Run only integration tests (requires network)
pytest tests/ -m integration

# Runs real PSADT downloads, validates actual structure
```

### Run Specific Test Types
```bash
# Unit tests for build module
pytest tests/test_build_manager.py tests/test_build_template.py -v

# Integration tests for build module
pytest tests/test_integration_build.py -v

# All tests for a specific module
pytest tests/ -k "build" -v
```

### Run Specific Test File
```bash
pytest tests/test_versioning.py -v
```

### Run with Coverage
```bash
# Unit tests with coverage
pytest tests/ -m "not integration" --cov=notapkgtool --cov-report=html

# All tests with coverage
pytest tests/ --cov=notapkgtool --cov-report=html

# Opens htmlcov/index.html for detailed report
```

### CI/CD Recommendations
```bash
# Fast feedback (PR checks) - unit tests only
pytest tests/ -m "not integration" -v

# Nightly builds - all tests
pytest tests/ -v

# Pre-release - all tests with coverage
pytest tests/ --cov=notapkgtool --cov-report=term-missing
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
- ✅ Successful recipe discovery (file-first strategy)
- ✅ Error handling for missing apps
- ✅ Error handling for missing strategy
- ✅ Error handling for unknown strategies
- ✅ Error handling for missing files
- ✅ Version-first fast path (cache hit skips download)
- ✅ Version-first cache miss (downloads new version)
- ✅ Version-first with missing cached file (re-downloads)

**8 tests covering core workflow and version-first optimization**

### Discovery Tests (`test_discovery.py`)
- ✅ Strategy registry and lookup
- ✅ Custom strategy registration
- ✅ HTTP static strategy (file-first) with MSI and ETag caching
- ✅ Version-first strategies (web_scrape, api_github, api_json):
  - `get_version_info()` returns VersionInfo without downloading
  - Version extraction from URLs, GitHub tags, and JSON APIs
- ✅ ETag caching support for url_download (HTTP 304)
- ✅ Configuration validation and error handling
- ✅ Missing/invalid configuration detection

**18 tests covering discovery strategies**

Note: Version-first strategy integration tests moved to test_core.py (TestVersionFirstFastPath)

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
- ✅ Strategy-specific validation (url_download, api_github, web_scrape, api_json)
- ✅ Multiple apps validation
- ✅ Verbose mode output
- ✅ ConfigError exception handling

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

**189 tests** covering all functionality:
- Configuration system (11 tests) ✅
- Core orchestration (8 tests) ✅
- Discovery strategies (18 tests) ✅
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

- **Fast**: All 189 tests run in < 1 second
- **Isolated**: No test depends on another
- **Deterministic**: Same input → same output
- **Comprehensive**: Cover happy paths and error cases
- **Readable**: Clear test names and documentation
- **No Network**: All external calls mocked (requests-mock)
- **No Real Files**: MSI extraction mocked where needed

## Test Performance

```bash
$ pytest tests/ -q
........................................................................ [ 38%]
........................................................................ [ 76%]
.............................................                            [100%]
189 passed in 0.50s
```

**Average:** ~2.6ms per test

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

| Module | Tests | Coverage | Features Tested |
|--------|-------|----------|-----------------|
| `config/` | 11 | Full | YAML loading, 3-layer merging, path resolution |
| `core.py` | 8 | Full | Recipe orchestration, version-first optimization, error handling |
| `discovery/` | 18 | Full | Version-first strategies, get_version_info(), ETag caching |
| `io/download.py` | 11 | Full | HTTP downloads, conditional requests, atomic writes |
| `state/` | 17 | Full | Schema v2, filesystem-first, cache operations |
| `validation.py` | 27 | Full | Recipe validation, all strategies, error detection |
| `versioning/` | 21 | Full | Semver, numeric, lexicographic comparison |
| `psadt/` | 13 | Full | GitHub API, download, extraction, caching |
| `build/` | 41 | Full | Orchestration, template generation, packaging |
| **Total** | **189** | **Full** | **All implemented features** |

## Key Test Features

### No Network Calls
All HTTP requests are mocked using `requests-mock`. Tests run completely offline:
- ✅ GitHub API calls mocked
- ✅ File downloads mocked
- ✅ PSADT downloads mocked

### Fast Execution
- ✅ **189 tests in ~0.5 seconds**
- ✅ Average: 2.6ms per test
- ✅ All tests run in parallel safely (isolated)

### Cross-Platform
Tests are designed to work on:
- ✅ Windows (primary platform)
- ✅ Linux (with msitools for MSI tests)
- ✅ macOS (with msitools for MSI tests)

### Comprehensive Error Coverage
Every module tests:
- ✅ Happy path (success scenarios)
- ✅ Missing files/configurations
- ✅ Invalid inputs
- ✅ Network failures
- ✅ API errors (404, rate limits, etc.)
- ✅ Malformed data

## Development Workflow

### Before Committing
```bash
# Run all tests
pytest tests/

# Format code
black notapkgtool/ tests/

# Fix linting
ruff check --fix notapkgtool/ tests/
```

### Writing New Tests
1. Create test file matching module name: `test_{module}.py`
2. Use class-based organization: `class TestFeatureName:`
3. Follow naming: `test_{what_is_tested}`
4. Add comprehensive docstrings
5. Mock external dependencies
6. Use fixtures from `conftest.py`

### Test Organization
```python
class TestFeatureName:
    """Tests for specific feature."""
    
    def test_success_case(self, tmp_path):
        """Test successful operation."""
        # Happy path test
    
    def test_error_case_missing_input(self):
        """Test error handling for missing input."""
        # Error path test
```

