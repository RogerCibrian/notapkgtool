"""Vulture whitelist: names flagged as unused that are actually alive.

Each statement below "uses" a name so vulture stops reporting it. Add an
entry only after confirming the symbol is genuinely reachable (dynamic
dispatch, template substitution, dataclass fields read by consumers) —
or, as below, when the finding is real but tracked for a separate fix.
Regenerate candidates with: python -m vulture --make-whitelist
"""

# Recipe schema fields `logging.log_format` / `logging.log_level` flow from
# build/manager.py into the DetectionConfig / RequirementsConfig dataclasses
# (registry_scripts.py, msix_scripts.py) but the script generators do not
# read them yet — a known gap: either wire them into script generation or
# deprecate the recipe fields. Whitelisted so the open question is recorded
# here instead of re-reported on every run.
_.log_format
_.log_level
