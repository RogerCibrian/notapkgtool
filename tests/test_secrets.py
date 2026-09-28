"""Tests for napt.secrets."""

from __future__ import annotations

import pytest
import requests
import requests_mock

from napt.download.download import make_session
from napt.exceptions import ConfigError, NetworkError
from napt.secrets import (
    bound_hosts,
    check_secret_use,
    expand_secrets,
    guarded_get,
    secret_names,
)

_URL = "https://api.vendor.com/latest"
_FIELD = "discovery.headers.Authorization"


def _config(**secrets: list[str]) -> dict:
    return {"secrets": {name: {"hosts": hosts} for name, hosts in secrets.items()}}


class TestSecretNames:
    """Tests for secret reference parsing."""

    def test_finds_each_reference_once_in_order(self):
        """Tests that references anywhere in the value are found, deduplicated."""
        assert secret_names("Bearer ${A} ${B} ${A}") == ["A", "B"]

    def test_plain_value_has_no_references(self):
        """Tests that text without ${...} references none."""
        assert secret_names("application/json") == []

    def test_malformed_reference_is_ignored(self):
        """Tests that an empty or invalid name is not a reference."""
        assert secret_names("${} ${1BAD} ${A-B}") == []


class TestCheckSecretUse:
    """Tests for the static binding check shared with napt validate."""

    def test_declared_secret_to_bound_host_is_clean(self):
        """Tests that a declared secret sent to a bound host passes."""
        config = _config(API_TOKEN=["api.vendor.com"])
        assert check_secret_use(config, "Bearer ${API_TOKEN}", _URL, _FIELD) == []

    def test_host_match_ignores_case_and_port(self):
        """Tests that hosts compare by hostname, case-insensitively."""
        config = _config(API_TOKEN=["API.Vendor.com"])
        url = "https://api.vendor.com:8443/latest"
        assert check_secret_use(config, "${API_TOKEN}", url, _FIELD) == []

    def test_undeclared_secret_is_an_error(self):
        """Tests that a variable org.yaml does not declare is unreachable."""
        errors = check_secret_use(_config(), "${AZURE_CLIENT_SECRET}", _URL, _FIELD)
        assert len(errors) == 1
        assert "AZURE_CLIENT_SECRET" in errors[0]
        assert "does not declare" in errors[0]
        assert errors[0].startswith(_FIELD)

    def test_unbound_host_is_refused(self):
        """Tests that a declared secret is refused for a host not in its list."""
        config = _config(API_TOKEN=["api.vendor.com"])
        errors = check_secret_use(
            config, "${API_TOKEN}", "https://evil.example.com/x", _FIELD
        )
        assert len(errors) == 1
        assert "Refusing to send secret API_TOKEN to evil.example.com" in errors[0]
        assert errors[0].endswith("binds it to api.vendor.com")

    @pytest.mark.parametrize(
        "url",
        [
            # urlsplit reads the host after the "@" (api.vendor.com);
            # requests cuts the authority at the backslash and connects to
            # evil.com.
            "https://evil.com\\@api.vendor.com/latest",
            "https://evil.com\\\\@api.vendor.com/latest",
            # Plain userinfo: unambiguous today, but the same shape.
            "https://user@api.vendor.com/latest",
            "https://api.vendor.com@evil.com/latest",
            # Whitespace and control characters in the authority.
            "https://api.vendor.com evil.com/latest",
            "https://api.vendor.com\tevil.com/latest",
        ],
    )
    def test_ambiguous_authority_is_refused(self, url):
        """Tests that a URL two parsers could read differently never passes
        the host check, whichever host the check itself would read."""
        config = _config(API_TOKEN=["api.vendor.com", "evil.com"])
        errors = check_secret_use(config, "${API_TOKEN}", url, _FIELD)
        assert len(errors) == 1
        assert errors[0].startswith(_FIELD)

    @pytest.mark.parametrize(
        "url", ["https://api.vendor.com:abc/latest", "https://[::1/latest"]
    )
    def test_unparseable_url_is_refused(self, url):
        """Tests that a URL the request layer cannot parse is refused."""
        config = _config(API_TOKEN=["api.vendor.com"])
        errors = check_secret_use(config, "${API_TOKEN}", url, _FIELD)
        assert len(errors) == 1
        assert "cannot be parsed" in errors[0]

    def test_plain_http_is_refused(self):
        """Tests that a secret is never sent in clear text."""
        config = _config(API_TOKEN=["api.vendor.com"])
        errors = check_secret_use(
            config, "${API_TOKEN}", "http://api.vendor.com/x", _FIELD
        )
        assert len(errors) == 1
        assert "https" in errors[0]

    def test_value_without_references_is_clean_anywhere(self):
        """Tests that a plain header value needs no declaration."""
        assert check_secret_use({}, "text/plain", "http://x/", _FIELD) == []


class TestExpandSecrets:
    """Tests for runtime expansion."""

    def test_expands_inside_surrounding_text(self, monkeypatch):
        """Tests that ${VAR} anywhere in the value is replaced."""
        monkeypatch.setenv("API_TOKEN", "abc")
        config = _config(API_TOKEN=["api.vendor.com"])
        assert expand_secrets(config, "Bearer ${API_TOKEN}", _URL, _FIELD) == (
            "Bearer abc"
        )

    def test_unset_declared_secret_is_an_error(self, monkeypatch):
        """Tests that a declared but unset variable stops discovery."""
        monkeypatch.delenv("API_TOKEN", raising=False)
        config = _config(API_TOKEN=["api.vendor.com"])
        with pytest.raises(ConfigError, match="not set"):
            expand_secrets(config, "${API_TOKEN}", _URL, _FIELD)

    def test_empty_declared_secret_is_an_error(self, monkeypatch):
        """Tests that an empty variable counts as unset."""
        monkeypatch.setenv("API_TOKEN", "")
        config = _config(API_TOKEN=["api.vendor.com"])
        with pytest.raises(ConfigError, match="not set"):
            expand_secrets(config, "${API_TOKEN}", _URL, _FIELD)

    def test_binding_violation_raises_before_lookup(self, monkeypatch):
        """Tests that an unbound host is refused even when the variable is set."""
        monkeypatch.setenv("API_TOKEN", "abc")
        config = _config(API_TOKEN=["api.vendor.com"])
        with pytest.raises(ConfigError, match="Refusing to send secret"):
            expand_secrets(config, "${API_TOKEN}", "https://evil.example.com", _FIELD)

    def test_undeclared_secret_raises(self, monkeypatch):
        """Tests that an undeclared variable is refused even when set."""
        monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
        with pytest.raises(ConfigError, match="does not declare"):
            expand_secrets({}, "${AZURE_CLIENT_SECRET}", _URL, _FIELD)


class TestBoundHosts:
    """Tests for the host set a request carrying secrets may visit."""

    def test_no_references_means_no_restriction(self):
        """Tests that plain values leave redirects unrestricted."""
        assert bound_hosts({}, ["text/plain"]) is None

    def test_intersection_of_every_secret(self):
        """Tests that a request carrying two secrets may only visit hosts
        both are bound to."""
        config = _config(A=["a.com", "shared.com"], B=["shared.com", "b.com"])
        assert bound_hosts(config, ["${A}", "x ${B}"]) == {"shared.com"}

    def test_undeclared_reference_binds_to_no_host(self):
        """Tests that an undeclared secret leaves nowhere for a redirect
        to go, should one ever get past the static check."""
        assert bound_hosts({}, ["${T}"]) == set()


class TestGuardedGet:
    """Tests for the redirect guard."""

    def test_without_secrets_redirects_are_followed(self):
        """Tests that a request carrying no secret follows redirects as before."""
        with requests_mock.Mocker() as m, make_session() as session:
            m.get(
                "https://a.com/x",
                status_code=302,
                headers={"Location": "https://b.com/y"},
            )
            m.get("https://b.com/y", json={"ok": True})
            resp = guarded_get(session, "https://a.com/x", {}, hosts=None, timeout=5)
        assert resp.json() == {"ok": True}

    def test_redirect_within_bound_hosts_is_followed(self):
        """Tests that a redirect to another bound host keeps the headers."""
        with requests_mock.Mocker() as m, make_session() as session:
            m.get(
                "https://a.com/x",
                status_code=301,
                headers={"Location": "/y"},
            )
            m.get("https://a.com/y", json={"ok": True})
            resp = guarded_get(
                session,
                "https://a.com/x",
                {"Authorization": "s"},
                hosts={"a.com"},
                timeout=5,
            )
        assert resp.json() == {"ok": True}
        assert m.last_request.headers["Authorization"] == "s"

    def test_redirect_to_another_host_is_refused(self):
        """Tests that a redirect off the bound hosts stops with the headers
        unsent."""
        with requests_mock.Mocker() as m, make_session() as session:
            m.get(
                "https://a.com/x",
                status_code=302,
                headers={"Location": "https://evil.example.com/y"},
            )
            m.get("https://evil.example.com/y", json={"ok": True})
            with pytest.raises(NetworkError, match="evil.example.com"):
                guarded_get(
                    session,
                    "https://a.com/x",
                    {"X-API-Key": "s"},
                    hosts={"a.com"},
                    timeout=5,
                )
        assert m.call_count == 1

    def test_redirect_to_plain_http_is_refused(self):
        """Tests that a downgrade to http is refused even on a bound host."""
        with requests_mock.Mocker() as m, make_session() as session:
            m.get(
                "https://a.com/x",
                status_code=302,
                headers={"Location": "http://a.com/y"},
            )
            with pytest.raises(NetworkError, match="https"):
                guarded_get(
                    session,
                    "https://a.com/x",
                    {"X-API-Key": "s"},
                    hosts={"a.com"},
                    timeout=5,
                )
        assert m.call_count == 1

    @pytest.mark.parametrize(
        "location",
        [
            "https://evil.com\\@a.com/y",
            "https://user@a.com/y",
            "https://a.com evil.com/y",
            # Unparseable by the request layer.
            "https://a.com:abc/y",
        ],
    )
    def test_redirect_to_ambiguous_authority_is_refused(self, location):
        """Tests that a Location two parsers could read differently, or
        that cannot be parsed at all, is refused even when the host the
        guard would read is bound."""
        with requests_mock.Mocker() as m, make_session() as session:
            # The later registration wins in requests_mock, so the
            # catch-all goes first and the redirect second.
            m.get(requests_mock.ANY, json={"ok": True})
            m.get(
                "https://a.com/x",
                status_code=302,
                headers={"Location": location},
            )
            with pytest.raises(NetworkError, match="Refusing to follow"):
                guarded_get(
                    session,
                    "https://a.com/x",
                    {"X-API-Key": "s"},
                    hosts={"a.com", "evil.com"},
                    timeout=5,
                )
        assert m.call_count == 1

    def test_redirect_loop_stops(self):
        """Tests that endless redirects end in an error, not a hang."""
        with requests_mock.Mocker() as m, make_session() as session:
            m.get(
                "https://a.com/x",
                status_code=302,
                headers={"Location": "https://a.com/x"},
            )
            with pytest.raises(NetworkError, match="redirect"):
                guarded_get(
                    session,
                    "https://a.com/x",
                    {"X-API-Key": "s"},
                    hosts={"a.com"},
                    timeout=5,
                )

    def test_connection_errors_propagate(self):
        """Tests that transport errors are left to the caller to wrap."""
        with requests_mock.Mocker() as m, make_session() as session:
            m.get("https://a.com/x", exc=requests.ConnectionError("down"))
            with pytest.raises(requests.ConnectionError):
                guarded_get(session, "https://a.com/x", {}, hosts={"a.com"}, timeout=5)
