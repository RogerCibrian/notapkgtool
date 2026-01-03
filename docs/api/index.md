# Developer Reference

Overview of NAPT's codebase structure, architecture, and key concepts for developers extending or integrating with NAPT.

## Code Organization

NAPT's codebase structure matches the module organization. Here's the file structure:

```
notapkgtool/
├── __init__.py              # Package initialization and public API exports
├── cli.py                   # Command-line interface
├── core.py                  # Main public API functions (orchestration)
├── detection.py             # Detection script generation for Intune Win32 apps
├── exceptions.py            # Exception hierarchy
├── logging.py               # Logging configuration
├── results.py               # Public API return types (dataclasses)
├── validation.py            # Recipe validation logic
│
├── build/                   # PSADT package building
│   ├── manager.py              # Package building orchestration
│   ├── packager.py             # .intunewin package creation
│   └── template.py             # PSADT template generation
│
├── config/                  # Configuration loading
│   └── loader.py               # 3-layer configuration system
│
├── discovery/               # Discovery strategies
│   ├── api_github.py           # GitHub Releases API strategy
│   ├── api_json.py             # Generic JSON API strategy
│   ├── base.py                 # Strategy protocol and registry
│   ├── url_download.py         # Direct URL download strategy
│   └── web_scrape.py           # Web scraping strategy
│
├── io/                      # File operations
│   ├── download.py             # HTTP file downloads with ETag support
│   └── upload.py               # File upload operations (planned)
│
├── policy/                  # Update policy enforcement (planned)
│   └── updates.py              # Update policy logic
│
├── psadt/                   # PSADT release management
│   └── release.py              # PSADT release download and caching
│
├── state/                   # Version tracking and caching
│   └── tracker.py              # State file management
│
└── versioning/              # Version extraction and comparison
    ├── keys.py                 # Version key extraction (DiscoveredVersion)
    └── msi.py                  # MSI version extraction backends
```

### Data Flow

```
Recipe YAML
    ↓
[config/loader.py] Load and merge configuration
    ↓
[core.py] Orchestrate workflow
    ↓
[discovery/] Discover version and download
    ↓
[state/tracker.py] Update version cache
    ↓
[build/manager.py] Build PSADT package
    ↓
[build/packager.py] Create .intunewin
    ↓
Result (dataclass)
```

## Quick Start

- **Using NAPT as a library:** Start with [`core.py`](core.md) - `discover_recipe()`, `build_package()`, `create_intunewin()`
- **Extending the CLI:** See [`cli.py`](cli.md) for command registration patterns
- **Adding discovery strategies:** Implement `DiscoveryStrategy` protocol from [`discovery/base.py`](discovery.md)

## Key Concepts

- **Discovery Strategies:** Protocol-based, stateless, registered in global registry. Two paths: version-first (api_github, api_json, web_scrape) and file-first (url_download with ETag)
- **Configuration:** 3-layer system (org → vendor → recipe) with deep merging
- **State Management:** Tracks versions in `state/versions.json` for caching
- **Exceptions:** All NAPT domain errors use custom exceptions inheriting from `NAPTError` (ConfigError, NetworkError, PackagingError) - allows catching all NAPT errors or specific types
- **Return Types:** Frozen dataclasses from `results.py` for public API functions only (type-safe, immutable returns)

## Design Principles

- Single Responsibility per module
- Protocol-based interfaces (typing.Protocol)
- Stateless strategies (instantiated on-demand)
- Structured returns (frozen dataclasses)
- Exception-based error handling
- Immutable configuration

## Extending NAPT

- **New discovery strategy:** Implement `DiscoveryStrategy`, register with `register_strategy()`, add to `discovery/__init__.py`
- **New CLI command:** Add parser in `cli.py`, create `cmd_<name>()` handler, register with `set_defaults()`
- **New config option:** Update schema in `config/loader.py`, add validation in `validation.py`, document in recipe schema

## See Also

- [Core API](core.md) - Main orchestration functions
- [Discovery API](discovery.md) - Discovery strategy implementations
- [Build API](build.md) - Package building functions
- [Config API](config.md) - Configuration loading
- [Exceptions API](exceptions.md) - Exception hierarchy

