# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Provenance stamp for NAPT-managed Intune apps.

The stamp is a single machine-parseable line written to the Intune notes
field of every app NAPT publishes:

    napt/v1 id=<recipe-id> entry=<install|update> sha256=<installer-hash>

It serves two purposes: ownership (presence of the stamp marks an app as
NAPT-managed; unstamped apps are never touched) and identity (the recipe
id, entry type, and installer hash tie the Intune object to a specific
publish instance recorded in deployment state). The notes field is
reserved for NAPT and is not recipe-configurable.
"""

from __future__ import annotations

from napt.exceptions import ConfigError

# Maximum length Intune accepts for the mobileApp notes field.
NOTES_MAX_LENGTH = 1024

STAMP_PREFIX = "napt/v1"

# Intune app entry types NAPT publishes per recipe.
ENTRY_INSTALL = "install"
ENTRY_UPDATE = "update"

_REQUIRED_KEYS = ("id", "entry", "sha256")


def build_stamp(recipe_id: str, entry: str, sha256: str) -> str:
    """Builds the provenance stamp for one Intune app entry.

    Args:
        recipe_id: Recipe identifier (from recipe's 'id' field).
        entry: Entry type, either "install" or "update".
        sha256: SHA-256 hex digest of the source installer.

    Returns:
        The stamp line to write to the Intune notes field.

    Raises:
        ConfigError: If the stamp would exceed Intune's notes field length
            limit (only possible with an extremely long recipe id).

    """
    stamp = f"{STAMP_PREFIX} id={recipe_id} entry={entry} sha256={sha256}"
    if len(stamp) > NOTES_MAX_LENGTH:
        raise ConfigError(
            f"Provenance stamp for '{recipe_id}' is {len(stamp)} characters, "
            f"over Intune's {NOTES_MAX_LENGTH}-character notes field limit. "
            "Shorten the recipe id."
        )
    return stamp


def parse_stamp(notes: str | None) -> dict[str, str] | None:
    """Parses a provenance stamp from an Intune notes field value.

    Args:
        notes: The notes field content, or None.

    Returns:
        A dict with "id", "entry", and "sha256" keys, or None when the
            notes do not carry a complete NAPT stamp.

    """
    if not notes or not notes.startswith(f"{STAMP_PREFIX} "):
        return None

    fields: dict[str, str] = {}
    for token in notes.split()[1:]:
        key, sep, value = token.partition("=")
        if sep and value:
            fields[key] = value

    if any(key not in fields for key in _REQUIRED_KEYS):
        return None
    return {key: fields[key] for key in _REQUIRED_KEYS}
