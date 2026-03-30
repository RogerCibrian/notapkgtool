"""Tests for napt.upload.auth."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from napt.exceptions import AuthError
from napt.upload.auth import get_access_token


def test_get_access_token_returns_token_on_phase1_success() -> None:
    """Tests that get_access_token returns the token when Phase 1 succeeds."""
    mock_token = MagicMock()
    mock_token.token = "test-bearer-token"
    mock_credential = MagicMock()
    mock_credential.get_token.return_value = mock_token

    with patch("napt.upload.auth.get_credential", return_value=mock_credential):
        result = get_access_token()

    assert result == "test-bearer-token"


def test_get_access_token_raises_auth_error_when_all_fail_non_tty() -> None:
    """Tests that AuthError is raised when Phase 1 fails and stdout is not a TTY."""
    from azure.core.exceptions import ClientAuthenticationError

    mock_credential = MagicMock()
    mock_credential.get_token.side_effect = ClientAuthenticationError("no cred")

    with patch("napt.upload.auth.get_credential", return_value=mock_credential):
        with patch("napt.upload.auth.sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            with pytest.raises(AuthError):
                get_access_token()
