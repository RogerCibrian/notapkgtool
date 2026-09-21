"""
Tests for napt.versioning module.

Tests MSI metadata extraction including:
- MSI architecture detection from Template
- Quoting of the MSI path in the extraction script
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from napt.exceptions import ConfigError
from napt.powershell import ps_single_quote
from napt.versioning.msi import _architecture_from_template, extract_msi_metadata

# Typographic single quote, which PowerShell accepts as a string delimiter.
# Written as an escape because it is nearly indistinguishable from ' on screen.
RSQUO = "\u2019"  # right single quotation mark


class TestArchitectureFromTemplate:
    """Tests for MSI Template architecture parsing."""

    def test_x64_template(self):
        """Tests x64 template parsing."""
        assert _architecture_from_template("x64;1033") == "x64"
        assert _architecture_from_template("X64;1033") == "x64"  # Case insensitive

    def test_intel_template_maps_to_x86(self):
        """Tests that Intel template maps to x86."""
        assert _architecture_from_template("Intel;1033") == "x86"
        assert _architecture_from_template("INTEL;1033") == "x86"

    def test_arm64_template(self):
        """Tests ARM64 template parsing."""
        assert _architecture_from_template("Arm64;1033") == "arm64"
        assert _architecture_from_template("ARM64;1033,2046") == "arm64"

    def test_amd64_alias_maps_to_x64(self):
        """Tests that the AMD64 unofficial alias maps to x64."""
        assert _architecture_from_template("AMD64;1033") == "x64"
        assert _architecture_from_template("amd64;1033") == "x64"

    def test_empty_platform_defaults_to_x86(self):
        """Tests that an empty platform defaults to x86 per MS docs."""
        assert _architecture_from_template(";1033") == "x86"
        assert _architecture_from_template("  ;1033") == "x86"

    def test_discards_language_codes(self):
        """Tests that language codes after the semicolon are discarded."""
        assert _architecture_from_template("x64;1033") == "x64"
        assert _architecture_from_template("x64;1033,2046") == "x64"
        assert _architecture_from_template("x64;1041,1033") == "x64"

    def test_intel64_raises_config_error(self):
        """Tests that Intel64 (Itanium) raises ConfigError."""
        with pytest.raises(ConfigError, match="Itanium"):
            _architecture_from_template("Intel64;1033")

    def test_arm32_raises_config_error(self):
        """Tests that Arm (Windows RT 32-bit) raises ConfigError."""
        with pytest.raises(ConfigError, match="Windows RT"):
            _architecture_from_template("Arm;1033")

    def test_unknown_platform_raises_config_error(self):
        """Tests that an unknown platform raises ConfigError."""
        with pytest.raises(ConfigError, match="Unknown"):
            _architecture_from_template("mips;1033")

    def test_template_without_semicolon(self):
        """Tests that a template without a semicolon is handled."""
        assert _architecture_from_template("x64") == "x64"
        assert _architecture_from_template("Intel") == "x86"

    def test_whitespace_handling(self):
        """Tests that whitespace in the template is handled."""
        assert _architecture_from_template("  x64  ;1033") == "x64"
        assert _architecture_from_template("x64 ; 1033") == "x64"


class TestExtractMsiMetadataScript:
    """Tests for the PowerShell script built to read MSI metadata."""

    def test_msi_path_is_quoted_in_script(self, tmp_path, monkeypatch):
        """Tests that a hostile MSI path cannot close its PowerShell string."""
        monkeypatch.setattr("napt.versioning.msi.sys.platform", "win32")
        msi_path = tmp_path / f"app{RSQUO}; Remove-Item X; {RSQUO}.msi"
        msi_path.write_bytes(b"")
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Contoso App\n1.2.3\nx64;1033\n", stderr=""
        )

        with mock.patch(
            "napt.versioning.msi.subprocess.run", return_value=completed
        ) as run:
            metadata = extract_msi_metadata(msi_path)

        script = run.call_args.args[0][-1]
        assert f"OpenDatabase({ps_single_quote(str(msi_path))}, 0)" in script
        assert f"app{RSQUO}{RSQUO}; Remove-Item X; {RSQUO}{RSQUO}.msi'" in script
        assert metadata.product_version == "1.2.3"
