# Developer Reference

Overview of NAPT's codebase structure, architecture, and key concepts for contributors.

## Code Organization

NAPT's codebase structure matches the module organization. Here's the file structure:

```
napt/
├── __init__.py              # Package overview docstring
├── exceptions.py            # Exception hierarchy
├── logging.py               # Logging configuration
├── results.py               # Result dataclasses returned by napt commands
├── validation.py            # Recipe validation logic
├── version.py               # NAPT's own version, read from package metadata
│
├── auth/                    # Microsoft Entra ID authentication
│   ├── credentials.py          # Token resolution and the napt auth login session
│   └── registration.py         # App registration provisioning (napt auth setup)
│
├── build/                   # PSADT package building
│   ├── manager.py              # Package building orchestration
│   ├── packager.py             # .intunewin package creation
│   └── template.py             # PSADT template generation
│
├── cli/                     # Command-line interface (one module per command)
│   ├── main.py                 # Parser assembly and dispatch
│   ├── auth.py                 # napt auth login/logout/status/setup
│   ├── build.py                # napt build
│   ├── discover.py             # napt discover
│   ├── init.py                 # napt init
│   ├── package.py              # napt package
│   ├── promote.py              # napt promote plan/apply
│   ├── status.py               # napt status
│   ├── upload.py               # napt upload
│   └── validate.py             # napt validate
│
├── config/                  # Configuration loading
│   └── loader.py               # 3-layer configuration system
│
├── discovery/               # Discovery strategies
│   ├── api_github.py           # GitHub Releases API strategy
│   ├── api_json.py             # Generic JSON API strategy
│   ├── base.py                 # Strategy protocol and shared helpers
│   ├── registry.py             # Strategy name-to-class table
│   ├── url_download.py         # Direct URL download strategy
│   └── web_scrape.py           # Web scraping strategy
│
├── download/                # HTTP file downloads
│   └── download.py             # HTTP downloads with ETag support
│
├── graph/                   # Microsoft Graph client
│   ├── client.py               # HTTP transport with retry and error mapping
│   └── intune.py               # Win32 app upload, queries, and assignments
│
├── psadt/                   # PSADT release management
│   └── release.py              # PSADT release download and caching
│
├── state/                   # State persistence
│   ├── cache.py                # Disposable cache of discovered versions and ETags
│   ├── deployment.py           # Authoritative per-app record of published and pending releases
│   └── stamp.py                # Provenance stamp linking Intune apps to deployment state
│
├── upload/                  # Intune upload pipeline
│   ├── manager.py              # Upload orchestration
│   └── intunewin.py            # .intunewin package parser
│
└── versioning/              # Version extraction and comparison
    ├── compare.py              # Version comparison (is_newer)
    ├── msi.py                  # MSI metadata extraction backends
    └── msix.py                 # MSIX metadata extraction (AppxManifest)
```

### Data Flow

```
Recipe YAML
    ↓
[config/loader.py] Load and merge configuration
    ↓
[discovery/] Discover version and download
    ↓
[state/cache.py] Update discovery cache
    ↓
[state/deployment.py] Record pending release
    ↓
[build/manager.py] Build PSADT package
    ↓
[build/packager.py] Create .intunewin
    ↓
[upload/manager.py] Upload to Microsoft Intune
    ↓
Result (dataclass)
```

## Quick Start

- **Adding a CLI command:** See [`cli/`](cli.md) for command registration patterns
- **Adding discovery strategies:** Implement `DiscoveryStrategy` protocol from [`discovery/base.py`](discovery.md)

## Key Concepts

- **Discovery Strategies:** Protocol-based, stateless, listed in an explicit registry table (api_github, api_json, web_scrape). All return a `RemoteVersion` from configuration alone. The orchestrator runs the result through `resolve_with_cache` to skip the download when the version is unchanged. `url_download` is a separate flow (not a registered strategy) because it must download the file to determine the version.
- **Configuration:** 3-layer system (org → vendor → recipe) with deep merging
- **State Management:** Two kinds with opposite philosophies — the disposable discovery cache (`cache/discovery.json`) for download optimization, and authoritative per-app deployment state (`state/deployment/<id>.json`) recording what is published and pending
- **Exceptions:** All NAPT domain errors use custom exceptions inheriting from `NAPTError` (ConfigError, NetworkError, PackagingError, StateError, AuthError) - allows catching all NAPT errors or specific types
- **Return Types:** Frozen dataclasses from `results.py`, one per napt command's underlying operation (type-safe, immutable returns)

## Design Principles

- Single Responsibility per module
- Protocol-based interfaces (typing.Protocol)
- Stateless strategies (instantiated on-demand)
- Structured returns (frozen dataclasses)
- Exception-based error handling
- Immutable configuration

## Common contributor tasks

- **New discovery strategy:** Implement `DiscoveryStrategy` in a new module under `discovery/`, then add it to the table in `discovery/registry.py`
- **New CLI command:** Create `napt/cli/<command>.py` with the `cmd_<name>()` handler and a `register(subparsers)` hook, call `register` from `main()` in `napt/cli/main.py`, and add `tests/cli/test_<command>.py` (strict one module per command)
- **New config option:** Update schema in `config/loader.py`, add validation in `validation.py`, document in recipe schema

## See Also

- [Discovery manager](discovery-manager.md) - Discovery orchestration
- [Discovery API](discovery.md) - Discovery strategy implementations
- [Build API](build.md) - Package building functions
- [Upload API](upload.md) - Intune upload pipeline
- [Auth API](auth.md) - Entra ID sign-in and app registration
- [Graph API](graph.md) - Microsoft Graph transport and Intune calls
- [Config API](config.md) - Configuration loading
- [Exceptions API](exceptions.md) - Exception hierarchy

