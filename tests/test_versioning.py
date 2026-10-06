"""
Tests for napt.versioning module.

Tests MSI metadata extraction including:
- MSI architecture detection from Template
- Quoting of the MSI path in the extraction script
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest import mock

import pytest

from napt.exceptions import PackagingError
from napt.powershell import ps_single_quote
from napt.versioning.msi import _architecture_from_template, extract_msi_metadata

# Typographic single quote, which PowerShell accepts as a string delimiter.
# Written as an escape because it is nearly indistinguishable from ' on screen.
RSQUO = "\u2019"  # right single quotation mark


class TestMissingBackend:
    """Tests for hosts that cannot read an MSI at all."""

    def test_powershell_missing_is_a_packaging_error(self, tmp_path, monkeypatch):
        """Tests that a Windows host without powershell on PATH is reported,
        not a FileNotFoundError traceback."""
        monkeypatch.setattr("napt.versioning.msi.sys.platform", "win32")
        msi_path = tmp_path / "app.msi"
        msi_path.write_bytes(b"")

        with mock.patch(
            "napt.powershell.subprocess.run",
            side_effect=FileNotFoundError(2, "No such file", "powershell"),
        ):
            with pytest.raises(PackagingError, match="PowerShell"):
                extract_msi_metadata(msi_path)

    def test_no_backend_is_a_packaging_error(self, tmp_path, monkeypatch):
        """Tests that a non-Windows host without msitools is reported as a
        build error naming the package to install."""
        monkeypatch.setattr("napt.versioning.msi.sys.platform", "linux")
        monkeypatch.setattr("napt.versioning.msi.shutil.which", lambda name: None)
        msi_path = tmp_path / "app.msi"
        msi_path.write_bytes(b"")

        with pytest.raises(PackagingError, match="msitools"):
            extract_msi_metadata(msi_path)


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

    def test_intel64_is_a_packaging_error(self):
        """Tests that Intel64 (Itanium) is refused as an installer problem."""
        with pytest.raises(PackagingError, match="Itanium"):
            _architecture_from_template("Intel64;1033")

    def test_arm32_is_a_packaging_error(self):
        """Tests that Arm (Windows RT 32-bit) is refused as an installer problem."""
        with pytest.raises(PackagingError, match="Windows RT"):
            _architecture_from_template("Arm;1033")

    def test_unknown_platform_is_a_packaging_error(self):
        """Tests that an unknown platform is refused as an installer problem."""
        with pytest.raises(PackagingError, match="Unknown"):
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

    @staticmethod
    def _fake_powershell(lines, encoding="utf-8"):
        """Stands in for powershell.exe: writes the values to the output file."""

        def run(args, **kwargs):
            out = Path(kwargs["env"]["NAPT_MSI_OUT"])
            out.write_text("\n".join(lines) + "\n", encoding=encoding)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        return run

    def test_msi_path_is_quoted_in_script(self, tmp_path, monkeypatch):
        """Tests that a hostile MSI path cannot close its PowerShell string."""
        monkeypatch.setattr("napt.versioning.msi.sys.platform", "win32")
        msi_path = tmp_path / f"app{RSQUO}; Remove-Item X; {RSQUO}.msi"
        msi_path.write_bytes(b"")

        with mock.patch(
            "napt.powershell.subprocess.run",
            side_effect=self._fake_powershell(["Contoso App", "1.2.3", "x64;1033"]),
        ) as run:
            metadata = extract_msi_metadata(msi_path)

        script = run.call_args.args[0][-1]
        assert f"OpenDatabase({ps_single_quote(str(msi_path))}, 0)" in script
        assert f"app{RSQUO}{RSQUO}; Remove-Item X; {RSQUO}{RSQUO}.msi'" in script
        assert metadata.product_version == "1.2.3"

    @pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
    def test_non_ascii_product_name_round_trips(self, tmp_path, monkeypatch, encoding):
        """Tests that the values travel through a UTF-8 file, not the console."""
        monkeypatch.setattr("napt.versioning.msi.sys.platform", "win32")
        msi_path = tmp_path / "app.msi"
        msi_path.write_bytes(b"")
        name = "Café Office™ üÉ"

        with mock.patch(
            "napt.powershell.subprocess.run",
            side_effect=self._fake_powershell([name, "2.0.0", "x64;1033"], encoding),
        ) as run:
            metadata = extract_msi_metadata(msi_path)

        script = run.call_args.args[0][-1]
        assert "[Console]::OutputEncoding" not in script
        assert "$env:NAPT_MSI_OUT" in script
        assert metadata.product_name == name
        assert not Path(run.call_args.kwargs["env"]["NAPT_MSI_OUT"]).exists()

    def test_output_file_is_removed_when_powershell_fails(self, tmp_path, monkeypatch):
        """Tests that a failed query leaves no temp file behind."""
        monkeypatch.setattr("napt.versioning.msi.sys.platform", "win32")
        msi_path = tmp_path / "app.msi"
        msi_path.write_bytes(b"")
        seen = {}

        def failing_run(args, **kwargs):
            seen["out"] = Path(kwargs["env"]["NAPT_MSI_OUT"])
            raise subprocess.CalledProcessError(1, args, stderr="boom")

        with mock.patch("napt.powershell.subprocess.run", side_effect=failing_run):
            with pytest.raises(PackagingError, match="PowerShell MSI query"):
                extract_msi_metadata(msi_path)

        assert not seen["out"].exists()

    def test_empty_template_platform_is_x86_on_windows(self, tmp_path, monkeypatch):
        """Tests that the PowerShell backend hands an empty Template to the
        shared platform mapping instead of failing, so both backends agree."""
        monkeypatch.setattr("napt.versioning.msi.sys.platform", "win32")
        msi_path = tmp_path / "app.msi"
        msi_path.write_bytes(b"")

        with mock.patch(
            "napt.powershell.subprocess.run",
            side_effect=self._fake_powershell(["App", "1.0.0", ";1033"]),
        ) as run:
            metadata = extract_msi_metadata(msi_path)

        assert metadata.architecture == "x86"
        assert "Template (Summary Information Property 7) not found" not in (
            run.call_args.args[0][-1]
        )


class TestExtractMsiMetadataMsiinfo:
    """Tests for the msitools backend (mocked)."""

    def test_missing_template_line_is_x86(self, tmp_path, monkeypatch):
        """Tests that an MSI whose summary lacks a Template is read as x86,
        the same answer the PowerShell backend gives."""
        monkeypatch.setattr("napt.versioning.msi.sys.platform", "linux")
        monkeypatch.setattr(
            "napt.versioning.msi.shutil.which", lambda name: "/usr/bin/msiinfo"
        )
        msi_path = tmp_path / "app.msi"
        msi_path.write_bytes(b"")

        def run(args, **kwargs):
            stdout = (
                "ProductName\tApp\nProductVersion\t1.0.0\n"
                if args[1] == "export"
                else "Title: Installation Database\n"
            )
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

        with mock.patch("napt.versioning.msi.subprocess.run", side_effect=run):
            metadata = extract_msi_metadata(msi_path)

        assert metadata.architecture == "x86"
        assert metadata.product_version == "1.0.0"
