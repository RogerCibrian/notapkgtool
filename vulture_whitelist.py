"""Vulture whitelist: names flagged as unused that are actually alive.

Each statement below "uses" a name so vulture stops reporting it. Add an
entry only after confirming the symbol is genuinely reachable (dynamic
dispatch, template substitution, dataclass fields read by consumers), or
when the finding is real but tracked for a separate fix.
Regenerate candidates with: python -m vulture --make-whitelist
"""

# napt/upstream/git.py: the transport lands one PR ahead of the commands
# that drive it (napt upstream add, check, update). Remove these entries
# when napt/cli/upstream.py calls them.
_.commit_for
_.ls_remote
_.list_recipe_files
_.read_file
