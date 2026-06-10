"""Tests for napt.build._ps_templates module.

Tests PowerShell template handling including:
- Escaping values for double-quoted PowerShell strings
- Escaped values surviving template substitution
"""

from __future__ import annotations

from pathlib import Path

from napt.build._ps_templates import escape_ps_string
from napt.build.registry_scripts import (
    DetectionConfig,
    generate_detection_script,
)

# All tests in this file are unit tests (fast, mocked)


class TestEscapePsString:
    """Tests for escaping values embedded in double-quoted PowerShell strings."""

    def test_plain_string_unchanged(self):
        """Tests that a string without special characters is unchanged."""
        assert escape_ps_string("Google Chrome") == "Google Chrome"

    def test_double_quote_escaped(self):
        """Tests that double quotes are backtick-escaped."""
        assert escape_ps_string('App "Pro" Edition') == 'App `"Pro`" Edition'

    def test_dollar_sign_escaped(self):
        """Tests that dollar signs are backtick-escaped."""
        assert escape_ps_string("Cost$aver Pro") == "Cost`$aver Pro"

    def test_backtick_escaped(self):
        """Tests that backticks are doubled."""
        assert escape_ps_string("a`b") == "a``b"

    def test_backtick_escaped_before_other_characters(self):
        """Tests that pre-existing backticks don't double-escape added ones."""
        assert escape_ps_string('`"') == '```"'

    def test_empty_string(self):
        """Tests that an empty string passes through."""
        assert escape_ps_string("") == ""


class TestEscapedGeneration:
    """Tests that special characters in config values reach scripts escaped."""

    def test_app_name_with_quotes_is_escaped(self, tmp_path: Path):
        """Tests that quotes in app_name are escaped in the generated script."""
        config = DetectionConfig(
            app_name='VMware Horizon "FIPS" Client',
            version="1.0.0",
        )
        output_path = tmp_path / "detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")
        assert 'VMware Horizon `"FIPS`" Client' in content
        assert 'VMware Horizon "FIPS" Client' not in content

    def test_app_name_with_dollar_is_escaped(self, tmp_path: Path):
        """Tests that dollar signs in app_name are escaped in the script."""
        config = DetectionConfig(
            app_name="Cost$aver Pro",
            version="1.0.0",
        )
        output_path = tmp_path / "detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")
        assert "Cost`$aver Pro" in content
        assert "Cost$aver Pro" not in content
