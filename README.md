notapkgtool/
  cli.py              # argparse/typer commands map 1:1 to docs
  core.py             # orchestrates: load -> discover -> package -> upload
  config/
    loader.py         # YAML load, deep-merge (org -> vendor -> recipe), schema validation
    models.py         # @dataclass(frozen=True) for config objects
  discovery/
    base.py           # Strategy Protocol/ABC + registry
    http_static.py
    url_regex.py
    github_release.py        # later
    http_json.py             # later
  versioning/
    keys.py           # version_key_any, compare_any, is_newer_any
    msi.py            # MSI ProductVersion
    pe.py             # EXE FileVersion
  packaging/
    psadt.py          # template fetch/inject/build .intunewin
  io/
    download.py       # atomic, conditional GETs
    upload.py         # Intune, storage adapters
  policy/
    updates.py        # waves/rings logic
