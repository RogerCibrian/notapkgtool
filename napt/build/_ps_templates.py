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
# <include filename> directives, then substitutes $Napt* PowerShell
variables with caller-supplied values via string replacement.

Templates are written as valid PowerShell with $Napt*-prefixed variables
as placeholders. Python replaces these with concrete values at build time.
"""

from __future__ import annotations

from pathlib import Path
import re

_TEMPLATES_DIR = Path(__file__).parent / "templates"
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
        substitute_ps_template() to fill in $Napt* variables.

    Raises:
        FileNotFoundError: If the template or any included file is missing.
    """

    def _resolve_include(match: re.Match) -> str:
        return (_TEMPLATES_DIR / match.group(1).strip()).read_text(encoding="utf-8")

    content = (_TEMPLATES_DIR / name).read_text(encoding="utf-8")
    return _INCLUDE_RE.sub(_resolve_include, content)


def substitute_ps_template(template: str, substitutions: dict[str, str]) -> str:
    """Substitutes $Napt* variables in a PowerShell template string.

    All substitutions are applied in a single regex pass so that
    already-substituted text is never re-processed. Keys are matched
    longest-first to prevent shorter variables from partially matching
    longer ones (e.g., "$NaptLogBaseName" inside "$NaptLogBaseNameUser").

    After substitution, verifies that no $Napt* placeholders remain
    in the output.

    Args:
        template: Template text returned by _load_ps_template().
        substitutions: Mapping of placeholder strings to their values.

    Returns:
        Final PowerShell script content ready to write to disk.

    Raises:
        ValueError: If any $Napt* placeholders remain after substitution.
    """
    # Sort keys longest-first so e.g. $NaptLogBaseNameUser (if it were
    # a key) would match before $NaptLogBaseName.
    pattern = re.compile(
        "|".join(
            re.escape(k) for k in sorted(substitutions, key=len, reverse=True)
        )
    )
    result = pattern.sub(lambda m: substitutions[m.group(0)], template)

    remaining = re.findall(r"\$Napt[A-Z]\w*", result)
    if remaining:
        raise ValueError(
            f"Unreplaced $Napt* variables in template: {sorted(set(remaining))}"
        )

    return result
