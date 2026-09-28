"""Tests for napt.files."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from napt.files import write_text_atomic


class TestWriteTextAtomic:
    """Tests for the atomic text writer."""

    def test_writes_content_and_leaves_no_temp_file(self, tmp_path):
        """Tests that the target holds the text and the folder holds only it."""
        target = tmp_path / "state.json"

        write_text_atomic(target, '{"a": 1}\n')

        assert target.read_text(encoding="utf-8") == '{"a": 1}\n'
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]

    def test_replaces_existing_content(self, tmp_path):
        """Tests that an existing target is replaced in full."""
        target = tmp_path / "state.json"
        target.write_text("old content that is longer", encoding="utf-8")

        write_text_atomic(target, "new")

        assert target.read_text(encoding="utf-8") == "new"

    def test_failed_write_leaves_the_old_file_intact(self, tmp_path):
        """Tests that a failure before the rename keeps the previous file
        unchanged and leaves no temporary file behind."""
        target = tmp_path / "state.json"
        target.write_text("old", encoding="utf-8")

        with (
            patch("napt.files.os.replace", side_effect=OSError(28, "No space")),
            pytest.raises(OSError, match="No space"),
        ):
            write_text_atomic(target, "new")

        assert target.read_text(encoding="utf-8") == "old"
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]

    def test_creates_parent_directories(self, tmp_path):
        """Tests that missing parent folders are created."""
        target = tmp_path / "state" / "deployment" / "app.json"

        write_text_atomic(target, "x")

        assert target.read_text(encoding="utf-8") == "x"
