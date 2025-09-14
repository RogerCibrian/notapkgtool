import getpass
import os
import time
from typing import Optional

from dotenv import load_dotenv
import requests


class CredentialManager:
    """
    Loads INTUNE_* environment variables (optionally from .env) and manages
    a cached Microsoft Graph access token that is refreshed automatically
    when it is about to expire.
    """

    def __init__(self, env_prefix: str = "INTUNE_", refresh_margin: int = 60) -> None:
        """
        :param env_prefix: Prefix used for environment variables.
        :param refresh_margin: Seconds before real expiry when we proactively refresh.
        """
        load_dotenv()
        self.env_prefix = env_prefix
        self.refresh_margin = refresh_margin
        self._token: Optional[str] = None
        self._token_expires_at: Optional[int] = None  # UNIX epoch

    # --------------------------------------------------------------------- #
    # Helper: read required env var
    # --------------------------------------------------------------------- #
    def _env(self, key: str) -> str:
        full_key = f"{self.env_prefix}{key}"
        value = os.getenv(full_key)
        if value is None:
            raise RuntimeError(f"Missing required environment variable: {full_key}")
        return value

    # --------------------------------------------------------------------- #
    # Public getters for ID / secret
    # --------------------------------------------------------------------- #
    def get_client_id(self) -> str:
        return self._env("CLIENT_ID")

    def get_tenant_id(self) -> str:
        return self._env("TENANT_ID")

    def get_client_secret(self) -> str:
        try:
            return self._env("CLIENT_SECRET")
        except RuntimeError:
            return getpass.getpass("Enter your client secret: ")

    # --------------------------------------------------------------------- #
    # Token handling
    # --------------------------------------------------------------------- #
    def _token_expired(self) -> bool:
        if self._token is None or self._token_expires_at is None:
            return True
        return time.time() >= (self._token_expires_at - self.refresh_margin)

    def _fetch_token(self) -> None:
        """
        Performs the client-credentials flow and stores
        self._token and self._token_expires_at.
        """
        tenant = self.get_tenant_id()
        url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

        data = {
            "client_id": self.get_client_id(),
            "client_secret": self.get_client_secret(),
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }

        response = requests.post(url, data=data)
        response.raise_for_status()

        token_data = response.json()
        self._token = token_data["access_token"]
        # expires_in is seconds until expiry
        expires_in = int(token_data.get("expires_in", 0))
        self._token_expires_at = int(time.time()) + expires_in

    def get_token(self) -> str:
        """
        Returns a valid access token, refreshing it when necessary.
        """
        if self._token_expired():
            self._fetch_token()
        # At this point self._token is guaranteed to be str and valid
        return self._token  # type: ignore[return-value]
