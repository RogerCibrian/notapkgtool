# NAPT Documentation Overview

## Project Structure

NAPT (Not a Pkg Tool) is a Python-based CLI tool for automating Windows application packaging and deployment to Microsoft Intune using PSAppDeployToolkit (PSADT).

### Package Organization

```
notapkgtool/
├── __init__.py              # Main package exports
├── cli.py                   # Command-line interface (argparse)
├── core.py                  # High-level orchestration
├── config/
│   ├── __init__.py          # Config package exports
│   └── loader.py            # YAML loading and merging
├── discovery/
│   ├── __init__.py          # Discovery package exports
│   ├── base.py              # Strategy protocol and registry
│   └── http_static.py       # Static URL download strategy
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
    └── url_regex.py         # URL regex extraction (planned)
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
- Config loading and merging
- HTTP static discovery strategy
- Robust file downloads
- Version comparison (semver, numeric, lexicographic)
- MSI ProductVersion extraction
- Cross-platform support

### 🚧 Planned
- Additional discovery strategies (url_regex, github_release, http_json)
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

### Usage

```bash
# Validate a recipe
python -m notapkgtool.cli check recipes/Google/chrome.yaml

# Custom output directory
python -m notapkgtool.cli check recipes/Google/chrome.yaml --output-dir ./cache

# Verbose errors
python -m notapkgtool.cli check recipes/Google/chrome.yaml --verbose
```

### Programmatic API

```python
from pathlib import Path
from notapkgtool.core import check_recipe

result = check_recipe(
    recipe_path=Path("recipes/Google/chrome.yaml"),
    output_dir=Path("./downloads"),
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
*Last updated: 2025-10-23*

