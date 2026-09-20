"""Tests for napt.build._ps_templates module.

Tests that escaped config values survive template substitution into the
generated scripts.
"""

from __future__ import annotations

from pathlib import Path

from napt.build.registry_scripts import (
    DetectionConfig,
    generate_detection_script,
)

# All tests in this file are unit tests (fast, mocked)

# Typographic double quotes, which PowerShell accepts as string delimiters.
# Written as escapes because they are nearly indistinguishable from " on screen.
LDQUO = "\u201c"  # left double quotation mark
RDQUO = "\u201d"  # right double quotation mark


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

    def test_app_name_with_smart_double_quote_is_escaped(self, tmp_path: Path):
        """Tests that a typographic double quote cannot close the string."""
        config = DetectionConfig(
            app_name=f"Acme{RDQUO}; Write-Output INJECTED; {LDQUO}",
            version="1.0.0",
        )
        output_path = tmp_path / "detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")
        assert f"Acme`{RDQUO}; Write-Output INJECTED; `{LDQUO}" in content
        assert f"Acme{RDQUO};" not in content
