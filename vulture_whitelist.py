"""Vulture whitelist: names flagged as unused that are actually alive.

Each statement below "uses" a name so vulture stops reporting it. Add an
entry only after confirming the symbol is genuinely reachable (dynamic
dispatch, template substitution, dataclass fields read by consumers), or
when the finding is real but tracked for a separate fix.
Regenerate candidates with: python -m vulture --make-whitelist
"""

# napt/upstream/refresh.py: RecipeStatus.old_blob reaches the user through
# dataclasses.asdict in `napt upstream check --format json`, which vulture
# cannot see.
_.old_blob
