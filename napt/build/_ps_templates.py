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

"""PowerShell template loader for build script generation.

Loads .ps1 template files from the templates/ directory, resolves
# <include filename> directives, then substitutes @@var_name@@ markers
with caller-supplied values.

The @@...@@ delimiter avoids conflicts with PowerShell's $Variable syntax,
so .ps1 template files can be written as standard PowerShell without escaping.
"""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_MARKER_RE = re.compile(r"@@(\w+)@@")
_INCLUDE_RE = re.compile(r"^# <include (.+)>$", re.MULTILINE)


def _load_ps_template(name: str) -> str:
    """Load a .ps1 template file, resolving includes and returning raw text.

    Reads the named template from the templates/ directory and replaces
    any lines matching '# <include filename>' with the content of the
    referenced file. Included files are resolved relative to templates/.

    Args:
        name: Filename of the template (e.g., "detection_script.ps1").

    Returns:
        Assembled template text with includes resolved. Call
        substitute_ps_template() to fill in @@var_name@@ markers.

    Raises:
        FileNotFoundError: If the template or any included file is missing.
    """

    def _resolve_include(match: re.Match) -> str:
        return (_TEMPLATES_DIR / match.group(1).strip()).read_text(encoding="utf-8")

    content = (_TEMPLATES_DIR / name).read_text(encoding="utf-8")
    return _INCLUDE_RE.sub(_resolve_include, content)


def substitute_ps_template(template: str, **kwargs: str) -> str:
    """Substitute @@var_name@@ markers in a PS template string.

    All @@name@@ markers must have a corresponding keyword argument.
    Unknown markers raise KeyError; unrecognised PowerShell $Variables
    are left untouched.

    Args:
        template: Template text returned by _load_ps_template().
        **kwargs: Substitution values keyed by marker name.

    Returns:
        Final PowerShell script content ready to write to disk.

    Raises:
        KeyError: If a marker in the template has no matching kwarg.
    """

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        return kwargs[key]

    return _MARKER_RE.sub(_replace, template)
