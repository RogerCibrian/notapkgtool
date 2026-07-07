"""
Tests for napt.state module.

Tests state persistence including:
- Loading and saving discovery cache files
- Cache operations
- Cache file creation and error handling
- Deployment state loading, saving, and determinism
- Pending release recording (newest wins)
"""

from __future__ import annotations

import json

import pytest

from napt.exceptions import PackagingError
from napt.state import (
    DiscoveryCache,
    create_default_deployment_state,
    deployment_state_path,
    load_cache,
    load_deployment_state,
    record_deployed,
    record_pending,
    save_cache,
    save_deployment_state,
)
from napt.state.cache import create_default_cache


class TestCacheFileOperations:
    """Tests for loading and saving discovery cache files."""

    def test_create_default_cache(self):
        """Tests that the default cache structure is empty with metadata."""
        data = create_default_cache()

        assert "metadata" in data
        assert "apps" in data
        assert data["metadata"]["schema_version"] == "2"
        assert isinstance(data["apps"], dict)
        assert len(data["apps"]) == 0

    def test_save_and_load_cache(self, tmp_path):
        """Tests round-trip save and load."""
        cache_file = tmp_path / "discovery.json"
        data = {
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
        save_cache(data, cache_file)
        assert cache_file.exists()

        # Load
        loaded = load_cache(cache_file)
        assert loaded["apps"]["test-app"]["known_version"] == "1.2.3"
        assert loaded["apps"]["test-app"]["etag"] == 'W/"abc123"'
        assert loaded["apps"]["test-app"]["url"] == "https://vendor.com/app.msi"

    def test_load_missing_file_raises(self, tmp_path):
        """Tests that loading nonexistent file raises FileNotFoundError."""
        cache_file = tmp_path / "nonexistent.json"

        with pytest.raises(FileNotFoundError):
            load_cache(cache_file)

    def test_load_invalid_json_raises(self, tmp_path):
        """Tests that loading invalid JSON raises JSONDecodeError."""
        cache_file = tmp_path / "invalid.json"
        cache_file.write_text("This is not JSON", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            load_cache(cache_file)

    def test_save_creates_parent_directory(self, tmp_path):
        """Tests that save creates parent directories if needed."""
        cache_file = tmp_path / "nested" / "dir" / "discovery.json"
        data = create_default_cache()

        save_cache(data, cache_file)

        assert cache_file.exists()
        assert cache_file.parent.exists()

    def test_save_pretty_prints_json(self, tmp_path):
        """Tests that saved JSON is pretty-printed."""
        cache_file = tmp_path / "discovery.json"
        data = {"metadata": {}, "apps": {"test": {"version": "1.0"}}}

        save_cache(data, cache_file)

        content = cache_file.read_text(encoding="utf-8")
        # Should have indentation (pretty-printed)
        assert "  " in content
        # Should have trailing newline
        assert content.endswith("\n")


class TestDiscoveryCache:
    """Tests for DiscoveryCache class."""

    def test_init(self, tmp_path):
        """Tests DiscoveryCache initialization."""
        cache_file = tmp_path / "discovery.json"
        cache = DiscoveryCache(cache_file)

        assert cache.cache_file == cache_file
        assert isinstance(cache.data, dict)

    def test_load_creates_default_if_missing(self, tmp_path):
        """Tests that load creates default cache if file doesn't exist."""
        cache_file = tmp_path / "new_discovery.json"
        cache = DiscoveryCache(cache_file)

        data = cache.load()

        assert cache_file.exists()
        assert "metadata" in data
        assert "apps" in data

    def test_load_existing_file(self, tmp_path):
        """Tests loading existing cache file."""
        cache_file = tmp_path / "discovery.json"
        initial_data = {
            "metadata": {"napt_version": "0.1.0"},
            "apps": {
                "test-app": {
                    "url": "https://vendor.com/app.msi",
                    "sha256": "abc123",
                    "known_version": "1.2.3",
                }
            },
        }
        save_cache(initial_data, cache_file)

        cache = DiscoveryCache(cache_file)
        data = cache.load()

        assert data["apps"]["test-app"]["known_version"] == "1.2.3"

    def test_load_corrupted_file_creates_backup(self, tmp_path):
        """Tests that corrupted file is backed up and replaced."""
        cache_file = tmp_path / "discovery.json"
        cache_file.write_text("corrupted JSON{{{", encoding="utf-8")

        cache = DiscoveryCache(cache_file)

        with pytest.raises(PackagingError, match="Corrupted cache file"):
            cache.load()

        # Should create backup
        backup_file = tmp_path / "discovery.json.backup"
        assert backup_file.exists()
        assert backup_file.read_text(encoding="utf-8") == "corrupted JSON{{{"

        # Should create new clean cache file
        assert cache_file.exists()
        new_data = load_cache(cache_file)
        assert "apps" in new_data

    def test_save_updates_timestamp(self, tmp_path):
        """Tests that save updates last_updated timestamp."""
        cache_file = tmp_path / "discovery.json"
        cache = DiscoveryCache(cache_file)
        cache.data = create_default_cache()

        cache.save()

        loaded = load_cache(cache_file)
        assert "last_updated" in loaded["metadata"]

    def test_get_cache_existing(self, tmp_path):
        """Tests getting cache entry for existing recipe."""
        cache_file = tmp_path / "discovery.json"
        cache = DiscoveryCache(cache_file)
        cache.data = {
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

        entry = cache.get_cache("test-app")

        assert entry is not None
        assert entry["known_version"] == "1.2.3"
        assert entry["etag"] == 'W/"abc123"'
        assert entry["url"] == "https://vendor.com/app.msi"

    def test_get_cache_missing(self, tmp_path):
        """Tests getting cache entry for non-existent recipe returns None."""
        cache_file = tmp_path / "discovery.json"
        cache = DiscoveryCache(cache_file)
        cache.data = {"metadata": {}, "apps": {}}

        entry = cache.get_cache("nonexistent-app")

        assert entry is None

    def test_update_cache(self, tmp_path):
        """Tests updating cache entry for a recipe."""
        cache_file = tmp_path / "discovery.json"
        cache = DiscoveryCache(cache_file)
        cache.data = create_default_cache()

        cache.update_cache(
            recipe_id="test-app",
            url="https://vendor.com/file.msi",
            sha256="abc123",
            etag='W/"xyz789"',
            last_modified="Mon, 28 Oct 2024 10:00:00 GMT",
            known_version="2.0.0",
            strategy="url_download",
        )

        entry = cache.get_cache("test-app")
        assert entry["known_version"] == "2.0.0"
        assert entry["url"] == "https://vendor.com/file.msi"
        assert entry["etag"] == 'W/"xyz789"'
        assert entry["last_modified"] == "Mon, 28 Oct 2024 10:00:00 GMT"
        assert entry["sha256"] == "abc123"
        assert entry["strategy"] == "url_download"

    def test_has_version_changed_true(self, tmp_path):
        """Tests version change detection when version differs."""
        cache_file = tmp_path / "discovery.json"
        cache = DiscoveryCache(cache_file)
        cache.data = {
            "metadata": {},
            "apps": {"test-app": {"known_version": "1.0.0"}},
        }

        assert cache.has_version_changed("test-app", "2.0.0") is True

    def test_has_version_changed_false(self, tmp_path):
        """Tests version change detection when version same."""
        cache_file = tmp_path / "discovery.json"
        cache = DiscoveryCache(cache_file)
        cache.data = {
            "metadata": {},
            "apps": {"test-app": {"known_version": "1.0.0"}},
        }

        assert cache.has_version_changed("test-app", "1.0.0") is False

    def test_has_version_changed_no_cache(self, tmp_path):
        """Tests version change detection with no cached version."""
        cache_file = tmp_path / "discovery.json"
        cache = DiscoveryCache(cache_file)
        cache.data = {"metadata": {}, "apps": {}}

        # No cache means version changed
        assert cache.has_version_changed("test-app", "1.0.0") is True


class TestDeploymentStateFiles:
    """Tests for per-app deployment state persistence."""

    def test_deployment_state_path(self, tmp_path):
        """Tests that the state path is derived from the recipe id."""
        path = deployment_state_path(tmp_path / "deployment", "napt-chrome")

        assert path == tmp_path / "deployment" / "napt-chrome.json"

    def test_create_default_deployment_state(self):
        """Tests that the default structure has all empty sections."""
        state = create_default_deployment_state()

        assert state["deployed"] is None
        assert state["pending"] is None
        assert state["rings"] == {}
        assert state["retained"] == []

    def test_load_missing_file_returns_default(self, tmp_path):
        """Tests that a missing file loads as default state without creating it."""
        state_path = tmp_path / "deployment" / "napt-chrome.json"

        state = load_deployment_state(state_path)

        assert state == create_default_deployment_state()
        assert not state_path.exists()

    def test_save_and_load_round_trip(self, tmp_path):
        """Tests round-trip save and load."""
        state_path = tmp_path / "deployment" / "napt-chrome.json"
        state = create_default_deployment_state()
        state["pending"] = {
            "version": "130.0.0",
            "sha256": "abc123",
            "url": "https://dl.google.com/chrome.msi",
        }

        save_deployment_state(state, state_path)
        loaded = load_deployment_state(state_path)

        assert loaded == state

    def test_load_corrupted_file_raises(self, tmp_path):
        """Tests that a corrupted file raises instead of being replaced."""
        state_path = tmp_path / "napt-chrome.json"
        state_path.write_text("not JSON{{{", encoding="utf-8")

        with pytest.raises(PackagingError, match="Corrupted deployment state"):
            load_deployment_state(state_path)

        # The corrupted file must be left untouched (never silently replaced).
        assert state_path.read_text(encoding="utf-8") == "not JSON{{{"

    def test_save_is_deterministic(self, tmp_path):
        """Tests that logically identical state produces byte-identical files."""
        path_a = tmp_path / "a.json"
        path_b = tmp_path / "b.json"

        state_a = create_default_deployment_state()
        state_a["pending"] = {
            "version": "1.0.0",
            "sha256": "abc",
            "url": "https://vendor.com/app.msi",
        }
        # Same logical content, different key insertion order.
        state_b = {
            "retained": [],
            "rings": {},
            "pending": {
                "url": "https://vendor.com/app.msi",
                "sha256": "abc",
                "version": "1.0.0",
            },
            "deployed": None,
        }

        save_deployment_state(state_a, path_a)
        save_deployment_state(state_b, path_b)

        assert path_a.read_bytes() == path_b.read_bytes()

    def test_save_twice_is_byte_identical(self, tmp_path):
        """Tests that re-saving unchanged state does not alter the file."""
        state_path = tmp_path / "napt-chrome.json"
        state = create_default_deployment_state()
        state["pending"] = {"version": "1.0.0", "sha256": "abc", "url": "https://x"}

        save_deployment_state(state, state_path)
        first = state_path.read_bytes()
        save_deployment_state(state, state_path)

        assert state_path.read_bytes() == first


class TestRecordPending:
    """Tests for pending release recording (single slot, newest wins)."""

    def test_first_discovery_is_recorded(self):
        """Tests that a release is recorded when nothing is deployed or pending."""
        state = create_default_deployment_state()

        action = record_pending(
            state, version="1.0.0", sha256="aaa", url="https://vendor.com/1.msi"
        )

        assert action == "recorded"
        assert state["pending"] == {
            "version": "1.0.0",
            "sha256": "aaa",
            "url": "https://vendor.com/1.msi",
        }

    def test_rerun_with_same_release_is_noop(self):
        """Tests that re-discovering the pending release changes nothing."""
        state = create_default_deployment_state()
        record_pending(state, version="1.0.0", sha256="aaa", url="https://x/1.msi")

        action = record_pending(
            state, version="1.0.0", sha256="aaa", url="https://x/1.msi"
        )

        assert action is None
        assert state["pending"]["version"] == "1.0.0"

    def test_newer_release_replaces_pending(self):
        """Tests that a newer discovery replaces an unpublished candidate."""
        state = create_default_deployment_state()
        record_pending(state, version="1.0.0", sha256="aaa", url="https://x/1.msi")

        action = record_pending(
            state, version="2.0.0", sha256="bbb", url="https://x/2.msi"
        )

        assert action == "replaced"
        assert state["pending"] == {
            "version": "2.0.0",
            "sha256": "bbb",
            "url": "https://x/2.msi",
        }

    def test_deployed_release_is_not_recorded(self):
        """Tests that discovering the deployed release records nothing."""
        state = create_default_deployment_state()
        state["deployed"] = {"version": "1.0.0", "sha256": "aaa"}

        action = record_pending(
            state, version="1.0.0", sha256="aaa", url="https://x/1.msi"
        )

        assert action is None
        assert state["pending"] is None

    def test_rollback_to_deployed_clears_pending(self):
        """Tests that pending is cleared when the vendor serves the deployed release."""
        state = create_default_deployment_state()
        state["deployed"] = {"version": "1.0.0", "sha256": "aaa"}
        record_pending(state, version="2.0.0", sha256="bbb", url="https://x/2.msi")

        action = record_pending(
            state, version="1.0.0", sha256="aaa", url="https://x/1.msi"
        )

        assert action == "cleared"
        assert state["pending"] is None

    def test_same_version_different_binary_is_new(self):
        """Tests that identity is the hash, not the version string."""
        state = create_default_deployment_state()
        state["deployed"] = {"version": "1.0.0", "sha256": "aaa"}

        action = record_pending(
            state, version="1.0.0", sha256="zzz", url="https://x/1.msi"
        )

        assert action == "recorded"
        assert state["pending"]["sha256"] == "zzz"

    def test_newer_release_supersedes_pending_over_deployed(self):
        """Tests the full flow: deployed, pending, then an even newer release."""
        state = create_default_deployment_state()
        state["deployed"] = {"version": "1.0.0", "sha256": "aaa"}
        record_pending(state, version="2.0.0", sha256="bbb", url="https://x/2.msi")

        action = record_pending(
            state, version="3.0.0", sha256="ccc", url="https://x/3.msi"
        )

        assert action == "replaced"
        assert state["pending"]["version"] == "3.0.0"
        assert state["deployed"]["version"] == "1.0.0"


class TestRecordDeployed:
    """Tests for deployed release recording."""

    def test_records_deployed_and_clears_matching_pending(self):
        """Tests that publishing the pending release clears the slot."""
        state = create_default_deployment_state()
        record_pending(state, version="2.0.0", sha256="bbb", url="https://x/2.msi")

        record_deployed(
            state,
            version="2.0.0",
            sha256="bbb",
            intune_app_id="app-1",
            intune_update_app_id="update-1",
        )

        assert state["deployed"] == {
            "version": "2.0.0",
            "sha256": "bbb",
            "intune_app_id": "app-1",
            "intune_update_app_id": "update-1",
        }
        assert state["pending"] is None

    def test_preserves_newer_pending(self):
        """Tests that a pending release with a different hash is kept."""
        state = create_default_deployment_state()
        record_pending(state, version="3.0.0", sha256="ccc", url="https://x/3.msi")

        record_deployed(
            state,
            version="2.0.0",
            sha256="bbb",
            intune_app_id="app-1",
            intune_update_app_id=None,
        )

        assert state["deployed"]["version"] == "2.0.0"
        assert state["pending"]["version"] == "3.0.0"

    def test_replaces_previous_deployed(self):
        """Tests that a new publication replaces the deployed section."""
        state = create_default_deployment_state()
        record_deployed(
            state,
            version="1.0.0",
            sha256="aaa",
            intune_app_id="a",
            intune_update_app_id="b",
        )

        record_deployed(
            state,
            version="2.0.0",
            sha256="bbb",
            intune_app_id="c",
            intune_update_app_id="d",
        )

        assert state["deployed"]["version"] == "2.0.0"
        assert state["deployed"]["intune_app_id"] == "c"
