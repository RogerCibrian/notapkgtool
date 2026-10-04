"""Tests for the CLI package's import graph."""

from __future__ import annotations

import subprocess
import sys


def _run(code: str) -> subprocess.CompletedProcess[str]:
    """Runs Python code in a fresh interpreter.

    A subprocess, so nothing imported earlier in the test session (conftest
    imports included) can mask a circular import or pre-load a module.
    In-process tests once missed a cycle that broke the console script
    because a conftest import had already initialized part of the cycle.
    """
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_entry_point_imports_in_fresh_interpreter():
    """Tests that the console script's module and every command import."""
    result = _run("import napt.cli.main")
    assert result.returncode == 0, result.stderr


def test_building_the_parser_leaves_the_heavy_libraries_unloaded():
    """Tests that commands that never talk to a tenant do not pay for the
    Azure and HTTP libraries at startup; each command imports its subsystem
    when it runs."""
    result = _run(
        "import sys\n"
        "from napt.cli.main import build_parser\n"
        "build_parser()\n"
        "heavy = {'azure', 'msal', 'requests', 'yaml'}\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] in heavy)\n"
        "print(loaded)\n"
        "sys.exit(1 if loaded else 0)\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
