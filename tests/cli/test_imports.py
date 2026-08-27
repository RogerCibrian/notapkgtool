"""Tests for the CLI package's import graph."""

from __future__ import annotations

import subprocess
import sys


def test_cli_imports_in_fresh_interpreter():
    """Tests that importing napt.cli succeeds in a fresh interpreter.

    Runs in a subprocess so nothing imported earlier in the test session
    (conftest imports included) can mask a circular import. In-process
    tests once missed a cycle that broke the console script because a
    conftest import had already initialized part of the cycle.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import napt.cli"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
