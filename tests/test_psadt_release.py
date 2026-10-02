"""
Tests for napt.psadt.release module.

Tests PSADT release management including:
- Fetching latest version from GitHub
- Downloading and caching releases
- Version resolution
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from napt.exceptions import NetworkError
from napt.psadt.release import get_psadt_release, is_psadt_cached

_LATEST_URL = (
    "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/"
    "releases/latest"
)


def _cache_toolkit(cache_dir: Path, version: str = "4.1.7") -> Path:
    """Lays out a complete cached toolkit and returns its folder."""
    version_dir = cache_dir / version
    (version_dir / "PSAppDeployToolkit").mkdir(parents=True)
    (version_dir / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").write_text(
        "# manifest"
    )
    (version_dir / "Invoke-AppDeployToolkit.ps1").write_text("# script")
    (version_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"MZ")
    (version_dir / "Files").mkdir()
    return version_dir


class TestLatestPSADTVersion:
    """Tests for resolving 'latest' through the GitHub API.

    Each test caches the expected version first, so resolving is the only
    request made.
    """

    def test_latest_resolves_to_the_tag_version(self, tmp_path, requests_mock):
        """Tests that the latest tag names the cache entry used."""
        version_dir = _cache_toolkit(tmp_path / "cache")
        requests_mock.get(_LATEST_URL, json={"tag_name": "4.1.7"})

        assert get_psadt_release("latest", tmp_path / "cache") == version_dir

    def test_latest_tag_with_v_prefix(self, tmp_path, requests_mock):
        """Tests that a v prefix on the tag is not part of the version."""
        version_dir = _cache_toolkit(tmp_path / "cache")
        requests_mock.get(_LATEST_URL, json={"tag_name": "v4.1.7"})

        assert get_psadt_release("latest", tmp_path / "cache") == version_dir

    def test_latest_api_404_is_a_network_error(self, tmp_path, requests_mock):
        """Tests that a repository with no releases is reported."""
        requests_mock.get(_LATEST_URL, status_code=404)

        with pytest.raises(NetworkError, match="not found or has no releases"):
            get_psadt_release("latest", tmp_path / "cache")

    def test_latest_api_failure_is_a_network_error(self, tmp_path, requests_mock):
        """Tests that a failed API call is reported with its status."""
        requests_mock.get(_LATEST_URL, status_code=500, reason="Server Error")

        with pytest.raises(NetworkError, match="500"):
            get_psadt_release("latest", tmp_path / "cache")

    def test_latest_missing_tag(self, tmp_path, requests_mock):
        """Tests that a release without a tag_name is reported."""
        requests_mock.get(_LATEST_URL, json={})

        with pytest.raises(NetworkError, match="missing 'tag_name'"):
            get_psadt_release("latest", tmp_path / "cache")

    @pytest.mark.parametrize(
        "tag", ["invalid-tag", "4.1.7-rc1", "v4.1.7.beta", "4.1.7 hotfix"]
    )
    def test_latest_tag_that_is_not_a_version_is_rejected(
        self, tmp_path, requests_mock, tag
    ):
        """Tests that a tag with a suffix is never cut down to a bare version."""
        requests_mock.get(_LATEST_URL, json={"tag_name": tag})

        with pytest.raises(NetworkError, match="Could not extract version from tag"):
            get_psadt_release("latest", tmp_path / "cache")

    def test_latest_non_json_response_is_a_network_error(self, tmp_path, requests_mock):
        """Tests that a 200 that is not JSON is reported, not a traceback."""
        requests_mock.get(_LATEST_URL, text="<html>maintenance</html>")

        with pytest.raises(NetworkError, match="Invalid JSON"):
            get_psadt_release("latest", tmp_path / "cache")

    def test_latest_json_that_is_not_an_object_is_a_network_error(
        self, tmp_path, requests_mock
    ):
        """Tests that a JSON body of the wrong shape is reported."""
        requests_mock.get(_LATEST_URL, json=["unexpected"])

        with pytest.raises(NetworkError, match="Unexpected GitHub API response"):
            get_psadt_release("latest", tmp_path / "cache")


class TestIsPSADTCached:
    """Tests for checking if PSADT is cached."""

    def test_is_cached_true(self, tmp_path):
        """Test detection of cached PSADT."""
        _cache_toolkit(tmp_path / "cache")

        assert is_psadt_cached("4.1.7", tmp_path / "cache") is True

    def test_is_cached_false_without_the_launcher(self, tmp_path):
        """Tests that an entry holding only the module is not complete."""
        manifest = (
            tmp_path
            / "cache"
            / "4.1.7"
            / "PSAppDeployToolkit"
            / "PSAppDeployToolkit.psd1"
        )
        manifest.parent.mkdir(parents=True)
        manifest.write_text("# manifest")

        assert is_psadt_cached("4.1.7", tmp_path / "cache") is False

    def test_is_cached_false_no_directory(self, tmp_path):
        """Test when cache directory doesn't exist."""
        cache_dir = tmp_path / "cache"

        assert is_psadt_cached("4.1.7", cache_dir) is False

    def test_is_cached_false_no_manifest(self, tmp_path):
        """Test when directory exists but manifest missing."""
        cache_dir = tmp_path / "cache"
        version_dir = cache_dir / "4.1.7"
        psadt_dir = version_dir / "PSAppDeployToolkit"
        psadt_dir.mkdir(parents=True)

        assert is_psadt_cached("4.1.7", cache_dir) is False


class TestGetPSADTRelease:
    """Tests for downloading and caching PSADT releases."""

    _LATEST = (
        "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/"
        "releases/latest"
    )
    _TAGS = (
        "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/"
        "releases/tags/"
    )

    @staticmethod
    def _cache_toolkit(cache_dir: Path, version: str = "4.1.7") -> Path:
        """Lays out a complete cached toolkit and returns its folder."""
        version_dir = cache_dir / version
        (version_dir / "PSAppDeployToolkit").mkdir(parents=True)
        (version_dir / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").write_text(
            "# manifest"
        )
        (version_dir / "Invoke-AppDeployToolkit.ps1").write_text("# script")
        (version_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"MZ")
        (version_dir / "Files").mkdir()
        return version_dir

    def test_get_release_already_cached(self, tmp_path):
        """Test using already cached release."""
        cache_dir = tmp_path / "cache"
        version_dir = self._cache_toolkit(cache_dir)

        result = get_psadt_release("4.1.7", cache_dir)

        assert result == version_dir

    def test_latest_lookup_sends_the_github_token(
        self, tmp_path, requests_mock, monkeypatch
    ):
        """Tests that a GITHUB_TOKEN in the environment authenticates the lookup."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        self._cache_toolkit(tmp_path / "cache")
        requests_mock.get(self._LATEST, json={"tag_name": "4.1.7"})

        get_psadt_release("latest", tmp_path / "cache")

        assert requests_mock.last_request.headers["Authorization"] == "Bearer ghp_test"

    def test_latest_download_makes_one_api_call(self, tmp_path, requests_mock):
        """Tests that the latest-release body is reused for the download."""
        zip_bytes = self._psadt_zip()
        requests_mock.get(
            self._LATEST,
            json={
                "tag_name": "v4.1.7",
                "assets": [
                    {
                        "name": "PSAppDeployToolkit_Template_v4_v4.1.7.zip",
                        "browser_download_url": "https://github.com/test/download.zip",
                        "size": len(zip_bytes),
                    }
                ],
            },
        )
        requests_mock.get("https://github.com/test/download.zip", content=zip_bytes)

        result = get_psadt_release("latest", tmp_path / "cache")

        assert result == tmp_path / "cache" / "4.1.7"
        api_calls = [
            r.url for r in requests_mock.request_history if "api.github.com" in r.url
        ]
        assert api_calls == [self._LATEST]

    def test_rate_limit_is_reported(self, tmp_path, requests_mock):
        """Tests that an exhausted rate limit is named as the cause."""
        requests_mock.get(
            self._LATEST, status_code=403, headers={"X-RateLimit-Remaining": "0"}
        )
        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="rate limit"):
            get_psadt_release("latest", tmp_path / "cache")

    def test_forbidden_without_a_rate_limit_is_not_called_one(
        self, tmp_path, requests_mock
    ):
        """Tests that a 403 for another reason is reported as a refusal."""
        requests_mock.get(self._LATEST, status_code=403, reason="Forbidden")
        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="403") as info:
            get_psadt_release("latest", tmp_path / "cache")
        assert "rate limit" not in str(info.value)

    def test_pinned_version_tries_the_v_prefixed_tag(self, tmp_path, requests_mock):
        """Tests that a pinned version finds a release tagged with a v prefix."""
        zip_bytes = self._psadt_zip()
        requests_mock.get(f"{self._TAGS}4.1.7", status_code=404)
        requests_mock.get(
            f"{self._TAGS}v4.1.7",
            json={
                "tag_name": "v4.1.7",
                "assets": [
                    {
                        "name": "PSAppDeployToolkit_Template_v4_v4.1.7.zip",
                        "browser_download_url": "https://github.com/test/download.zip",
                    }
                ],
            },
        )
        requests_mock.get("https://github.com/test/download.zip", content=zip_bytes)

        result = get_psadt_release("4.1.7", tmp_path / "cache")

        assert result == tmp_path / "cache" / "4.1.7"

    def test_release_spec_with_a_v_prefix_is_normalized(self, tmp_path):
        """Tests that psadt.release 'v4.1.7' uses the cache entry for 4.1.7."""
        version_dir = self._cache_toolkit(tmp_path / "cache")

        assert get_psadt_release("v4.1.7", tmp_path / "cache") == version_dir

    def test_release_without_a_template_archive_is_refused_before_download(
        self, tmp_path, requests_mock
    ):
        """Tests that no download happens when the release has no Template_v4 zip."""
        requests_mock.get(
            f"{self._TAGS}4.1.7",
            json={
                "tag_name": "4.1.7",
                "assets": [
                    {
                        "name": "PSAppDeployToolkit_4.1.7.zip",
                        "browser_download_url": "https://github.com/test/other.zip",
                    }
                ],
            },
        )
        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="Template_v4"):
            get_psadt_release("4.1.7", tmp_path / "cache")
        assert all("other.zip" not in r.url for r in requests_mock.request_history)

    def test_four_part_tag_is_accepted(self, tmp_path, requests_mock):
        """Tests that a tag with four numeric parts is a version."""
        version_dir = self._cache_toolkit(tmp_path / "cache", "4.1.7.1")
        requests_mock.get(self._LATEST, json={"tag_name": "4.1.7.1"})

        assert get_psadt_release("latest", tmp_path / "cache") == version_dir

    def test_cache_entry_missing_an_entry_is_downloaded_again(
        self, tmp_path, requests_mock
    ):
        """Tests that a cache entry holding only the manifest is not accepted."""
        cache_dir = tmp_path / "cache"
        manifest = (
            cache_dir / "4.1.7" / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1"
        )
        manifest.parent.mkdir(parents=True)
        manifest.write_text("# manifest")
        self._serve_release(requests_mock, self._psadt_zip())

        result = get_psadt_release("4.1.7", cache_dir)

        assert (result / "Invoke-AppDeployToolkit.exe").exists()
        assert requests_mock.called

    def test_release_with_path_segments_is_rejected(self, tmp_path):
        """Tests that a psadt.release value cannot point outside the cache."""
        from napt.exceptions import ConfigError

        with pytest.raises(ConfigError, match="Invalid psadt.release"):
            get_psadt_release("../../outside", tmp_path / "cache")

    def test_get_release_download_and_extract(self, tmp_path, requests_mock):
        """Test downloading and extracting a release."""
        cache_dir = tmp_path / "cache"
        self._serve_release(requests_mock, self._psadt_zip())

        result = get_psadt_release("4.1.7", cache_dir)

        assert result == cache_dir / "4.1.7"
        assert (result / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").exists()
        assert (result / "Invoke-AppDeployToolkit.exe").exists()
        assert (result / "Files").is_dir()

    def test_get_release_no_assets(self, tmp_path, requests_mock):
        """Test handling of release with no assets."""
        cache_dir = tmp_path / "cache"

        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/tags/4.1.7",
            json={"tag_name": "4.1.7", "assets": []},
        )

        with pytest.raises(NetworkError, match="Template_v4"):
            get_psadt_release("4.1.7", cache_dir)

    def test_get_release_api_404(self, tmp_path, requests_mock):
        """Test handling of a version no tag spelling names."""
        cache_dir = tmp_path / "cache"
        requests_mock.get(f"{self._TAGS}9.9.9", status_code=404)
        requests_mock.get(f"{self._TAGS}v9.9.9", status_code=404)

        with pytest.raises(NetworkError, match="tagged 9.9.9 or v9.9.9"):
            get_psadt_release("9.9.9", cache_dir)

    def test_non_json_release_response_is_a_network_error(
        self, tmp_path, requests_mock
    ):
        """Tests that a 200 that is not JSON is reported, not a traceback."""
        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/tags/4.1.7",
            text="<html>maintenance</html>",
        )

        from napt.exceptions import NetworkError

        with pytest.raises(NetworkError, match="Invalid JSON"):
            get_psadt_release("4.1.7", tmp_path / "cache")

    def _serve_release(
        self,
        requests_mock,
        zip_bytes: bytes,
        *,
        size: int | None = None,
        digest: str | None = None,
    ) -> None:
        """Mocks the release lookup and the zip download.

        Args:
            requests_mock: The requests_mock fixture.
            zip_bytes: What the download serves.
            size: The asset size the API reports, when given.
            digest: The asset digest the API reports, when given.
        """
        asset = {
            "name": "PSAppDeployToolkit_Template_v4_v4.1.7.zip",
            "browser_download_url": "https://github.com/test/download.zip",
        }
        if size is not None:
            asset["size"] = size
        if digest is not None:
            asset["digest"] = digest
        requests_mock.get(
            "https://api.github.com/repos/PSAppDeployToolkit/PSAppDeployToolkit/releases/tags/4.1.7",
            json={"tag_name": "4.1.7", "assets": [asset]},
        )
        requests_mock.get("https://github.com/test/download.zip", content=zip_bytes)

    @staticmethod
    def _psadt_zip(*names: str) -> bytes:
        """Builds a Template_v4-shaped archive, or one holding only names."""
        import io
        import zipfile

        entries = names or (
            "PSAppDeployToolkit/PSAppDeployToolkit.psd1",
            "Invoke-AppDeployToolkit.ps1",
            "Invoke-AppDeployToolkit.exe",
            "Files/",
            "Assets/",
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            for name in entries:
                zf.writestr(name, "" if name.endswith("/") else f"# {name}")
        return buffer.getvalue()

    def test_download_matching_the_published_digest_passes(
        self, tmp_path, requests_mock
    ):
        """Tests that a download whose bytes hash to the release's digest is
        accepted."""
        import hashlib

        zip_bytes = self._psadt_zip()
        digest = "sha256:" + hashlib.sha256(zip_bytes).hexdigest()
        self._serve_release(
            requests_mock, zip_bytes, size=len(zip_bytes), digest=digest
        )

        result = get_psadt_release("4.1.7", tmp_path / "cache")

        assert (result / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").exists()

    def test_download_not_matching_the_published_digest_is_refused(
        self, tmp_path, requests_mock
    ):
        """Tests that a download that is not the published archive is refused
        before anything is extracted, even when its size is right."""
        from napt.exceptions import NetworkError

        zip_bytes = self._psadt_zip()
        self._serve_release(
            requests_mock,
            zip_bytes,
            size=len(zip_bytes),
            digest="sha256:" + "0" * 64,
        )

        with pytest.raises(NetworkError, match="digest"):
            get_psadt_release("4.1.7", tmp_path / "cache")

        assert not (tmp_path / "cache" / "4.1.7").exists()

    def test_download_not_matching_the_published_size_is_refused(
        self, tmp_path, requests_mock
    ):
        """Tests that, for a release without a digest, a download of the
        wrong size (a truncated one) is refused."""
        from napt.exceptions import NetworkError

        zip_bytes = self._psadt_zip()
        self._serve_release(requests_mock, zip_bytes, size=len(zip_bytes) + 1000)

        with pytest.raises(NetworkError, match="bytes"):
            get_psadt_release("4.1.7", tmp_path / "cache")

    def test_download_matching_the_published_size_passes_without_a_digest(
        self, tmp_path, requests_mock
    ):
        """Tests that a release without a digest (the 4.0 line) is checked by
        size alone."""
        zip_bytes = self._psadt_zip()
        self._serve_release(requests_mock, zip_bytes, size=len(zip_bytes))

        result = get_psadt_release("4.1.7", tmp_path / "cache")

        assert (result / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").exists()

    def test_layout_missing_what_napt_builds_from_is_reported(
        self, tmp_path, requests_mock
    ):
        """Tests that an archive without the Template_v4 entries NAPT relies
        on is refused with each missing entry named."""
        from napt.exceptions import PackagingError

        self._serve_release(
            requests_mock,
            self._psadt_zip(
                "PSAppDeployToolkit/PSAppDeployToolkit.psd1",
                "Invoke-AppDeployToolkit.ps1",
            ),
        )

        with pytest.raises(PackagingError, match="Template_v4") as info:
            get_psadt_release("4.1.7", tmp_path / "cache")

        message = str(info.value)
        assert "Invoke-AppDeployToolkit.exe" in message
        assert "Files/" in message
        assert not (tmp_path / "cache" / "4.1.7").exists()

    def test_stale_partial_cache_entry_is_replaced(self, tmp_path, requests_mock):
        """Tests that a folder left by an older NAPT with no manifest is
        replaced by the verified toolkit, not merged into."""
        cache_dir = tmp_path / "cache"
        stale = cache_dir / "4.1.7"
        stale.mkdir(parents=True)
        (stale / "psadt_4.1.7.zip").write_bytes(b"leftover")
        self._serve_release(requests_mock, self._psadt_zip())

        result = get_psadt_release("4.1.7", cache_dir)

        assert result == stale
        assert not (stale / "psadt_4.1.7.zip").exists()
        assert (stale / "PSAppDeployToolkit" / "PSAppDeployToolkit.psd1").exists()

    def test_cache_write_failure_is_a_packaging_error(self, tmp_path, requests_mock):
        """Tests that a cache the file system refuses to write is reported by
        path, not as an OSError traceback."""
        import shutil

        from napt.exceptions import PackagingError

        cache_dir = tmp_path / "cache"
        (cache_dir / "4.1.7").mkdir(parents=True)
        self._serve_release(requests_mock, self._psadt_zip())
        real_rmtree = shutil.rmtree

        def refuse_the_entry(path, *args, **kwargs):
            if Path(path) == cache_dir / "4.1.7":
                raise OSError(13, "Permission denied")
            return real_rmtree(path, *args, **kwargs)

        with patch("napt.psadt.release.shutil.rmtree", side_effect=refuse_the_entry):
            with pytest.raises(PackagingError, match="Permission denied"):
                get_psadt_release("4.1.7", cache_dir)

    def test_stale_work_folders_are_removed(self, tmp_path):
        """Tests that a work folder left by a hard-killed run is removed once
        it is old enough, while a fresh one from a running download stays."""
        import os
        import time

        cache_dir = tmp_path / "cache"
        cached = cache_dir / "4.1.7" / "PSAppDeployToolkit"
        cached.mkdir(parents=True)
        (cached / "PSAppDeployToolkit.psd1").write_text("# manifest")
        stale = cache_dir / ".4.1.7-abc123"
        stale.mkdir()
        (stale / "psadt_4.1.7.zip").write_bytes(b"half")
        two_days_ago = time.time() - 2 * 24 * 3600
        os.utime(stale, (two_days_ago, two_days_ago))
        fresh = cache_dir / ".4.1.8-def456"
        fresh.mkdir()

        get_psadt_release("4.1.7", cache_dir)

        assert not stale.exists()
        assert fresh.exists()

    def test_stale_work_folder_that_cannot_be_removed_is_skipped(self, tmp_path):
        """Tests that a leftover the file system refuses to remove does not
        stop the run from using the cached toolkit."""
        import os
        import time

        cache_dir = tmp_path / "cache"
        _cache_toolkit(cache_dir)
        stale = cache_dir / ".4.1.7-abc123"
        stale.mkdir()
        two_days_ago = time.time() - 2 * 24 * 3600
        os.utime(stale, (two_days_ago, two_days_ago))

        with patch(
            "napt.psadt.release.shutil.rmtree",
            side_effect=OSError(13, "Permission denied"),
        ):
            result = get_psadt_release("4.1.7", cache_dir)

        assert result == cache_dir / "4.1.7"

    def test_cache_holds_only_the_extracted_toolkit(self, tmp_path, requests_mock):
        """Tests that neither the downloaded zip nor a working folder is left
        in the cache, since build copies everything in the version folder."""
        cache_dir = tmp_path / "cache"
        self._serve_release(requests_mock, self._psadt_zip())

        result = get_psadt_release("4.1.7", cache_dir)

        assert sorted(p.name for p in cache_dir.iterdir()) == ["4.1.7"]
        assert sorted(p.name for p in result.iterdir()) == [
            "Assets",
            "Files",
            "Invoke-AppDeployToolkit.exe",
            "Invoke-AppDeployToolkit.ps1",
            "PSAppDeployToolkit",
        ]

    def test_interrupted_extraction_leaves_no_cache_entry(
        self, tmp_path, requests_mock
    ):
        """Tests that an extraction that dies after the manifest file is
        written is not accepted as a cached toolkit by the next run."""
        import zipfile

        from napt.exceptions import PackagingError

        cache_dir = tmp_path / "cache"
        self._serve_release(requests_mock, self._psadt_zip())

        def die_after_the_manifest(path, *args, **kwargs):
            target = Path(path) / "PSAppDeployToolkit"
            target.mkdir(parents=True, exist_ok=True)
            (target / "PSAppDeployToolkit.psd1").write_text("partial")
            raise zipfile.BadZipFile("truncated")

        with patch.object(
            zipfile.ZipFile, "extractall", side_effect=die_after_the_manifest
        ):
            with pytest.raises(PackagingError):
                get_psadt_release("4.1.7", cache_dir)

        assert not (cache_dir / "4.1.7").exists()
        assert not is_psadt_cached("4.1.7", cache_dir)
        assert not list(cache_dir.glob("**/*.zip"))

    def test_extracted_archive_without_the_toolkit_is_not_cached(
        self, tmp_path, requests_mock
    ):
        """Tests that an archive missing the toolkit folder never becomes a
        cache entry the next run would trust."""
        import io
        import zipfile

        from napt.exceptions import PackagingError

        cache_dir = tmp_path / "cache"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("README.md", "not a toolkit")
        self._serve_release(requests_mock, buffer.getvalue())

        with pytest.raises(PackagingError, match="Template_v4"):
            get_psadt_release("4.1.7", cache_dir)

        assert not (cache_dir / "4.1.7").exists()
