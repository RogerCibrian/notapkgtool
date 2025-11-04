# NAPT Documentation Overview

## Project Structure

NAPT (Not a Pkg Tool) is a Python-based CLI tool for automating Windows application packaging and deployment to Microsoft Intune using PSAppDeployToolkit (PSADT).

### Package Organization

```
notapkgtool/
├── __init__.py              # Main package exports
├── cli.py                   # Command-line interface (argparse)
├── core.py                  # High-level orchestration
├── validation.py            # Recipe validation (no downloads)
├── config/
│   ├── __init__.py          # Config package exports
│   └── loader.py            # YAML loading and merging
├── discovery/
│   ├── __init__.py          # Discovery package exports
│   ├── base.py              # Strategy protocol and registry
│   ├── http_static.py       # Static URL download strategy
│   ├── url_regex.py         # URL regex discovery strategy
│   ├── github_release.py    # GitHub releases API strategy
│   └── http_json.py         # HTTP JSON API strategy
├── state/
│   ├── __init__.py          # State tracking exports
│   └── tracker.py           # Version and ETag caching
├── io/
│   ├── __init__.py          # I/O package exports
│   ├── download.py          # Robust HTTP downloads
│   └── upload.py            # Upload adapters (planned)
├── policy/
│   ├── __init__.py          # Policy package exports
│   └── updates.py           # Update policies (planned)
└── versioning/
    ├── __init__.py          # Versioning package exports
    ├── keys.py              # Version comparison logic
    ├── msi.py               # MSI ProductVersion extraction
    └── url_regex.py         # URL regex extraction helper
```

## Documentation Standards

All modules in NAPT follow these documentation standards:

### Module-Level Docstrings

Every module includes:
- **Purpose**: What the module does
- **Key Features**: Notable capabilities
- **Public API**: Functions/classes exported
- **Examples**: Practical usage examples
- **Design Decisions**: Why certain approaches were chosen
- **Notes**: Important caveats or context

### Function/Class Docstrings

All public functions include:
- **Summary**: One-line description
- **Parameters**: Type-annotated with descriptions
- **Returns**: Type and meaning
- **Raises**: Exceptions that can be raised
- **Examples**: Usage examples (where helpful)
- **Notes**: Additional context (optional)

### Type Annotations

- Modern Python 3.11+ syntax (`X | None`, not `Optional[X]`)
- Full type coverage for public APIs
- `from __future__ import annotations` for forward references

### Import Organization

Consistent three-section import order:
1. `from __future__ import annotations` (if needed)
2. Standard library imports
3. Third-party imports
4. First-party (NAPT) imports

### Error Handling

- Exceptions are chained with `raise ... from err`
- Descriptive error messages
- Appropriate exception types (ValueError, RuntimeError, etc.)

## Key Design Patterns

### 1. Strategy Pattern (Discovery)

Discovery strategies use Protocol-based structural subtyping:
- No inheritance required
- Self-registering at module import
- Dynamic dispatch via registry

```python
from notapkgtool.discovery import get_strategy

strategy = get_strategy("http_static")
discovered, path, sha256 = strategy.discover_version(app_config, output_dir)
```

### 2. Layered Configuration

Three-layer YAML merging with deep merge for dicts:
1. Organization defaults (defaults/org.yaml)
2. Vendor defaults (defaults/vendors/<Vendor>.yaml)
3. Recipe configuration (recipes/<Vendor>/<app>.yaml)

```python
from notapkgtool.config import load_effective_config

config = load_effective_config(Path("recipes/Google/chrome.yaml"))
```

### 3. Atomic Operations

- Downloads use `.part` files with atomic rename
- Prevents partial files in destination
- Safe for concurrent/interrupted operations

### 4. Conditional Requests

- HTTP 304 Not Modified support
- ETag and Last-Modified headers
- Bandwidth-efficient incremental builds

### 5. State Tracking

- JSON-based state file for version and ETag persistence
- Automatic conditional downloads using cached ETags
- Enabled by default with `--stateless` opt-out
- Prevents re-downloading unchanged files

## State Management & Caching

NAPT automatically tracks discovered versions and uses HTTP ETags for efficient conditional downloads. This prevents re-downloading unchanged files and enables fast scheduled checks.

### How It Works

1. **First Run**: Downloads file, saves ETag and version to `state/versions.json`
2. **Second Run**: Sends `If-None-Match` header with cached ETag
3. **Server Response**:
   - `HTTP 304 Not Modified` → Uses cached file (instant!)
   - `HTTP 200 OK` → Downloads new version, updates state

### Default Behavior (Stateful)

```bash
# State tracking enabled by default
napt discover recipes/Google/chrome.yaml

# Creates/updates: state/versions.json
```

### Stateless Mode

```bash
# Disable state tracking for one-off checks
napt discover recipes/Google/chrome.yaml --stateless

# Always downloads, no caching
# Useful for CI/CD clean builds
```

### Custom State File

```bash
# Use different state file per environment
napt discover recipes/Google/chrome.yaml --state-file production-state.json
napt discover recipes/Google/chrome.yaml --state-file staging-state.json
```

### State File Structure

The state file is JSON with this schema:

```json
{
  "metadata": {
    "napt_version": "0.1.0",
    "schema_version": "1",
    "last_updated": "2024-10-28T10:30:00Z"
  },
  "apps": {
    "napt-chrome": {
      "version": "130.0.6723.117",
      "etag": "W/\"abc123\"",
      "last_modified": "Mon, 28 Oct 2024 10:30:00 GMT",
      "file_path": "downloads/googlechromestandaloneenterprise64.msi",
      "sha256": "def456...",
      "last_checked": "2024-10-28T10:30:00Z",
      "source": "http_static"
    }
  }
}
```

### Benefits

- **Bandwidth efficiency**: Avoid downloading unchanged files (especially important for scheduled checks)
- **Speed**: HTTP 304 responses are instant vs. downloading 60+ MB installers
- **Server-friendly**: Reduces load on vendor CDNs
- **Cost savings**: Important when using metered bandwidth

### When Files Are Re-Downloaded

Files are only re-downloaded when:
- First time checking a recipe
- Server's ETag changed (file content changed)
- ETag not supported by server (falls back to full download)
- Running in `--stateless` mode
- Cached file was deleted

### Troubleshooting

**Corrupted state file:**
```bash
# NAPT automatically creates backup and fresh state
# Backup saved to: state/versions.json.backup
```

**Cached file deleted:**
```bash
# Run with --stateless to force re-download
napt discover recipes/Google/chrome.yaml --stateless
```

**State file location:**
```bash
# Default: state/versions.json
# Custom: --state-file path/to/custom.json
# None: --stateless
```

## Discovery Strategies

Discovery strategies are the core mechanism for obtaining application installers and extracting version information. NAPT uses a pluggable strategy pattern that allows different approaches based on vendor requirements.

### Overview

Each strategy implements the `DiscoveryStrategy` protocol and provides a `discover_version()` method that:
1. Downloads or locates an installer
2. Extracts version information
3. Returns a `DiscoveredVersion` object, file path, and SHA-256 hash

Strategies are registered at module import time and dynamically loaded based on the recipe configuration.

### Available Strategies

| Strategy | Version Source | Use Case | Bandwidth | Speed |
|----------|---------------|----------|-----------|-------|
| **http_static** | File metadata | Fixed URLs with embedded versions | Medium | Medium |
| **url_regex** | URL pattern | Version-encoded URLs | Low | Fast |
| **github_release** | Git tags | GitHub-hosted releases | Medium | Medium |
| **http_json** | JSON API | Programmatic APIs with metadata | Low | Fast |

### Strategy Comparison

#### http_static

**Best for:**
- Vendors with stable download URLs (e.g., Chrome, Firefox enterprise)
- MSI installers with ProductVersion embedded
- When version isn't in URL or easily parseable

**Pros:**
- Simple and reliable
- Version directly from installer (most accurate)
- Works with any URL structure

**Cons:**
- Must download file before knowing version
- Requires version extraction from file format
- Currently only supports MSI ProductVersion

**Configuration:**
```yaml
source:
  strategy: http_static
  url: "https://vendor.com/installer.msi"
  version:
    type: msi_product_version_from_file
    file: "installer.msi"  # Optional
```

**See also:** [`notapkgtool/discovery/http_static.py`](notapkgtool/discovery/http_static.py)

#### url_regex

**Best for:**
- URLs with version numbers embedded (e.g., `app-v1.2.3.msi`)
- API endpoints that return versioned download URLs
- When you need to check version without downloading

**Pros:**
- Fast version discovery (no download needed)
- Bandwidth-efficient
- File format agnostic
- Can decide whether to download before fetching

**Cons:**
- Requires predictable URL patterns
- Version may not match actual file version
- Regex patterns can be complex

**Configuration:**
```yaml
source:
  strategy: url_regex
  url: "https://vendor.com/app-v1.2.3-setup.msi"
  version:
    type: regex_in_url
    pattern: "app-v(?P<version>[0-9.]+)-setup"
```

**See also:** [`notapkgtool/discovery/url_regex.py`](notapkgtool/discovery/url_regex.py)

#### github_release

**Best for:**
- Open-source projects on GitHub (Git, VS Code, Node.js)
- Projects with semantic versioned tags
- Multi-platform releases with multiple assets

**Pros:**
- Direct API access (no web scraping)
- Automatic latest release detection
- Asset pattern matching for platform selection
- Optional authentication for rate limits
- Prerelease control

**Cons:**
- Requires GitHub-hosted releases
- Subject to API rate limits (60/hr unauth, 5000/hr with token)
- Needs asset pattern for multi-asset releases

**Configuration:**
```yaml
source:
  strategy: github_release
  repo: "owner/repository"
  asset_pattern: ".*-64-bit\\.exe$"       # Optional
  version_pattern: "v?([0-9.]+)"          # Optional
  prerelease: false                       # Optional
  token: "${GITHUB_TOKEN}"                # Optional
```

**See also:** [`notapkgtool/discovery/github_release.py`](notapkgtool/discovery/github_release.py)

#### http_json

**Best for:**
- Vendors with JSON REST APIs (Microsoft, Mozilla, etc.)
- Cloud services with version endpoints
- CDNs that provide metadata APIs
- APIs requiring authentication or custom headers

**Pros:**
- Fast version discovery (no download needed)
- Handles complex JSON structures with JSONPath
- Support for POST requests and custom headers
- Environment variable expansion for tokens
- Works with any file type

**Cons:**
- Requires vendor to provide JSON API
- Need to understand API response structure
- JSONPath expressions can be complex for nested data

**Configuration:**
```yaml
source:
  strategy: http_json
  api_url: "https://api.vendor.com/latest"
  version_path: "version"
  download_url_path: "download_url"
  method: "GET"                          # Optional
  headers:                               # Optional
    Authorization: "Bearer ${API_TOKEN}"
  body:                                  # Optional (for POST)
    platform: "windows"
```

**See also:** [`notapkgtool/discovery/http_json.py`](notapkgtool/discovery/http_json.py)

### Decision Guide

Use this flowchart to choose the right strategy:

```
Is the app on GitHub with releases?
├─ YES → Use github_release
│         (easiest for OSS projects)
│
└─ NO → Does the vendor provide a JSON API?
        ├─ YES → Use http_json
        │         (fast, flexible, modern)
        │
        └─ NO → Does the URL contain the version?
                ├─ YES → Use url_regex
                │         (fast, no download needed)
                │
                └─ NO → Use http_static
                          (reliable, version from file)
```

**Additional considerations:**

- **Modern APIs**: If vendor provides JSON API, prefer `http_json` (fastest, most flexible)
- **Rate limits**: If checking GitHub frequently, use `github_release` with a token
- **Accuracy**: If version accuracy is critical, prefer `http_static` (version from actual file)
- **Performance**: For version checks without downloading, prefer `url_regex` or `http_json`
- **Future-proofing**: `http_static` is most resilient to URL changes

### Configuration Reference

#### Common Fields

All strategies support these standard fields:

```yaml
source:
  strategy: "<strategy_name>"  # Required: http_static, url_regex, or github_release
  # Strategy-specific fields below
```

#### http_static Configuration

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | ✅ Yes | - | Direct download URL |
| `version.type` | string | ✅ Yes | - | Version extraction method |
| `version.file` | string | ❌ No | (from URL) | Target file for version extraction |

**Supported version types:**
- `msi_product_version_from_file`: Extract from MSI ProductVersion property

**Example:**
```yaml
source:
  strategy: http_static
  url: "https://dl.google.com/chrome/install/googlechromestandaloneenterprise64.msi"
  version:
    type: msi_product_version_from_file
```

#### url_regex Configuration

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | ✅ Yes | - | URL containing version |
| `version.type` | string | ✅ Yes | - | Must be `regex_in_url` |
| `version.pattern` | string | ✅ Yes | - | Regex pattern to extract version |

**Pattern syntax:**
- Use named capture group: `(?P<version>...)`
- Or use first capture group: `(...)`
- Full Python regex syntax supported

**Example:**
```yaml
source:
  strategy: url_regex
  url: "https://vendor.com/downloads/app-v1.2.3-setup.msi"
  version:
    type: regex_in_url
    pattern: "app-v(?P<version>[0-9.]+)-setup"
```

#### github_release Configuration

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repo` | string | ✅ Yes | - | GitHub repo (owner/name) |
| `asset_pattern` | string | ❌ No | (first asset) | Regex to match asset filename |
| `version_pattern` | string | ❌ No | `v?([0-9.]+)` | Regex to extract version from tag |
| `prerelease` | boolean | ❌ No | `false` | Include pre-release versions |
| `token` | string | ❌ No | - | GitHub auth token (increases rate limit) |

**Pattern syntax:**
- `asset_pattern`: Standard regex, matches against asset filenames
- `version_pattern`: Extracts from tag name, supports named groups
- `token`: Can use environment variables: `${GITHUB_TOKEN}`

**Rate limits:**
- Unauthenticated: 60 requests/hour per IP
- Authenticated: 5000 requests/hour per token

**Example:**
```yaml
source:
  strategy: github_release
  repo: "git-for-windows/git"
  asset_pattern: "Git-.*-64-bit\\.exe$"
  version_pattern: "v?([0-9.]+)\\.windows"
  token: "${GITHUB_TOKEN}"
```

#### http_json Configuration

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `api_url` | string | ✅ Yes | - | JSON API endpoint URL |
| `version_path` | string | ✅ Yes | - | JSONPath to version field |
| `download_url_path` | string | ✅ Yes | - | JSONPath to download URL |
| `method` | string | ❌ No | `"GET"` | HTTP method (GET or POST) |
| `headers` | dict | ❌ No | `{}` | Custom HTTP headers |
| `body` | dict | ❌ No | `{}` | Request body (for POST) |
| `timeout` | int | ❌ No | `30` | Request timeout in seconds |

**JSONPath syntax:**
- Simple: `version` → `{"version": "1.2.3"}`
- Nested: `release.version` → `{"release": {"version": "1.2.3"}}`
- Array: `[0].version` → `[{"version": "1.2.3"}]`
- Deep: `data.stable.platforms.windows.x64`

**Example:**
```yaml
source:
  strategy: http_json
  api_url: "https://api.vendor.com/releases"
  version_path: "release.stable.version"
  download_url_path: "release.stable.platforms.windows.x64"
  headers:
    Authorization: "Bearer ${API_TOKEN}"
```

### Common Patterns

#### Pattern 1: Simple Fixed URL (Chrome)
```yaml
source:
  strategy: http_static
  url: "https://dl.google.com/chrome/install/googlechromestandaloneenterprise64.msi"
  version:
    type: msi_product_version_from_file
```

#### Pattern 2: Version in URL
```yaml
source:
  strategy: url_regex
  url: "https://vendor.com/app-1.2.3-installer.msi"
  version:
    type: regex_in_url
    pattern: "app-([0-9.]+)-installer"
```

#### Pattern 3: GitHub Release (Git for Windows)
```yaml
source:
  strategy: github_release
  repo: "git-for-windows/git"
  asset_pattern: "Git-.*-64-bit\\.exe$"
  version_pattern: "v?([0-9.]+)\\.windows"
```

#### Pattern 4: Multiple Assets with Platform Selection
```yaml
source:
  strategy: github_release
  repo: "vendor/app"
  asset_pattern: "app-windows-x64\\.zip$"  # Select specific platform
  version_pattern: "v([0-9.]+)"
```

#### Pattern 5: Pre-release Channels
```yaml
source:
  strategy: github_release
  repo: "vendor/app"
  prerelease: true  # Include beta/RC versions
  version_pattern: "v?([0-9.]+-[a-z0-9]+)"  # Capture prerelease suffix
```

#### Pattern 6: Simple JSON API
```yaml
source:
  strategy: http_json
  api_url: "https://api.vendor.com/latest"
  version_path: "version"
  download_url_path: "download_url"
```

#### Pattern 7: Nested JSON with Authentication
```yaml
source:
  strategy: http_json
  api_url: "https://api.vendor.com/releases"
  version_path: "stable.version"
  download_url_path: "stable.platforms.windows.x64"
  headers:
    Authorization: "Bearer ${API_TOKEN}"
```

#### Pattern 8: POST Request with Query Parameters
```yaml
source:
  strategy: http_json
  api_url: "https://api.vendor.com/query"
  version_path: "result.version"
  download_url_path: "result.url"
  method: "POST"
  body:
    platform: "windows"
    arch: "x64"
    channel: "stable"
```

### Error Handling

All strategies follow consistent error handling patterns:

**ValueError:**
- Missing required configuration fields
- Invalid configuration values
- Pattern match failures

**RuntimeError:**
- Download failures (network, HTTP errors)
- API failures (GitHub rate limits, 404s)
- Version extraction failures

Errors are always chained with `from err` for better debugging:
```python
try:
    strategy.discover_version(config, output_dir)
except RuntimeError as e:
    print(f"Discovery failed: {e}")
    print(f"Caused by: {e.__cause__}")
```

### Extending with Custom Strategies

To add a custom strategy:

1. **Implement the protocol:**
```python
from notapkgtool.discovery.base import register_strategy
from notapkgtool.versioning.keys import DiscoveredVersion
from pathlib import Path

class MyStrategy:
    def discover_version(self, app_config, output_dir):
        # Your implementation
        version = "1.0.0"
        file_path = output_dir / "installer.msi"
        sha256 = "abc123..."
        
        discovered = DiscoveredVersion(
            version=version,
            source="my_strategy"
        )
        return discovered, file_path, sha256
```

2. **Register the strategy:**
```python
register_strategy("my_strategy", MyStrategy)
```

3. **Use in recipes:**
```yaml
source:
  strategy: my_strategy
  # Your custom fields
```

## Cross-Platform Support

### Windows
- Native MSI extraction (msilib, _msi, or PowerShell COM)
- All features fully supported
- PowerShell fallback ensures universal compatibility

### Linux/macOS
- MSI extraction via `msitools` package
- All other features fully supported
- Installation: `apt-get install msitools` (Debian/Ubuntu)

## Current Status (v0.1.0)

### ✅ Implemented
- CLI with `check` command
- Three output modes: normal, verbose, and debug
- Config loading and merging
- HTTP static discovery strategy
- URL regex discovery strategy
- GitHub release discovery strategy
- HTTP JSON API discovery strategy
- State tracking with ETag-based caching
- Robust file downloads with conditional requests
- Version comparison (semver, numeric, lexicographic)
- MSI ProductVersion extraction
- Cross-platform support

### 🚧 Planned
- PSADT package building
- Intune upload
- Deployment wave management
- Update policies enforcement

## Quick Start

### Installation

```bash
# Install dependencies
pip install pyyaml requests

# On Linux, install msitools for MSI support
sudo apt-get install msitools
```

### Commands Overview

NAPT provides two primary commands for working with recipes:

| Command | Purpose | Network | Download | Use Case |
|---------|---------|---------|----------|----------|
| `validate` | Check recipe syntax | No | No | Development, CI/CD pre-checks |
| `discover` | Find latest version | Yes | Yes | Production runs, version discovery |

### Usage

**Validate recipe syntax (fast, no downloads):**
```bash
# Basic validation
napt validate recipes/Google/chrome.yaml

# Verbose validation (shows validation progress)
napt validate recipes/Google/chrome.yaml --verbose
```

**Discover latest version (downloads installer):**
```bash
# Basic discovery
napt discover recipes/Google/chrome.yaml

# Custom output directory
napt discover recipes/Google/chrome.yaml --output-dir ./cache

# Verbose output (shows progress details and operations)
napt discover recipes/Google/chrome.yaml --verbose

# Debug output (shows full config dumps and backend details)
napt discover recipes/Google/chrome.yaml --debug

# Stateless mode (no caching)
napt discover recipes/Google/chrome.yaml --stateless
```

## Commands Reference

### `napt validate`

Validates recipe syntax and configuration without making network calls or downloading files. This is the fastest way to check if your recipe is properly formatted.

**Purpose:**
- Development workflow (check recipes as you edit them)
- CI/CD pre-checks (validate all recipes on every commit)
- Quick syntax verification

**Features:**
- ✅ Validates YAML syntax
- ✅ Checks required fields (apiVersion, apps, source, etc.)
- ✅ Validates strategy-specific configuration
- ✅ No network calls
- ✅ No downloads
- ✅ Instant feedback

**Usage:**
```bash
napt validate <recipe-file> [options]
```

**Options:**
- `-v, --verbose` - Show validation progress and details

**Example Output:**
```
Validating recipe: recipes/Google/chrome.yaml

======================================================================
VALIDATION RESULTS
======================================================================
Recipe:      recipes/Google/chrome.yaml
Status:      VALID
App Count:   1
======================================================================

[SUCCESS] Recipe is valid!
```

**When to use:**
- Editing recipes locally
- CI/CD pipeline checks
- Before running `napt discover`
- Troubleshooting recipe configuration

---

### `napt discover`

Discovers the latest version of an application by querying the configured source and downloading the installer. This command performs the full discovery workflow including version extraction and state tracking.

**Purpose:**
- Find the latest version available from the source
- Download the installer (or use cached version via ETag)
- Extract version information from the downloaded file
- Update state file with version and caching information

**Features:**
- ✅ Discovers version using configured strategy
- ✅ Downloads installer (or HTTP 304 if cached)
- ✅ Extracts version from downloaded file
- ✅ Updates state file with ETag caching
- ✅ SHA-256 hash verification
- ✅ Atomic file writes

**Usage:**
```bash
napt discover <recipe-file> [options]
```

**Options:**
- `--output-dir DIR` - Directory to save downloaded files (default: ./downloads)
- `--state-file FILE` - State file for version tracking (default: state/versions.json)
- `--stateless` - Disable state tracking (no caching, always download)
- `-v, --verbose` - Show progress and high-level status updates
- `-d, --debug` - Show detailed debugging output (implies --verbose)

**Example Output:**
```
Discovering version for recipe: recipes/Google/chrome.yaml
Output directory: ./downloads

[1/4] Loading configuration...
[2/4] Discovering version...
[3/4] Downloading installer...
[4/4] Extracting version...
======================================================================
DISCOVERY RESULTS
======================================================================
App Name:        Google Chrome
App ID:          napt-chrome
Strategy:        http_static
Version:         142.0.7444.60
Version Source:  msi_product_version_from_file
File Path:       ./downloads/googlechromestandaloneenterprise64.msi
SHA-256:         9342a6a6ad6e81696b1294320beaa1630fb5c14f281061b40afbc9acd765ea88
Status:          success
======================================================================

[SUCCESS] Version discovered successfully!
```

**When to use:**
- Scheduled CI/CD runs to check for updates
- Before building PSADT packages
- Testing recipe discovery logic
- Preparing files for Intune upload

---

### Output Verbosity Modes

Both commands support multiple output modes to suit different debugging needs:

**1. Normal Mode** (default - no flags)
- Minimal, clean output with progress steps
- Download progress percentage
- Final validation results
- Suitable for production automation

**2. Verbose Mode** (`-v` or `--verbose`)
- All normal output plus:
  - `[CONFIG]` Configuration loading and merging details
  - `[DISCOVERY]` Discovery strategy selection
  - `[HTTP]` HTTP request/response status, headers, redirects
  - `[FILE]` File operations, paths, SHA-256 hashes
  - `[VERSION]` Version extraction methods and results
- Useful for understanding workflow and troubleshooting issues

**3. Debug Mode** (`-d` or `--debug`)
- All verbose output plus:
  - Complete YAML content from all configuration layers
  - Final merged configuration structure
  - Backend selection attempts (e.g., msilib vs PowerShell COM)
  - Maximum detail for deep troubleshooting
- Note: Debug mode automatically enables verbose mode

### Programmatic API

```python
from pathlib import Path
from notapkgtool.core import discover_recipe
from notapkgtool.validation import validate_recipe

# Validate recipe (no downloads)
result = validate_recipe(
    recipe_path=Path("recipes/Google/chrome.yaml"),
    verbose=True,
)
print(f"Status: {result['status']}")

# Discover version - Normal mode
result = discover_recipe(
    recipe_path=Path("recipes/Google/chrome.yaml"),
    output_dir=Path("./downloads"),
)

# Discover version - Verbose mode
result = discover_recipe(
    recipe_path=Path("recipes/Google/chrome.yaml"),
    output_dir=Path("./downloads"),
    verbose=True,
)

# Discover version - Debug mode
result = discover_recipe(
    recipe_path=Path("recipes/Google/chrome.yaml"),
    output_dir=Path("./downloads"),
    debug=True,
)

print(f"App: {result['app_name']}")
print(f"Version: {result['version']}")
print(f"SHA-256: {result['sha256']}")
```

## Contributing Guidelines

When adding new code:

1. **Follow existing patterns**: Use the same docstring format
2. **Add type annotations**: Full coverage for public APIs
3. **Chain exceptions**: Use `raise ... from err`
4. **Write examples**: Include docstring examples
5. **Test cross-platform**: Ensure Linux/Windows compatibility
6. **Document design decisions**: Explain "why" not just "what"

## Additional Resources

- **README.md**: Project overview and architecture
- **pyproject.toml**: Dependencies and tool configuration
- **defaults/org.yaml**: Example configuration structure
- **recipes/Google/chrome.yaml**: Example recipe

## License

GPL-3.0-only - See LICENSE file for details

---

*This documentation reflects the state of NAPT v0.1.0*
*Last updated: 2025-10-28*

