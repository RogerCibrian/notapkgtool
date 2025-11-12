"""
Tests for notapkgtool.state module.

Tests state management including:
- Loading and saving state files
- Cache operations
- State file creation and error handling
"""

from __future__ import annotations

import json

import pytest

from notapkgtool.state import StateTracker, load_state, save_state
from notapkgtool.state.tracker import create_default_state


class TestStateFileOperations:
    """Tests for loading and saving state files."""

    def test_create_default_state(self):
        """Test creating default empty state structure."""
        state = create_default_state()

        assert "metadata" in state
        assert "apps" in state
        assert state["metadata"]["schema_version"] == "2"
        assert isinstance(state["apps"], dict)
        assert len(state["apps"]) == 0

    def test_save_and_load_state(self, tmp_path):
        """Test round-trip save and load."""
        state_file = tmp_path / "test_state.json"
        state = {
            "metadata": {"napt_version": "0.1.0"},
            "apps": {
                "test-app": {
                    "url": "https://vendor.com/app.msi",
                    "etag": 'W/"abc123"',
                    "sha256": "def456",
                    "known_version": "1.2.3",
                }
            },
        }

        # Save
        save_state(state, state_file)
        assert state_file.exists()

        # Load
        loaded = load_state(state_file)
        assert loaded["apps"]["test-app"]["known_version"] == "1.2.3"
        assert loaded["apps"]["test-app"]["etag"] == 'W/"abc123"'
        assert loaded["apps"]["test-app"]["url"] == "https://vendor.com/app.msi"

    def test_load_missing_file_raises(self, tmp_path):
        """Test that loading nonexistent file raises FileNotFoundError."""
        state_file = tmp_path / "nonexistent.json"

        with pytest.raises(FileNotFoundError):
            load_state(state_file)

    def test_load_invalid_json_raises(self, tmp_path):
        """Test that loading invalid JSON raises JSONDecodeError."""
        state_file = tmp_path / "invalid.json"
        state_file.write_text("This is not JSON", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            load_state(state_file)

    def test_save_creates_parent_directory(self, tmp_path):
        """Test that save creates parent directories if needed."""
        state_file = tmp_path / "nested" / "dir" / "state.json"
        state = create_default_state()

        save_state(state, state_file)

        assert state_file.exists()
        assert state_file.parent.exists()

    def test_save_pretty_prints_json(self, tmp_path):
        """Test that saved JSON is pretty-printed."""
        state_file = tmp_path / "state.json"
        state = {"metadata": {}, "apps": {"test": {"version": "1.0"}}}

        save_state(state, state_file)

        content = state_file.read_text(encoding="utf-8")
        # Should have indentation (pretty-printed)
        assert "  " in content
        # Should have trailing newline
        assert content.endswith("\n")


class TestStateTracker:
    """Tests for StateTracker class."""

    def test_init(self, tmp_path):
        """Test StateTracker initialization."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)

        assert tracker.state_file == state_file
        assert isinstance(tracker.state, dict)

    def test_load_creates_default_if_missing(self, tmp_path):
        """Test that load creates default state if file doesn't exist."""
        state_file = tmp_path / "new_state.json"
        tracker = StateTracker(state_file)

        state = tracker.load()

        assert state_file.exists()
        assert "metadata" in state
        assert "apps" in state

    def test_load_existing_file(self, tmp_path):
        """Test loading existing state file."""
        state_file = tmp_path / "state.json"
        initial_state = {
            "metadata": {"napt_version": "0.1.0"},
            "apps": {
                "test-app": {
                    "url": "https://vendor.com/app.msi",
                    "sha256": "abc123",
                    "known_version": "1.2.3",
                }
            },
        }
        save_state(initial_state, state_file)

        tracker = StateTracker(state_file)
        state = tracker.load()

        assert state["apps"]["test-app"]["known_version"] == "1.2.3"

    def test_load_corrupted_file_creates_backup(self, tmp_path):
        """Test that corrupted file is backed up and replaced."""
        state_file = tmp_path / "state.json"
        state_file.write_text("corrupted JSON{{{", encoding="utf-8")

        tracker = StateTracker(state_file)

        with pytest.raises(RuntimeError, match="Corrupted state file"):
            tracker.load()

        # Should create backup
        backup_file = tmp_path / "state.json.backup"
        assert backup_file.exists()
        assert backup_file.read_text(encoding="utf-8") == "corrupted JSON{{{"

        # Should create new clean state file
        assert state_file.exists()
        new_state = load_state(state_file)
        assert "apps" in new_state

    def test_save_updates_timestamp(self, tmp_path):
        """Test that save updates last_updated timestamp."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.state = create_default_state()

        tracker.save()

        loaded = load_state(state_file)
        assert "last_updated" in loaded["metadata"]

    def test_get_cache_existing(self, tmp_path):
        """Test getting cache for existing recipe."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.state = {
            "metadata": {},
            "apps": {
                "test-app": {
                    "url": "https://vendor.com/app.msi",
                    "etag": 'W/"abc123"',
                    "sha256": "def456",
                    "known_version": "1.2.3",
                }
            },
        }

        cache = tracker.get_cache("test-app")

        assert cache is not None
        assert cache["known_version"] == "1.2.3"
        assert cache["etag"] == 'W/"abc123"'
        assert cache["url"] == "https://vendor.com/app.msi"

    def test_get_cache_missing(self, tmp_path):
        """Test getting cache for non-existent recipe returns None."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.state = {"metadata": {}, "apps": {}}

        cache = tracker.get_cache("nonexistent-app")

        assert cache is None

    def test_update_cache(self, tmp_path):
        """Test updating cache for a recipe."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.state = create_default_state()

        tracker.update_cache(
            recipe_id="test-app",
            url="https://vendor.com/file.msi",
            sha256="abc123",
            etag='W/"xyz789"',
            last_modified="Mon, 28 Oct 2024 10:00:00 GMT",
            known_version="2.0.0",
            strategy="url_download",
        )

        cache = tracker.get_cache("test-app")
        assert cache["known_version"] == "2.0.0"
        assert cache["url"] == "https://vendor.com/file.msi"
        assert cache["etag"] == 'W/"xyz789"'
        assert cache["last_modified"] == "Mon, 28 Oct 2024 10:00:00 GMT"
        assert cache["sha256"] == "abc123"
        assert cache["strategy"] == "url_download"

    def test_has_version_changed_true(self, tmp_path):
        """Test version change detection when version differs."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.state = {
            "metadata": {},
            "apps": {"test-app": {"known_version": "1.0.0"}},
        }

        assert tracker.has_version_changed("test-app", "2.0.0") is True

    def test_has_version_changed_false(self, tmp_path):
        """Test version change detection when version same."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.state = {
            "metadata": {},
            "apps": {"test-app": {"known_version": "1.0.0"}},
        }

        assert tracker.has_version_changed("test-app", "1.0.0") is False

    def test_has_version_changed_no_cache(self, tmp_path):
        """Test version change detection with no cached version."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.state = {"metadata": {}, "apps": {}}

        # No cache means version changed
        assert tracker.has_version_changed("test-app", "1.0.0") is True
