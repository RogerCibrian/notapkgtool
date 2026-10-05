"""Tests for napt.logging: the console logger and the prefixes modules use."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import napt
from napt.logging import Logger, get_global_logger, get_logger, set_global_logger

# The prefixes CLAUDE.md documents: pipeline stages, then shared domains.
DOCUMENTED_PREFIXES = {
    "DISCOVERY",
    "BUILD",
    "PACKAGE",
    "UPLOAD",
    "PROMOTE",
    "INIT",
    "HTTP",
    "AUTH",
    "FILE",
    "CACHE",
    "CONFIG",
    "STATE",
    "DETECTION",
    "REQUIREMENTS",
    "PSADT",
    "MSI",
    "MSIX",
}
_LEVELS = {"info", "warning", "progress", "verbose", "debug"}


class TestLogger:
    """Tests for what each level prints."""

    def test_info_prints_prefix_and_message(self, capsys):
        """Tests that an info line is the prefix in brackets and the message."""
        Logger().info("BUILD", "Using PSADT 4.1.8")

        assert capsys.readouterr().out == "[BUILD] Using PSADT 4.1.8\n"

    def test_warning_is_tagged(self, capsys):
        """Tests that a warning is told apart from an info line."""
        Logger().warning("BUILD", "display_name will be ignored")

        assert (
            capsys.readouterr().out == "[BUILD] WARNING: display_name will be ignored\n"
        )

    def test_step_always_prints(self, capsys):
        """Tests that a step indicator prints at every verbosity."""
        Logger().step(3, 8, "Inspecting installer...")

        assert capsys.readouterr().out == "[3/8] Inspecting installer...\n"

    def test_progress_overwrites_the_line(self, capsys):
        """Tests that progress ends with a carriage return, not a newline."""
        Logger().progress("HTTP", "42%")

        assert capsys.readouterr().out == "[HTTP] 42%\r"

    def test_verbose_and_debug_are_hidden_by_default(self, capsys):
        """Tests that the default logger prints neither verbose nor debug."""
        logger = Logger()
        logger.verbose("STATE", "hidden")
        logger.debug("HTTP", "hidden too")

        assert capsys.readouterr().out == ""

    def test_verbose_shows_verbose_only(self, capsys):
        """Tests that -v shows verbose lines and still hides debug."""
        logger = Logger(verbose=True)
        logger.verbose("STATE", "shown")
        logger.debug("HTTP", "hidden")

        assert capsys.readouterr().out == "[STATE] shown\n"

    def test_debug_implies_verbose(self, capsys):
        """Tests that -d shows both verbose and debug lines."""
        logger = Logger(debug=True)
        logger.verbose("STATE", "shown")
        logger.debug("HTTP", "also shown")

        assert capsys.readouterr().out == "[STATE] shown\n[HTTP] also shown\n"

    def test_debug_enabled_lets_callers_skip_expensive_dumps(self):
        """Tests that a module can ask before building a debug-only dump."""
        assert Logger().debug_enabled is False
        assert Logger(verbose=True).debug_enabled is False
        assert Logger(debug=True).debug_enabled is True


class TestGlobalLogger:
    """Tests for the logger every module reads."""

    def test_get_logger_builds_a_logger(self):
        """Tests that get_logger returns the one logger class, configured."""
        logger = get_logger(verbose=True)

        assert isinstance(logger, Logger)

    def test_default_global_logger_is_quiet(self, capsys):
        """Tests that without the CLI's setup, verbose lines do not print."""
        get_global_logger().verbose("STATE", "hidden")

        assert capsys.readouterr().out == ""

    def test_set_global_logger_replaces_it(self):
        """Tests that the CLI's configured logger is what modules then get."""
        logger = get_logger(debug=True)

        set_global_logger(logger)

        assert get_global_logger() is logger

    def test_fixture_restores_the_global_logger(self):
        """Tests that the previous test's replacement did not leak here."""
        assert get_global_logger() is not get_logger(debug=True)
        assert not get_global_logger()._debug


def _logger_calls(tree: ast.AST):
    """Yields (lineno, prefix) for every logger.<level>("PREFIX", ...) call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _LEVELS or not node.args:
            continue
        receiver = node.func.value
        is_logger = (isinstance(receiver, ast.Name) and "logger" in receiver.id) or (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "get_global_logger"
        )
        first = node.args[0]
        if (
            is_logger
            and isinstance(first, ast.Constant)
            and isinstance(first.value, str)
        ):
            yield node.lineno, first.value


def test_every_log_prefix_is_documented():
    """Tests that no module logs under a prefix CLAUDE.md does not list."""
    package_dir = Path(napt.__file__).parent
    offenders = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, prefix in _logger_calls(tree):
            if prefix not in DOCUMENTED_PREFIXES:
                offenders.append(f"{path.relative_to(package_dir)}:{lineno} {prefix}")

    assert offenders == []


@pytest.mark.parametrize("prefix", sorted(DOCUMENTED_PREFIXES))
def test_documented_prefixes_are_plain_words(prefix):
    """Tests that the documented set itself holds upper-case ASCII words."""
    assert prefix.isupper() and prefix.isascii() and prefix.isalpha()
