"""Shared helpers for CLI command tests."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock


def _args(**kwargs) -> argparse.Namespace:
    """Build Namespace with verbose=False, debug=False defaults."""
    defaults = {"verbose": False, "debug": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _mock_result(**kwargs) -> MagicMock:
    """Build a MagicMock with the given attributes."""
    result = MagicMock()
    for k, v in kwargs.items():
        setattr(result, k, v)
    return result
