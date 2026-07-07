"""Tests for napt.upload.stamp."""

from __future__ import annotations

import pytest

from napt.exceptions import ConfigError
from napt.upload.stamp import (
    NOTES_MAX_LENGTH,
    build_stamp,
    parse_stamp,
)


class TestBuildStamp:
    """Tests for provenance stamp construction."""

    def test_builds_expected_format(self):
        """Tests that the stamp has the documented format."""
        stamp = build_stamp("napt-chrome", "install", "a" * 64)

        assert stamp == f"napt/v1 id=napt-chrome entry=install sha256={'a' * 64}"

    def test_round_trips_through_parse(self):
        """Tests that a built stamp parses back to its fields."""
        stamp = build_stamp("napt-chrome", "update", "b" * 64)

        assert parse_stamp(stamp) == {
            "id": "napt-chrome",
            "entry": "update",
            "sha256": "b" * 64,
        }

    def test_over_length_raises(self):
        """Tests that a stamp over the notes limit raises ConfigError."""
        long_id = "x" * NOTES_MAX_LENGTH

        with pytest.raises(ConfigError, match="notes field limit"):
            build_stamp(long_id, "install", "a" * 64)


class TestParseStamp:
    """Tests for provenance stamp parsing."""

    def test_none_returns_none(self):
        """Tests that None notes parse as no stamp."""
        assert parse_stamp(None) is None

    def test_empty_returns_none(self):
        """Tests that empty notes parse as no stamp."""
        assert parse_stamp("") is None

    def test_admin_text_returns_none(self):
        """Tests that non-NAPT notes parse as no stamp."""
        assert parse_stamp("Deployed by the IT team, ticket #42") is None

    def test_missing_field_returns_none(self):
        """Tests that a stamp without all required fields is rejected."""
        assert parse_stamp("napt/v1 id=napt-chrome sha256=abc") is None

    def test_prefix_must_match_exactly(self):
        """Tests that a different stamp version is not parsed as v1."""
        assert parse_stamp("napt/v2 id=a entry=install sha256=b") is None

    def test_extra_tokens_are_tolerated(self):
        """Tests that unknown key=value tokens do not break parsing."""
        stamp = "napt/v1 id=app entry=install sha256=abc future=stuff"

        assert parse_stamp(stamp) == {
            "id": "app",
            "entry": "install",
            "sha256": "abc",
        }
