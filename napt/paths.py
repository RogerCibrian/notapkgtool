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

"""Safe handling of externally supplied names that become filesystem paths.

Three kinds of text reach the filesystem from outside NAPT: the filename a
download server announces, the recipe ``id``, and the version reported by an
installer or scraped from a page. Joined into a path unchecked, a value
containing ``..`` leaves the folder NAPT meant to use, and a filename can
carry characters that run as code once it lands in a PowerShell script.
"""

from __future__ import annotations

import re

# Names Windows reserves for devices, with or without an extension.
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{n}" for n in range(1, 10)]
    + [f"LPT{n}" for n in range(1, 10)]
)

# Characters Windows forbids in a filename, plus ASCII control characters.
_FORBIDDEN_RE = re.compile(r'[<>:"|?*\x00-\x1f\x7f]')

# Characters that act inside a quoted PowerShell string, which is where a
# recipe puts the filename: "$" and the backtick expand or escape in double
# quotes, and every quote here closes a string. The escapes are the
# typographic single quotes (U+2018 to U+201B) and double quotes (U+201C to
# U+201E) that PowerShell accepts as delimiters. ";" is included because it is
# rare in real names and ends the statement if the name is left unquoted.
#
# This does not make unquoted use safe. Parentheses also run as code there
# ("Setup (calc).exe" runs calc), and they are too common in real filenames to
# replace. A recipe must quote {{installer_filename}}.
_POWERSHELL_ACTIVE_RE = re.compile("[$;`'\u2018\u2019\u201a\u201b\u201c\u201d\u201e]")

# A path component NAPT will create a folder from: starts with a letter or
# digit, then letters, digits, dot, hyphen, underscore, or plus.
_SAFE_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


def _is_reserved(name: str) -> bool:
    """Reports whether Windows treats the name as a device, such as NUL.txt."""
    return name.split(".", 1)[0].strip().upper() in _RESERVED_NAMES


def safe_filename(raw: str) -> str | None:
    """Reduces a server-supplied filename to one safe to save and to script.

    Keeps only the final path component, so ``..`` segments and absolute
    paths cannot move the file. Removes characters Windows forbids and
    replaces the characters that act inside a PowerShell string with an
    underscore, because the name is later substituted into recipe-authored
    PowerShell whose quoting NAPT does not control.

    Args:
        raw: Filename from a Content-Disposition header or a URL path,
            already percent-decoded.

    Returns:
        The cleaned filename, or None when nothing usable remains (empty,
        only dots, or a reserved device name).

    Example:
        Clean a hostile filename:
            ```python
            safe_filename("../../setup$(calc).msi")  # Returns: "setup_(calc).msi"
            safe_filename("..")                      # Returns: None
            ```

    """
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = _FORBIDDEN_RE.sub("", name)
    name = _POWERSHELL_ACTIVE_RE.sub("_", name)
    # Windows silently drops trailing dots and spaces, so "evil.exe." and
    # "evil.exe" are the same file.
    name = name.strip().rstrip(". ")
    if not name or _is_reserved(name):
        return None
    return name


def is_safe_path_component(value: str) -> bool:
    """Reports whether a value can be used as a folder name as-is.

    Accepts letters, digits, dot, hyphen, underscore, and plus, starting with
    a letter or digit. Rejects anything containing a path separator or ``..``,
    names ending in a dot, and reserved device names.

    Args:
        value: Recipe ``id``, a version string, or a release tag.

    Returns:
        True when joining the value onto a directory stays inside it.

    """
    return (
        _SAFE_COMPONENT_RE.fullmatch(value) is not None
        and ".." not in value
        and not value.endswith(".")
        and not _is_reserved(value)
    )
