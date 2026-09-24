"""Tests for napt.powershell module.

Tests PowerShell string quoting including:
- Doubling every single-quote delimiter PowerShell recognizes
- Backtick-escaping every double-quote delimiter, backticks, and dollar signs
- Round-tripping hostile values through a real PowerShell interpreter
"""

from __future__ import annotations

import base64
from pathlib import Path
import shutil
import subprocess

import pytest

from napt.powershell import (
    ps_escape_double_quoted,
    ps_single_quote,
    strip_control_characters,
)

# PowerShell treats these as string delimiters in addition to ' and ".
SMART_SINGLE_QUOTES = ["\u2018", "\u2019", "\u201a", "\u201b"]
SMART_DOUBLE_QUOTES = ["\u201c", "\u201d", "\u201e"]

HOSTILE_VALUES = [
    "Google Chrome",
    "Bob's App",
    'App "Pro" Edition',
    "Cost$aver Pro",
    "a`b",
    "$(Write-Output INJECTED)",
    "Acme'; Write-Output INJECTED; '",
    'Acme"; Write-Output INJECTED; "',
    *[f"Acme{q}; Write-Output INJECTED; {q}x" for q in SMART_SINGLE_QUOTES],
    *[f"Acme{q}; Write-Output INJECTED; {q}x" for q in SMART_DOUBLE_QUOTES],
    "C:\\Program Files\\Caf\u00e9\\app.msi",
    "",
]


class TestPsSingleQuote:
    """Tests for formatting single-quoted PowerShell literals."""

    def test_plain_string_is_wrapped(self):
        """Tests that a plain string is wrapped in single quotes."""
        assert ps_single_quote("Google Chrome") == "'Google Chrome'"

    def test_ascii_single_quote_is_doubled(self):
        """Tests that an ASCII single quote is doubled."""
        assert ps_single_quote("Bob's App") == "'Bob''s App'"

    @pytest.mark.parametrize("quote", SMART_SINGLE_QUOTES)
    def test_smart_single_quote_is_doubled(self, quote: str):
        """Tests that each typographic single quote is doubled."""
        assert ps_single_quote(f"a{quote}b") == f"'a{quote}{quote}b'"

    def test_double_quotes_and_dollars_are_left_alone(self):
        """Tests that characters with no meaning in single quotes pass through."""
        assert ps_single_quote('$x "y" `z') == "'$x \"y\" `z'"

    def test_empty_string(self):
        """Tests that an empty string becomes an empty literal."""
        assert ps_single_quote("") == "''"


class TestPsEscapeDoubleQuoted:
    """Tests for escaping values embedded in double-quoted PowerShell strings."""

    def test_plain_string_unchanged(self):
        """Tests that a string without special characters is unchanged."""
        assert ps_escape_double_quoted("Google Chrome") == "Google Chrome"

    def test_double_quote_escaped(self):
        """Tests that double quotes are backtick-escaped."""
        assert ps_escape_double_quoted('App "Pro"') == 'App `"Pro`"'

    @pytest.mark.parametrize("quote", SMART_DOUBLE_QUOTES)
    def test_smart_double_quote_escaped(self, quote: str):
        """Tests that each typographic double quote is backtick-escaped."""
        assert ps_escape_double_quoted(f"a{quote}b") == f"a`{quote}b"

    def test_dollar_sign_escaped(self):
        """Tests that dollar signs are backtick-escaped."""
        assert ps_escape_double_quoted("Cost$aver Pro") == "Cost`$aver Pro"

    def test_backtick_escaped(self):
        """Tests that backticks are doubled."""
        assert ps_escape_double_quoted("a`b") == "a``b"

    def test_existing_backtick_does_not_absorb_added_escape(self):
        """Tests that a backtick before a quote yields two separate escapes."""
        assert ps_escape_double_quoted('`"') == '```"'

    def test_empty_string(self):
        """Tests that an empty string passes through."""
        assert ps_escape_double_quoted("") == ""


class TestStripControlCharacters:
    """Tests for removing line breaks and control characters from a value."""

    def test_plain_name_unchanged(self):
        """Tests that an ordinary name, including non-ASCII, is untouched."""
        assert strip_control_characters("Café Office™") == ("Café Office™")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Contoso\r\nViewer", "Contoso Viewer"),
            ("Contoso\nViewer", "Contoso Viewer"),
            ("Contoso\tViewer", "Contoso Viewer"),
            ("Contoso\u2028Viewer", "Contoso Viewer"),
            ("Contoso\x00\x7fViewer", "Contoso Viewer"),
            ("\r\nContoso Viewer\r\n", "Contoso Viewer"),
        ],
    )
    def test_control_characters_become_one_space(self, raw: str, expected: str):
        """Tests that each run of control characters collapses to a space."""
        assert strip_control_characters(raw) == expected


def _powershell_executables() -> list[str]:
    """Returns every PowerShell interpreter on PATH (5.1 and 7 differ)."""
    return [exe for exe in ("powershell", "pwsh") if shutil.which(exe)]


@pytest.mark.parametrize("executable", _powershell_executables())
def test_hostile_values_round_trip_through_powershell(executable: str, tmp_path: Path):
    """Tests that a real interpreter reads every quoted value back verbatim."""
    lines = ["$values = @("]
    for value in HOSTILE_VALUES:
        lines.append(f"    {ps_single_quote(value)},")
        lines.append(f'    "{ps_escape_double_quoted(value)}",')
    lines[-1] = lines[-1].rstrip(",")
    lines.append(")")
    lines.append(
        "$values | ForEach-Object {"
        " [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($_)) }"
    )
    script = tmp_path / "roundtrip.ps1"
    script.write_text("\n".join(lines), encoding="utf-8-sig")

    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    decoded = [
        base64.b64decode(line).decode("utf-8") for line in result.stdout.splitlines()
    ]
    expected = [value for value in HOSTILE_VALUES for _ in range(2)]
    assert decoded == expected
