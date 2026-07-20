"""Tests for napt.promote.preflight."""

from __future__ import annotations

from unittest.mock import patch

from napt.exceptions import ConfigError
from napt.promote.preflight import unresolvable_groups

TOKEN = "tok"


def _resolve_or_raise(token, group, cache=None):
    """Resolves any group except ones containing 'missing'."""
    if "missing" in group:
        raise ConfigError(f"No Entra ID group found with displayName '{group}'.")
    return {
        "@odata.type": "#microsoft.graph.groupAssignmentTarget",
        "groupId": f"gid-{group}",
    }


def _actions(*group_lists: list[str]) -> list[dict]:
    return [
        {"type": "promote", "app_id": f"app-{i}", "groups": groups}
        for i, groups in enumerate(group_lists)
    ]


class TestUnresolvableGroups:
    """Tests for plan group validation."""

    def test_all_groups_resolve(self):
        """Tests that a plan whose groups all resolve reports no failures."""
        with patch(
            "napt.promote.preflight.resolve_assignment_target",
            side_effect=_resolve_or_raise,
        ):
            failures = unresolvable_groups(
                TOKEN, _actions(["Pilot Devices"], ["Broad Devices"])
            )

        assert failures == []

    def test_unresolvable_group_reported_once(self):
        """Tests that a group used by several actions is resolved and
        reported only once."""
        with patch(
            "napt.promote.preflight.resolve_assignment_target",
            side_effect=_resolve_or_raise,
        ) as resolve_mock:
            failures = unresolvable_groups(
                TOKEN, _actions(["missing-group"], ["missing-group"], ["Real"])
            )

        assert len(failures) == 1
        assert "missing-group" in failures[0]
        assert resolve_mock.call_count == 2  # one per distinct group

    def test_successful_resolutions_fill_shared_cache(self):
        """Tests that resolutions land in the caller's cache for reuse."""
        cache: dict[str, str] = {}

        def _resolve(token, group, group_id_cache=None):
            group_id_cache[group] = f"gid-{group}"
            return {"@odata.type": "#t", "groupId": f"gid-{group}"}

        with patch(
            "napt.promote.preflight.resolve_assignment_target",
            side_effect=_resolve,
        ):
            failures = unresolvable_groups(TOKEN, _actions(["Pilot Devices"]), cache)

        assert failures == []
        assert cache == {"Pilot Devices": "gid-Pilot Devices"}

    def test_actions_without_groups_are_skipped(self):
        """Tests that actions with no groups key produce no lookups."""
        with patch(
            "napt.promote.preflight.resolve_assignment_target"
        ) as resolve_mock:
            failures = unresolvable_groups(TOKEN, [{"type": "odd_action"}])

        assert failures == []
        resolve_mock.assert_not_called()
