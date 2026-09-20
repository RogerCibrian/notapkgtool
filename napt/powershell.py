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

"""PowerShell string quoting and file encoding for generated scripts.

Values written into PowerShell source (recipe fields, installer metadata,
file paths) can be vendor-controlled, and a value that closes its string
early runs as code on the endpoint or the build host.

PowerShell treats typographic quotes as string delimiters too: U+2018 to
U+201B close a single-quoted string, U+201C to U+201E a double-quoted one.
Both functions escape the full sets.
"""

from __future__ import annotations

import re

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
