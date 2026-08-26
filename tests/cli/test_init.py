"""Tests for napt.cli.init."""

from __future__ import annotations

from napt.cli.init import cmd_init
from tests.cli.conftest import _args


class TestCmdInit:
    """Tests for cmd_init handler."""

    def test_fresh_directory_creates_full_structure(self, tmp_path, capsys):
        """Tests that init creates recipes/, defaults/vendors/, defaults/org.yaml."""
        code = cmd_init(_args(directory=str(tmp_path), force=False))
        assert code == 0
        assert (tmp_path / "recipes").is_dir()
        assert (tmp_path / "defaults" / "vendors").is_dir()
        assert (tmp_path / "defaults" / "org.yaml").exists()
        out = capsys.readouterr().out
        assert "[SUCCESS]" in out
        assert "[OK]" in out

    def test_existing_files_skipped_without_force(self, tmp_path, capsys):
        """Tests that existing files are preserved when --force is not used."""
        (tmp_path / "recipes").mkdir()
        org_yaml = tmp_path / "defaults" / "org.yaml"
        org_yaml.parent.mkdir(parents=True)
        org_yaml.write_text("original content")

        cmd_init(_args(directory=str(tmp_path), force=False))

        assert org_yaml.read_text() == "original content"
        out = capsys.readouterr().out
        assert "[SKIP]" in out
        assert "Existing files were preserved" in out

    def test_force_backs_up_and_recreates_org_yaml(self, tmp_path, capsys):
        """Tests that --force backs up existing org.yaml and creates a fresh one."""
        org_yaml = tmp_path / "defaults" / "org.yaml"
        org_yaml.parent.mkdir(parents=True)
        org_yaml.write_text("original content")

        cmd_init(_args(directory=str(tmp_path), force=True))

        backup = tmp_path / "defaults" / "org.yaml.backup"
        assert backup.exists()
        assert backup.read_text() == "original content"
        assert org_yaml.exists()
        assert org_yaml.read_text() != "original content"
        out = capsys.readouterr().out
        assert "Backed Up" in out

    def test_org_yaml_contains_template_content(self, tmp_path):
        """Tests that the created org.yaml matches ORG_YAML_TEMPLATE exactly."""
        from napt.config.defaults import ORG_YAML_TEMPLATE

        cmd_init(_args(directory=str(tmp_path), force=False))
        content = (tmp_path / "defaults" / "org.yaml").read_text(encoding="utf-8")
        assert content == ORG_YAML_TEMPLATE
