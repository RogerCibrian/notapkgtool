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

"""PowerShell string quoting, file encoding, and the build-host script runner.

Values written into PowerShell source (recipe fields, installer metadata,
file paths) can be vendor-controlled, and a value that closes its string
early runs as code on the endpoint or the build host.

Scripts NAPT runs on the build host to read installer metadata hand their
results back through a UTF-8 file rather than stdout; see
[run_powershell_lines][napt.powershell.run_powershell_lines] for why.

PowerShell treats typographic quotes as string delimiters too: U+2018 to
U+201B close a single-quoted string, U+201C to U+201E a double-quoted one.
Both quoting functions escape the full sets. A value that lands outside a
string, such as an app name in a comment line, needs a different guard: a
line break ends the comment and the rest of the value runs as code, so
[strip_control_characters][napt.powershell.strip_control_characters] removes
line breaks and the other control characters first.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile

from napt.exceptions import PackagingError

# Encoding for every .ps1 file NAPT writes: UTF-8 with a byte order mark.
# Windows PowerShell 5.1 (which Intune uses for detection and requirements
# scripts) reads a file without a BOM as the ANSI code page. That garbles
# non-ASCII app names, and it undoes the quoting below: the UTF-8 bytes of an
# ordinary letter such as U+00D3 decode to a typographic quote (C3 93 reads as
# a left double quotation mark in cp1252), which then closes the string.
PS_SCRIPT_ENCODING = "utf-8-sig"

# Characters PowerShell's tokenizer treats as a single-quote delimiter: the
# ASCII quote, then left, right, low-9, and high-reversed-9 quotation marks.
_SINGLE_QUOTES = "'\u2018\u2019\u201a\u201b"
# Characters PowerShell's tokenizer treats as a double-quote delimiter: the
# ASCII quote, then left, right, and low-9 double quotation marks.
_DOUBLE_QUOTES = '"\u201c\u201d\u201e'

_SINGLE_QUOTE_RE = re.compile(f"[{_SINGLE_QUOTES}]")
_DOUBLE_QUOTED_SPECIAL_RE = re.compile(f"[`${_DOUBLE_QUOTES}]")

# C0 controls (including CR and LF, the only characters that end a PowerShell
# comment), DEL, and the Unicode line and paragraph separators, which do not
# end a comment but are invisible and have no place in a name or filename.
_CONTROL_RE = re.compile("[\x00-\x1f\x7f\u2028\u2029]+")


def run_powershell_lines(
    script: str, *, out_var: str, timeout: int, what: str
) -> list[str]:
    """Runs a PowerShell script that hands its results back through a file.

    PowerShell writes captured stdout in the console's OEM code page (cp437
    on English Windows), which Python would decode as the locale code page
    (cp1252), mangling every non-ASCII character of a product name or an
    icon name. Changing the console's code page from inside the script
    would fix that but leaks into the user's terminal for the rest of the
    session. So the script writes its values as UTF-8 with
    ``[System.IO.File]::WriteAllLines`` to the file named by the environment
    variable ``out_var``, and this function reads them back. The path
    travels in the environment, keeping it out of the script text.

    Args:
        script: The PowerShell source. It writes its results to
            ``$env:<out_var>`` and exits non-zero on failure.
        out_var: Name of the environment variable that carries the output
            file's path.
        timeout: Seconds to wait for the script.
        what: What the script does, for messages (``"PowerShell MSI
            query"``).

    Returns:
        The lines of the output file.

    Raises:
        PackagingError: If the script exits non-zero (the message carries
            its stderr), times out, or PowerShell cannot be launched.

    """
    with tempfile.NamedTemporaryFile(
        prefix="napt-ps-", suffix=".txt", delete=False
    ) as handle:
        out_path = Path(handle.name)
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env={**os.environ, out_var: str(out_path)},
        )
        return out_path.read_text(encoding="utf-8-sig").splitlines()
    except subprocess.CalledProcessError as err:
        stderr = err.stderr if err.stderr else "No stderr captured"
        raise PackagingError(
            f"{what} failed (exit {err.returncode}). stderr: {stderr}"
        ) from err
    except subprocess.TimeoutExpired:
        raise PackagingError(f"{what} timed out") from None
    except OSError as err:
        raise PackagingError(f"{what} failed: {err}") from err
    finally:
        out_path.unlink(missing_ok=True)


def ps_single_quote(value: str) -> str:
    """Formats a value as a single-quoted PowerShell string literal.

    Single-quoted strings are verbatim: no variable expansion, no
    subexpressions, no backtick escapes. The only characters with meaning
    are the quote delimiters, which are escaped by doubling. Prefer this
    form whenever the surrounding PowerShell allows it.

    Args:
        value: Raw text to embed.

    Returns:
        The literal including its surrounding quotes.

    Example:
        Quote an MSI product name:
            ```python
            ps_single_quote("Bob's App")  # Returns: "'Bob''s App'"
            ```

    """
    return "'" + _SINGLE_QUOTE_RE.sub(lambda m: m.group(0) * 2, value) + "'"


def ps_escape_double_quoted(value: str) -> str:
    """Escapes a value for use inside a double-quoted PowerShell string.

    Backticks, dollar signs, and every double-quote delimiter are prefixed
    with a backtick so the value reads as literal text instead of closing
    the string, expanding a variable, or running a ``$(...)`` subexpression.

    Args:
        value: Raw text destined for the inside of a double-quoted string.

    Returns:
        The escaped text, without surrounding quotes.

    Example:
        Escape an app name for a template placeholder in double quotes:
            ```python
            ps_escape_double_quoted('5" Floppy $1')  # Returns: '5`" Floppy `$1'
            ```

    """
    return _DOUBLE_QUOTED_SPECIAL_RE.sub(lambda m: "`" + m.group(0), value)


def strip_control_characters(value: str) -> str:
    """Removes line breaks and other control characters from a value.

    Quoting keeps a value safe inside a string, but an app name is also
    written into a comment line and a script filename, where a line break
    ends the comment (the remainder runs as code) or makes the filename
    invalid. Each run of control characters becomes a single space.

    Args:
        value: Raw text, typically an app name from installer metadata or
            a recipe.

    Returns:
        The text with every run of control characters replaced by a space
        and surrounding whitespace trimmed.

    Example:
        Clean a display name read from an installer manifest:
            ```python
            app_name = strip_control_characters(metadata.display_name)
            ```

    """
    return _CONTROL_RE.sub(" ", value).strip()
