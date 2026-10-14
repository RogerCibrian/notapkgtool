"""Tests for napt.github, the GitHub API access shared by three callers."""

from __future__ import annotations

import pytest
import requests

from napt.exceptions import ConfigError, NetworkError
from napt.github import (
    api_headers,
    asset_names,
    asset_url,
    download,
    env_token,
    find_asset,
    get_json,
    latest_release,
    normalize_release_spec,
    release_by_version,
    release_tag,
    repo_file,
    verify_size,
    version_from_tag,
)

_URL = "https://api.github.com/repos/owner/repo/releases/latest"


class TestHeaders:
    """Tests for the request headers."""

    def test_headers_without_a_token(self):
        """Tests that an unauthenticated call sends no Authorization."""
        headers = api_headers(None)

        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert "Authorization" not in headers

    def test_headers_with_a_token_use_bearer(self):
        """Tests that one authorization scheme is used for every caller."""
        assert api_headers("ghp_x")["Authorization"] == "Bearer ghp_x"

    def test_env_token_reads_github_token(self, monkeypatch):
        """Tests that GITHUB_TOKEN is the environment token."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
        assert env_token() == "ghp_env"

    def test_env_token_is_none_when_unset_or_empty(self, monkeypatch):
        """Tests that an unset or empty variable means no token."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert env_token() is None
        monkeypatch.setenv("GITHUB_TOKEN", "")
        assert env_token() is None


class TestGetJson:
    """Tests for the one request path."""

    def test_returns_the_object(self, requests_mock):
        """Tests that a JSON object body is returned."""
        requests_mock.get(_URL, json={"tag_name": "1.0"})
        with requests.Session() as session:
            assert get_json(session, _URL, what="x") == {"tag_name": "1.0"}

    def test_404_is_none(self, requests_mock):
        """Tests that a missing resource is None, for callers that try again."""
        requests_mock.get(_URL, status_code=404)
        with requests.Session() as session:
            assert get_json(session, _URL, what="x") is None

    def test_rate_limit_is_named_from_the_header(self, requests_mock):
        """Tests that a 403 with no requests remaining is a rate limit."""
        requests_mock.get(_URL, status_code=403, headers={"X-RateLimit-Remaining": "0"})
        with (
            requests.Session() as session,
            pytest.raises(NetworkError, match="rate limit exceeded while fetching x"),
        ):
            get_json(session, _URL, what="x")

    def test_other_403_is_a_refusal(self, requests_mock):
        """Tests that a 403 with requests remaining is not called a rate limit."""
        requests_mock.get(
            _URL,
            status_code=403,
            reason="Forbidden",
            headers={"X-RateLimit-Remaining": "10"},
        )
        with (
            requests.Session() as session,
            pytest.raises(NetworkError, match="refused the request for x: 403"),
        ):
            get_json(session, _URL, what="x")

    def test_failed_status_names_what_and_status(self, requests_mock):
        """Tests that any other failure carries the status and reason."""
        requests_mock.get(_URL, status_code=502, reason="Bad Gateway")
        with (
            requests.Session() as session,
            pytest.raises(NetworkError, match="x failed: 502 Bad Gateway"),
        ):
            get_json(session, _URL, what="x")

    def test_transport_failure_is_a_network_error(self, requests_mock):
        """Tests that a connection failure is reported, not raised raw."""
        requests_mock.get(_URL, exc=requests.ConnectionError("no route"))
        with (
            requests.Session() as session,
            pytest.raises(NetworkError, match="Failed to fetch x: no route"),
        ):
            get_json(session, _URL, what="x")

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"text": "<html>"}, "Invalid JSON response from the GitHub API for x"),
            ({"json": [1]}, "Unexpected GitHub API response for x"),
        ],
    )
    def test_bad_bodies_are_network_errors(self, requests_mock, kwargs, message):
        """Tests that a body that is not a JSON object is reported."""
        requests_mock.get(_URL, **kwargs)
        with requests.Session() as session, pytest.raises(NetworkError, match=message):
            get_json(session, _URL, what="x")

    def test_token_is_sent_and_bound_to_the_api_host(self, requests_mock):
        """Tests that a token is sent, and a redirect elsewhere refused."""
        requests_mock.get(
            _URL, status_code=302, headers={"Location": "https://evil.example/x"}
        )
        with (
            requests.Session() as session,
            pytest.raises(NetworkError, match="Refusing to follow the redirect"),
        ):
            get_json(session, _URL, what="x", token="ghp_x")
        assert requests_mock.last_request.headers["Authorization"] == "Bearer ghp_x"


class TestLookups:
    """Tests for the release and contents lookups."""

    def test_latest_release_404_names_the_repository(self, requests_mock):
        """Tests that a repository with no releases is reported by name."""
        requests_mock.get(_URL, status_code=404)
        with (
            requests.Session() as session,
            pytest.raises(NetworkError, match="'owner/repo' not found or has no"),
        ):
            latest_release(session, "owner/repo")

    def test_release_by_version_tries_both_spellings(self, requests_mock):
        """Tests that a bare tag is tried first, then the v-prefixed one."""
        requests_mock.get(
            "https://api.github.com/repos/owner/repo/releases/tags/1.2.3",
            status_code=404,
        )
        requests_mock.get(
            "https://api.github.com/repos/owner/repo/releases/tags/v1.2.3",
            json={"tag_name": "v1.2.3"},
        )
        with requests.Session() as session:
            tag, release = release_by_version(session, "owner/repo", "1.2.3")

        assert (tag, release) == ("v1.2.3", {"tag_name": "v1.2.3"})

    def test_release_by_version_without_a_match(self, requests_mock):
        """Tests that neither spelling matching is reported."""
        requests_mock.get(
            "https://api.github.com/repos/owner/repo/releases/tags/1.2.3",
            status_code=404,
        )
        requests_mock.get(
            "https://api.github.com/repos/owner/repo/releases/tags/v1.2.3",
            status_code=404,
        )
        with (
            requests.Session() as session,
            pytest.raises(NetworkError, match="tagged 1.2.3 or v1.2.3"),
        ):
            release_by_version(session, "owner/repo", "1.2.3")

    def test_repo_file_looks_up_a_path_at_a_ref(self, requests_mock):
        """Tests that the contents API is asked for the path at the ref."""
        requests_mock.get(
            "https://api.github.com/repos/owner/repo/contents/tool.exe?ref=v1",
            json={"name": "tool.exe", "size": 3},
        )
        with requests.Session() as session:
            entry = repo_file(session, "owner/repo", "tool.exe", "v1")

        assert entry == {"name": "tool.exe", "size": 3}
        assert requests_mock.last_request.qs == {"ref": ["v1"]}


class TestReleaseFields:
    """Tests for reading tags, versions, and assets."""

    def test_release_tag(self):
        """Tests that the tag is read as the repository spells it."""
        assert release_tag({"tag_name": "v1.2.3"}) == "v1.2.3"

    @pytest.mark.parametrize("release", [{}, {"tag_name": ""}, {"tag_name": 5}])
    def test_release_without_a_tag(self, release):
        """Tests that a missing or malformed tag is reported."""
        with pytest.raises(NetworkError, match="missing 'tag_name'"):
            release_tag(release)

    @pytest.mark.parametrize(
        ("tag", "version"),
        [("1.2.3", "1.2.3"), ("v1.2.3", "1.2.3"), ("4.1.7.1", "4.1.7.1"), ("v2", None)],
    )
    def test_version_from_tag(self, tag, version):
        """Tests that a whole-tag version is read with or without a v."""
        if version is None:
            with pytest.raises(NetworkError, match="Could not extract version"):
                version_from_tag(tag)
        else:
            assert version_from_tag(tag) == version

    @pytest.mark.parametrize("tag", ["1.2.3-rc1", "v1.2.3.beta", "1.2.3 hotfix", "x"])
    def test_version_from_tag_rejects_suffixes(self, tag):
        """Tests that a tag is never cut down to the version it starts with."""
        with pytest.raises(NetworkError, match="Could not extract version"):
            version_from_tag(tag)

    @pytest.mark.parametrize("spec", ["4.1.7", "v4.1.7"])
    def test_normalize_release_spec(self, spec):
        """Tests that a pinned version loses its v prefix."""
        assert normalize_release_spec(spec, "psadt.release", "4.1.7") == "4.1.7"

    @pytest.mark.parametrize("spec", ["", "v", "../x", "4.1.7/x"])
    def test_normalize_release_spec_rejects_non_versions(self, spec):
        """Tests that a value that cannot name a cache folder is refused."""
        with pytest.raises(ConfigError, match="Invalid psadt.release"):
            normalize_release_spec(spec, "psadt.release", "4.1.7")

    def test_find_asset_and_names(self):
        """Tests that the first matching asset is found and names are listed."""
        release = {"assets": [{"name": "a.txt"}, {"name": "b.zip"}, {"name": "c.zip"}]}

        assert find_asset(release, lambda n: n.endswith(".zip")) == {"name": "b.zip"}
        assert find_asset(release, lambda n: n.endswith(".msi")) is None
        assert asset_names(release) == ["a.txt", "b.zip", "c.zip"]

    def test_asset_url(self):
        """Tests that the download URL is read, and its absence reported."""
        assert asset_url({"browser_download_url": "https://x/y"}) == "https://x/y"
        with pytest.raises(NetworkError, match="Asset a.zip has no download URL"):
            asset_url({"name": "a.zip", "browser_download_url": ""})


class TestDownload:
    """Tests for downloading and checking asset bytes."""

    def test_download_returns_bytes(self, requests_mock):
        """Tests that the body is returned."""
        requests_mock.get("https://x/a.zip", content=b"zip")
        with requests.Session() as session:
            assert download(session, "https://x/a.zip", what="a.zip") == b"zip"

    def test_download_failure_is_a_network_error(self, requests_mock):
        """Tests that a failed download names what was being fetched."""
        requests_mock.get("https://x/a.zip", status_code=500)
        with (
            requests.Session() as session,
            pytest.raises(NetworkError, match="Failed to download a.zip"),
        ):
            download(session, "https://x/a.zip", what="a.zip")

    def test_verify_size(self):
        """Tests that a size mismatch is reported and a missing size ignored."""
        verify_size("a.zip", b"abc", 3)
        verify_size("a.zip", b"abc", None)
        with pytest.raises(NetworkError, match="is 3 bytes; GitHub reports 4"):
            verify_size("a.zip", b"abc", 4)
