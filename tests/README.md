# NAPT Test Suite

Comprehensive test coverage for the NAPT project.

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and test configuration
├── test_config.py          # Configuration loading and merging tests
├── test_core.py            # Core orchestration tests
├── test_discovery.py       # Discovery strategy tests
├── test_download.py        # HTTP download functionality tests
├── test_integration.py     # End-to-end integration tests
├── test_versioning.py      # Version comparison and extraction tests
├── fixtures/
│   └── test.yaml          # Test fixture data
└── scripts/
    ├── smoke_test_chrome.py       # Manual smoke test for Chrome download
    └── showcase_version_check.py  # Demo script for version comparison
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
- ✅ Missing URL error handling
- ✅ Missing version type error handling
- ✅ Unsupported version type error handling
- ✅ Download failure error handling
- ✅ Version extraction failure error handling

**9 tests covering discovery strategies**

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
- ✅ End-to-end check_recipe workflow
- ✅ Config + discovery integration
- ✅ Download error propagation
- ✅ Version extraction error propagation

**4 tests covering integration scenarios**

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

## Total Coverage

**61 tests** covering all major functionality:
- Configuration system ✅
- Core orchestration ✅
- Discovery strategies ✅
- HTTP downloads ✅
- Version comparison ✅
- Integration workflows ✅
- Error handling ✅

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

- **Fast**: All tests run in < 1 second
- **Isolated**: No test depends on another
- **Deterministic**: Same input → same output
- **Comprehensive**: Cover happy paths and error cases
- **Readable**: Clear test names and documentation

