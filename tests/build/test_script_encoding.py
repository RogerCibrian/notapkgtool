"""Tests for the encoding of generated PowerShell scripts.

Windows PowerShell 5.1 reads a script without a byte order mark as the ANSI
code page. These tests cover that every generated script carries a BOM, and
that a real interpreter therefore reads non-ASCII app names as written.
"""

from __future__ import annotations

import codecs
from pathlib import Path
import shutil
import subprocess

import pytest

from napt.build.msix_scripts import (
    MSIXDetectionConfig,
    MSIXRequirementsConfig,
    generate_msix_detection_script,
    generate_msix_requirements_script,
)
from napt.build.registry_scripts import (
    DetectionConfig,
    RequirementsConfig,
    generate_detection_script,
    generate_requirements_script,
)

# U+00D3 is bytes C3 93 in UTF-8. Read as cp1252, byte 93 is a left double
# quotation mark, which PowerShell accepts as a string delimiter. Without a
# BOM this ordinary letter closes the double-quoted string it sits in.
O_ACUTE = "\u00d3"  # latin capital letter o with acute
HOSTILE_NAME = f"Caf{O_ACUTE}; Write-Output INJECTED; {O_ACUTE}x"

GENERATORS = [
    pytest.param(
        generate_detection_script,
        DetectionConfig(app_name=HOSTILE_NAME, version="1.0.0"),
        id="registry-detection",
    ),
    pytest.param(
        generate_requirements_script,
        RequirementsConfig(app_name=HOSTILE_NAME, version="1.0.0"),
        id="registry-requirements",
    ),
    pytest.param(
        generate_msix_detection_script,
        MSIXDetectionConfig(
            identity_name="Contoso.App", app_name=HOSTILE_NAME, version="1.0.0.0"
        ),
        id="msix-detection",
    ),
    pytest.param(
        generate_msix_requirements_script,
        MSIXRequirementsConfig(
            identity_name="Contoso.App", app_name=HOSTILE_NAME, version="1.0.0.0"
        ),
        id="msix-requirements",
    ),
]

# Parses a script without running it and reports, on one line, how many syntax
# errors it has and whether the injected text became a real command.
PARSE_SCRIPT = """
param($File)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $File, [ref]$tokens, [ref]$errors)
$injected = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -eq 'Write-Output'
}, $true) | Where-Object { $_.Extent.Text -match 'INJECTED' })
"errors=$($errors.Count) injected=$($injected.Count)"
"""


def _powershell_executables() -> list[str]:
    """Returns every PowerShell interpreter on PATH (5.1 and 7 differ)."""
    return [exe for exe in ("powershell", "pwsh") if shutil.which(exe)]


@pytest.mark.parametrize(("generate", "config"), GENERATORS)
def test_generated_script_starts_with_bom(generate, config, tmp_path: Path):
    """Tests that every generated script starts with a UTF-8 byte order mark."""
    output_path = tmp_path / "script.ps1"

    generate(config, output_path)

    assert output_path.read_bytes().startswith(codecs.BOM_UTF8)


@pytest.mark.parametrize("executable", _powershell_executables())
@pytest.mark.parametrize(("generate", "config"), GENERATORS)
def test_accented_name_cannot_close_its_string(
    generate, config, executable: str, tmp_path: Path
):
    """Tests that a real interpreter parses an accented app name as text."""
    output_path = tmp_path / "script.ps1"
    generate(config, output_path)
    parser = tmp_path / "parse.ps1"
    parser.write_text(PARSE_SCRIPT, encoding="utf-8-sig")

    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(parser),
            "-File",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "errors=0 injected=0"
