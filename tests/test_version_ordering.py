"""Tests for napt.versioning.ordering and its parity with the device-side code.

One table of cases drives both implementations: the Python mirror, and the
real ``Compare-VersionString`` from the script template run by whichever
PowerShell interpreters are installed.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from napt.powershell import PS_SCRIPT_ENCODING, ps_single_quote
from napt.versioning.ordering import compare_versions, is_downgrade, version_parts

_SHARED_FUNCTIONS = (
    Path(__file__).parent.parent
    / "napt"
    / "build"
    / "templates"
    / "_shared_functions.ps1"
)

# (left, right, expected) where expected is the sign of left compared to right.
ORDERING_CASES = [
    ("1.2.0", "1.1.9", 1),
    ("1.1.9", "1.2.0", -1),
    ("1.2.0", "1.2.0", 0),
    ("1.10.0", "1.9.0", 1),
    ("141.0.7390.123", "140.0.7339.128", 1),
    ("141.0.7390.122", "141.0.7390.123", -1),
    # Missing trailing segments count as 0.
    ("2.0", "2.0.0.0", 0),
    ("2.0.1", "2.0", 1),
    # A hyphen separates segments like a dot.
    ("1.2-3", "1.2.3", 0),
    # Only a segment's leading digits count.
    ("1.2.3beta", "1.2.3", 0),
    ("7.4.1x64", "7.4.0", 1),
    # A segment with no leading digits counts as 0, so prerelease tags are
    # not ranked and a "v" prefix turns the first number into 0.
    ("1.0-rc1", "1.0", 0),
    ("1.0.0-beta", "1.0.0-alpha", 0),
    ("v2.0", "v1.9", -1),
    ("v2.5", "v1.5", 0),
    ("v2.0", "1.9", -1),
    ("2024.1", "5.0", 1),
    ("01.02", "1.2", 0),
]


@pytest.mark.parametrize(("left", "right", "expected"), ORDERING_CASES)
def test_compare_versions(left: str, right: str, expected: int):
    """Tests that the Python mirror orders each case as listed."""
    assert compare_versions(left, right) == expected
    assert compare_versions(right, left) == -expected


def test_version_parts_keeps_leading_digits_only():
    """Tests that segments reduce to their leading digits, or 0."""
    assert version_parts("v2.10-rc1.7x") == [0, 10, 0, 7]


def test_is_downgrade():
    """Tests that only a lower version counts as a downgrade."""
    assert is_downgrade("1.9.0", "2.0.0")
    assert not is_downgrade("2.0.0", "2.0.0")
    assert not is_downgrade("2.0.1", "2.0.0")
    assert not is_downgrade("1.0.0", None)


def _powershell_executables() -> list[str]:
    """Returns every PowerShell interpreter on PATH (5.1 and 7 differ)."""
    return [exe for exe in ("powershell", "pwsh") if shutil.which(exe)]


@pytest.mark.parametrize("executable", _powershell_executables())
def test_device_side_function_agrees_with_table(executable: str, tmp_path: Path):
    """Tests that the real Compare-VersionString orders each case as listed."""
    lines = [f". {ps_single_quote(str(_SHARED_FUNCTIONS))}"]
    lines += [
        f"Compare-VersionString -LeftVersion {ps_single_quote(left)}"
        f" -RightVersion {ps_single_quote(right)}"
        for left, right, _ in ORDERING_CASES
    ]
    script = tmp_path / "ordering.ps1"
    script.write_text("\n".join(lines), encoding=PS_SCRIPT_ENCODING)

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
    actual = [int(line) for line in result.stdout.split()]
    assert actual == [expected for _, _, expected in ORDERING_CASES]
