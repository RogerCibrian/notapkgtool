# Developer reference

How the `napt/` package is laid out.

## Code organization

```
napt/
├── __init__.py              # Package overview docstring
├── exceptions.py            # Exception hierarchy
├── logging.py               # Logging configuration
├── paths.py                 # Safe filenames and folder names from external input
├── powershell.py            # PowerShell string quoting for generated scripts
├── results.py               # Result dataclasses returned by napt commands
├── validation.py            # Recipe validation logic
├── version.py               # NAPT's own version, read from package metadata
│
├── auth/                    # Microsoft Entra ID authentication
│   ├── credentials.py          # Token resolution and the napt auth login session
│   └── registration.py         # App registration provisioning (napt auth setup)
│
├── build/                   # PSADT package building
│   ├── _ps_templates.py        # Loads the .ps1 templates for generated scripts
│   ├── icons.py                # App icon extraction from installers
│   ├── manager.py              # Package building orchestration
│   ├── msix_scripts.py         # MSIX detection and requirements scripts
│   ├── packager.py             # .intunewin package creation
│   ├── registry_scripts.py     # Registry detection and requirements scripts
│   ├── template.py             # PSADT template generation
│   └── templates/              # PowerShell templates for the generated scripts
│
├── cli/                     # Command-line interface (one module per command)
│   ├── __main__.py             # Runs the CLI as python -m napt.cli
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
│   ├── defaults.py             # Code defaults (the first configuration layer)
│   └── loader.py               # Layered configuration loader
│
├── discovery/               # Discovery strategies
│   ├── api_github.py           # GitHub Releases API strategy
│   ├── api_json.py             # Generic JSON API strategy
│   ├── base.py                 # Strategy protocol and shared helpers
│   ├── manager.py              # Discovery orchestration (napt discover)
│   ├── registry.py             # Strategy name-to-class table
│   ├── resolve.py              # Downloads the installer and settles its version
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
├── promote/                 # Deployment ring promotion
│   ├── applier.py              # Executes plans against Intune
│   ├── drift.py                # Assignment drift detection
│   ├── planner.py              # Computes promotions and writes plan files
│   ├── preflight.py            # Assignment group validation
│   └── reconcile.py            # Recovers lost publish state writebacks
│
├── psadt/                   # PSADT release management
│   └── release.py              # PSADT release download and caching
│
├── state/                   # State persistence
│   ├── deployment.py           # Authoritative per-app record of published and pending releases
│   └── stamp.py                # Provenance stamp linking Intune apps to deployment state
│
├── upload/                  # Intune upload pipeline
│   ├── manager.py              # Upload orchestration
│   └── intunewin.py            # .intunewin package parser
│
└── versioning/              # Version extraction and ordering
    ├── msi.py                  # MSI metadata extraction backends
    ├── msix.py                 # MSIX metadata extraction (AppxManifest)
    └── ordering.py             # Version ordering, mirroring the device-side comparison
```

### Data flow

```
Recipe YAML
    ↓
[config/loader.py] Load and merge configuration
    ↓
[discovery/] Discover version and download
    ↓
[state/deployment.py] Record pending release
    ↓
[build/manager.py] Build PSADT package
    ↓
[build/packager.py] Create .intunewin
    ↓
[upload/manager.py] Upload to Microsoft Intune
    ↓
[promote/planner.py] Plan ring promotion (one plan file per app)
    ↓
[promote/applier.py] Apply plans to Intune and update deployment state
```

## Key concepts

- **Discovery strategies:** version-first strategies (api_github, api_json,
  web_scrape) implement `DiscoveryStrategy` and are listed in
  `discovery/registry.py`; `url_download` is a separate flow.
  Both end in `discovery/resolve.py` (see [Discovery API](discovery.md)).
- **Configuration:** Five layers (code defaults, org, vendor, parent, recipe),
  merged with dicts deep-merged and lists replaced
- **State management:** Per-app deployment state
  (`state/deployment/<id>.json`) is the authoritative record of what is
  published and pending.
  The downloads folder holds installers; discovery reuses what it finds
  there, and build takes the file whose SHA-256 matches the recorded release.
- **Exceptions:** All NAPT domain errors use custom exceptions inheriting from
  `NAPTError` (ConfigError, NetworkError, PackagingError, StateError,
  AuthError)
- **Return types:** Frozen dataclasses from `results.py`, one per napt
  command's underlying operation

