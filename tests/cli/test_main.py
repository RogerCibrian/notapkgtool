"""Tests for the napt entry point: parser assembly and dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from napt.cli import (
    auth,
    build,
    discover,
    init,
    package,
    promote,
    status,
    upload,
    validate,
)
from napt.cli.main import build_parser, main
from napt.logging import get_global_logger, set_global_logger


class TestBuildParser:
    """Tests that every command's parser is registered and parses real argv."""

    @pytest.mark.parametrize(
        ("argv", "handler"),
        [
            (["validate", "r.yaml"], validate.cmd_validate),
            (["discover", "r.yaml"], discover.cmd_discover),
            (["build", "r.yaml"], build.cmd_build),
            (["package", "r.yaml"], package.cmd_package),
            (["init"], init.cmd_init),
            (["upload", "r.yaml"], upload.cmd_upload),
            (["auth", "login"], auth.cmd_auth_login),
            (["auth", "logout"], auth.cmd_auth_logout),
            (["auth", "status"], auth.cmd_auth_status),
            (["auth", "setup", "--tenant-id", "t"], auth.cmd_auth_setup),
            (["promote", "plan"], promote.cmd_promote_plan),
            (["promote", "apply"], promote.cmd_promote_apply),
            (["status"], status.cmd_status),
        ],
    )
    def test_every_command_dispatches_to_its_handler(self, argv, handler):
        """Tests that argv selects the handler and the output flags default off."""
        args = build_parser().parse_args(argv)

        assert args.func is handler
        assert args.verbose is False
        assert args.debug is False

    def test_no_command_is_a_usage_error(self):
        """Tests that bare 'napt' exits 2 like any usage error."""
        with pytest.raises(SystemExit) as info:
            build_parser().parse_args([])
        assert info.value.code == 2

    @pytest.mark.parametrize(
        "argv",
        [
            ["discover", "r.yaml"],
            ["build", "r.yaml"],
            ["package", "r.yaml"],
            ["upload", "r.yaml"],
            ["promote", "plan"],
            ["promote", "apply"],
            ["status"],
        ],
    )
    def test_state_dir_is_a_path_that_defaults_to_config(self, argv):
        """Tests that --state-dir is declared the same way on every command."""
        parser = build_parser()

        assert parser.parse_args(argv).state_dir is None
        assert parser.parse_args([*argv, "--state-dir", "s"]).state_dir == Path("s")

    def test_directory_flags_and_paths_are_paths(self):
        """Tests that every path argument parses to a Path."""
        parser = build_parser()

        assert parser.parse_args(["validate", "r.yaml"]).recipe == Path("r.yaml")
        assert parser.parse_args(["init"]).directory == Path(".")
        assert parser.parse_args(["status"]).recipes == Path("recipes")
        args = parser.parse_args(["discover", "r.yaml", "--output-dir", "d"])
        assert args.output_dir == Path("d")
        args = parser.parse_args(
            ["build", "r.yaml", "--downloads-dir", "a", "--output-dir", "b"]
        )
        assert (args.downloads_dir, args.output_dir) == (Path("a"), Path("b"))
        args = parser.parse_args(
            ["package", "r.yaml", "--builds-dir", "a", "--output-dir", "b"]
        )
        assert (args.builds_dir, args.output_dir) == (Path("a"), Path("b"))
        args = parser.parse_args(["upload", "r.yaml", "--packages-dir", "p"])
        assert args.packages_dir == Path("p")
        args = parser.parse_args(["promote", "apply", "--plan-file", "f.json"])
        assert args.plan_file == Path("f.json")

    def test_upload_help_describes_the_recorded_release(self, capsys):
        """Tests that the help no longer promises the most recent package."""
        with pytest.raises(SystemExit) as info:
            build_parser().parse_args(["upload", "--help"])

        assert info.value.code == 0
        out = capsys.readouterr().out
        assert "most recent" not in out
        assert "deployment state" in out


class TestMain:
    """Tests for the console script's dispatch."""

    @pytest.fixture(autouse=True)
    def _restore_logger(self):
        previous = get_global_logger()
        yield
        set_global_logger(previous)

    def test_exits_with_the_handlers_code(self, tmp_path, capsys):
        """Tests that a successful command exits 0 through main."""
        with pytest.raises(SystemExit) as info:
            main(["status", "--state-dir", str(tmp_path / "state")])

        assert info.value.code == 0
        assert "No deployment state found" in capsys.readouterr().out

    def test_failure_is_reported_through_the_shared_wrapper(self, tmp_path, capsys):
        """Tests that a missing recipe is an error line and exit 1, not a
        traceback, with no per-command pre-check needed."""
        with pytest.raises(SystemExit) as info:
            main(["discover", str(tmp_path / "missing.yaml")])

        assert info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: file not found" in captured.out
        assert "Traceback" not in captured.err

    def test_verbose_configures_the_global_logger(self, tmp_path, capsys):
        """Tests that -v is applied once, before the handler runs."""
        with pytest.raises(SystemExit):
            main(["status", "--state-dir", str(tmp_path / "state"), "-v"])

        get_global_logger().verbose("TEST", "shown")
        assert "shown" in capsys.readouterr().out
