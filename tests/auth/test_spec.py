"""Tests for napt.auth.spec."""

from __future__ import annotations

from napt.auth import credentials
from napt.auth.spec import (
    APPLICATION_PERMISSIONS,
    DELEGATED_PERMISSIONS,
    REQUIRED_PERMISSIONS,
)


def test_permission_lists_share_one_required_set() -> None:
    """Tests that the permissions status checks, setup grants as application
    permissions, and setup grants as delegated permissions come from one
    definition, so the three can never disagree."""
    assert APPLICATION_PERMISSIONS == REQUIRED_PERMISSIONS
    assert set(REQUIRED_PERMISSIONS) <= set(DELEGATED_PERMISSIONS)
    assert credentials.REQUIRED_PERMISSIONS is REQUIRED_PERMISSIONS


def test_login_failed_hint_names_the_required_permissions() -> None:
    """Tests that the hint lists the same permissions status checks for."""
    for permission in REQUIRED_PERMISSIONS:
        assert permission in credentials._HINT_LOGIN_FAILED
