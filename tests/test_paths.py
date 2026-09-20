"""Tests for napt.paths module.

Tests the handling of externally supplied names including:
- Reducing a server-supplied filename to a safe final component
- Accepting only plain folder names for ids and versions
"""

from __future__ import annotations

import pytest

from napt.paths import is_safe_path_component, safe_filename

BACKSLASH = chr(92)

# Typographic quotes, which PowerShell accepts as string delimiters. Written as
# escapes because they are nearly indistinguishable from ' and " on screen.
RSQUO = "\u2019"  # right single quotation mark
RDQUO = "\u201d"  # right double quotation mark


class TestSafeFilename:
    """Tests for cleaning a filename announced by a download server."""

    @pytest.mark.parametrize(
        "name",
        ["setup.msi", "Setup (x64)+1.exe", "7z2501-x64.msi", "Caf\u00e9.exe"],
    )
    def test_ordinary_names_are_unchanged(self, name: str):
        """Tests that a harmless filename passes through untouched."""
        assert safe_filename(name) == name

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("../../evil.exe", "evil.exe"),
            (f"..{BACKSLASH}..{BACKSLASH}evil.exe", "evil.exe"),
            ("C:/Windows/System32/evil.exe", "evil.exe"),
            (f"{BACKSLASH}{BACKSLASH}server{BACKSLASH}share{BACKSLASH}x.msi", "x.msi"),
            ("/etc/cron.d/job", "job"),
        ],
    )
    def test_only_the_final_component_is_kept(self, raw: str, expected: str):
        """Tests that path segments and absolute paths are discarded."""
        assert safe_filename(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("setup$(calc).msi", "setup_(calc).msi"),
            ("a`b.msi", "a_b.msi"),
            ("Bob's App.exe", "Bob_s App.exe"),
            (f"a{RSQUO}b{RDQUO}.msi", "a_b_.msi"),
            ("setup;calc.exe", "setup_calc.exe"),
        ],
    )
    def test_powershell_active_characters_are_replaced(self, raw: str, expected: str):
        """Tests that characters which act in a PowerShell string become _."""
        assert safe_filename(raw) == expected

    def test_forbidden_and_control_characters_are_removed(self):
        """Tests that characters Windows forbids are dropped."""
        assert safe_filename('a<b>c:"d|e?f*g\x00\x1f.msi') == "abcdefg.msi"

    def test_trailing_dots_and_spaces_are_removed(self):
        """Tests that a name Windows would silently rewrite is normalized."""
        assert safe_filename("evil.exe. ") == "evil.exe"

    @pytest.mark.parametrize("raw", ["", ".", "..", "...", "  ", "NUL", "con.msi"])
    def test_unusable_names_return_none(self, raw: str):
        """Tests that an empty, dots-only, or reserved name is refused."""
        assert safe_filename(raw) is None


class TestIsSafePathComponent:
    """Tests for accepting a value as a folder name."""

    @pytest.mark.parametrize(
        "value",
        [
            "napt-chrome",
            "1.2.3",
            "150.0.7871.47",
            "2.53.0.windows.1",
            "1.2.3+build5",
            "v1",
            "app_id",
        ],
    )
    def test_plain_names_are_accepted(self, value: str):
        """Tests that ids and versions seen in practice are accepted."""
        assert is_safe_path_component(value)

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "..",
            "1..2",
            f"..{BACKSLASH}x",
            "../x",
            "a/b",
            "2.0 / stable",
            "2.0 beta",
            ".hidden",
            "-dash",
            "1.0.",
            "CON",
            "nul.1",
            "a:b",
            "$(calc)",
        ],
    )
    def test_unsafe_names_are_rejected(self, value: str):
        """Tests that separators, dot runs, and reserved names are rejected."""
        assert not is_safe_path_component(value)
