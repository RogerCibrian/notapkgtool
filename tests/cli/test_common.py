"""Tests for the scaffolding every CLI command shares."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from napt.cli.common import (
    add_output_flags,
    add_state_dir,
    print_results,
    run_handler,
    setup_logging,
)
from napt.exceptions import AuthError, ConfigError, StateError
from napt.logging import get_global_logger
from tests.cli.conftest import _args


def _raising(exc: BaseException):
    """Builds a handler that raises the given exception."""

    def handler(args: argparse.Namespace) -> int:
        raise exc

    return handler


class TestRunHandler:
    """Tests for the one error wrapper around every command handler."""

    def test_returns_the_handlers_exit_code(self):
        """Tests that a handler's own exit code passes through."""
        assert run_handler(lambda args: 3, _args()) == 3

    def test_napt_error_prints_message_and_returns_one(self, capsys):
        """Tests that a NAPT error is one line on stdout and exit 1."""
        code = run_handler(_raising(ConfigError("bad recipe")), _args())

        assert code == 1
        captured = capsys.readouterr()
        assert "Error: bad recipe" in captured.out
        assert "Traceback" not in captured.err

    def test_auth_error_is_labelled(self, capsys):
        """Tests that the label comes from the error type."""
        code = run_handler(_raising(AuthError("expired")), _args())

        assert code == 1
        assert "Authentication error: expired" in capsys.readouterr().out

    def test_every_napt_error_subclass_is_reported(self, capsys):
        """Tests that no NAPT error escapes as a traceback."""
        code = run_handler(_raising(StateError("corrupt")), _args())

        assert code == 1
        assert "Error: corrupt" in capsys.readouterr().out

    @pytest.mark.parametrize("flag", ["verbose", "debug"])
    def test_verbose_and_debug_add_the_traceback(self, capsys, flag):
        """Tests that -v and -d show where the error came from."""
        run_handler(_raising(ConfigError("bad")), _args(**{flag: True}))

        captured = capsys.readouterr()
        assert "Error: bad" in captured.out
        assert "Traceback" in captured.err

    def test_interrupt_exits_130_without_traceback(self, capsys):
        """Tests that Ctrl-C ends cleanly with the shell's interrupt code."""
        code = run_handler(_raising(KeyboardInterrupt()), _args(verbose=True))

        assert code == 130
        captured = capsys.readouterr()
        assert "Interrupted" in captured.out
        assert "Traceback" not in captured.err

    def test_os_error_is_reported(self, capsys):
        """Tests that a file system failure is reported, not dumped."""
        code = run_handler(_raising(PermissionError("denied")), _args())

        assert code == 1
        captured = capsys.readouterr()
        assert "Error: denied" in captured.out
        assert "Traceback" not in captured.err

    def test_other_exceptions_propagate(self):
        """Tests that a bug is not hidden behind an error line."""
        with pytest.raises(TypeError):
            run_handler(_raising(TypeError("bug")), _args())


class TestSetupLogging:
    """Tests for configuring the global logger from the parsed flags."""

    def test_sets_the_global_logger_from_the_flags(self, capsys):
        """Tests that -v makes verbose messages visible everywhere."""
        logger = setup_logging(_args(verbose=True))

        assert get_global_logger() is logger
        get_global_logger().verbose("TEST", "shown")
        get_global_logger().debug("TEST", "hidden")
        out = capsys.readouterr().out
        assert "shown" in out
        assert "hidden" not in out

    def test_debug_implies_verbose(self, capsys):
        """Tests that -d shows debug and verbose messages."""
        setup_logging(_args(debug=True))

        get_global_logger().verbose("TEST", "shown")
        get_global_logger().debug("TEST", "also shown")
        out = capsys.readouterr().out
        assert "shown" in out
        assert "also shown" in out


class TestPrintResults:
    """Tests for the one results block every command prints."""

    def test_prints_banner_title_rows_and_success_line(self, capsys):
        """Tests that the block has the shape every command used to hand-write."""
        print_results(
            "BUILD RESULTS",
            [("App Name", "7-Zip"), ("Version", "26.02")],
            "PSADT package built successfully!",
        )

        assert capsys.readouterr().out == (
            "=" * 70 + "\n"
            "BUILD RESULTS\n" + "=" * 70 + "\n"
            "App Name: 7-Zip\n"
            "Version:  26.02\n" + "=" * 70 + "\n"
            "\n"
            "[SUCCESS] PSADT package built successfully!\n"
        )

    def test_labels_pad_to_the_longest_in_the_block(self, capsys):
        """Tests that values line up in one column however long the labels are."""
        print_results(
            "UPLOAD RESULTS",
            [("App ID", "napt-chrome"), ("Intune Win32 Update ID", "guid")],
            "done",
        )

        lines = capsys.readouterr().out.splitlines()
        assert lines[3] == "App ID:                 napt-chrome"
        assert lines[4] == "Intune Win32 Update ID: guid"

    def test_rows_without_a_value_are_skipped(self, capsys):
        """Tests that an optional field with nothing to show prints no row."""
        print_results("UPLOAD RESULTS", [("A", "x"), ("B", None), ("C", 0)], "done")

        out = capsys.readouterr().out
        assert "B:" not in out
        assert "C: 0" in out

    def test_values_are_printed_with_str(self, capsys):
        """Tests that paths and other objects print the way print would show them."""
        print_results("X", [("Path", Path("builds") / "app")], "done")

        assert f"Path: {Path('builds') / 'app'}" in capsys.readouterr().out


class TestFlags:
    """Tests for the shared argument groups."""

    def test_output_flags(self):
        """Tests that -v and -d are store_true flags defaulting to off."""
        parser = argparse.ArgumentParser()
        add_output_flags(parser)

        assert parser.parse_args([]).verbose is False
        assert parser.parse_args([]).debug is False
        assert parser.parse_args(["-v"]).verbose is True
        assert parser.parse_args(["--debug"]).debug is True

    def test_state_dir_is_a_path_defaulting_to_none(self):
        """Tests that --state-dir is a Path whose absence means 'from config'."""
        parser = argparse.ArgumentParser()
        add_state_dir(parser, "where deployment state lives")

        assert parser.parse_args([]).state_dir is None
        assert parser.parse_args(["--state-dir", "x"]).state_dir == Path("x")
