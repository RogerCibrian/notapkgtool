"""Tests for napt.discovery: strategy registry, strategies, url_download flow."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest
import requests_mock

from napt.discovery.api_github import ApiGithubStrategy
from napt.discovery.api_json import ApiJsonStrategy
from napt.discovery.base import RemoteVersion
from napt.discovery.registry import get_strategy
from napt.discovery.url_download import run_url_download
from napt.discovery.web_scrape import WebScrapeStrategy
from napt.exceptions import ConfigError, NetworkError, PackagingError
from napt.versioning.msi import MSIMetadata
from napt.versioning.msix import MSIXMetadata


class TestStrategyRegistry:
    """Tests for discovery strategy registry lookup."""

    def test_get_api_github_strategy(self):
        """Tests that api_github strategy can be retrieved from the registry."""
        strategy = get_strategy("api_github")
        assert isinstance(strategy, ApiGithubStrategy)

    def test_get_unknown_strategy_raises(self):
        """Tests that an unregistered strategy name raises ConfigError."""
        with pytest.raises(ConfigError, match="Unknown discovery strategy") as exc:
            get_strategy("urldownload")
        # The hint names every strategy a recipe can use, not only the
        # registered ones.
        assert "url_download" in str(exc.value)
        with pytest.raises(ConfigError, match="Unknown discovery strategy"):
            get_strategy("nonexistent_strategy")

    def test_url_download_not_in_registry(self):
        """Tests that url_download is intentionally not a registered strategy."""
        with pytest.raises(ConfigError, match="Unknown discovery strategy"):
            get_strategy("url_download")

    def test_get_api_json_strategy(self):
        """Tests that api_json strategy can be retrieved from the registry."""
        strategy = get_strategy("api_json")
        assert isinstance(strategy, ApiJsonStrategy)

    def test_get_web_scrape_strategy(self):
        """Tests that web_scrape strategy can be retrieved from the registry."""
        strategy = get_strategy("web_scrape")
        assert isinstance(strategy, WebScrapeStrategy)


class TestUrlDownloadFlow:
    """Tests for the url_download flow (run_url_download)."""

    def test_discovers_version_from_msi(self, tmp_test_dir):
        """Tests that the version is extracted from a freshly downloaded MSI."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/installer.msi"},
        }
        fake_msi_content = b"fake MSI content"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_msi_content,
                headers={"Content-Length": str(len(fake_msi_content))},
            )
            with patch("napt.discovery.resolve.extract_msi_metadata") as mock_extract:
                mock_extract.return_value = MSIMetadata(
                    product_name="", product_version="1.2.3", architecture="x64"
                )
                result = run_url_download(app_config, tmp_test_dir)

        assert result.version == "1.2.3"
        assert result.version_source == "msi"
        app_dir = tmp_test_dir / "test-app"
        assert result.file_path == app_dir / "1.2.3" / "installer.msi"
        assert result.file_path.exists()
        assert not [p for p in app_dir.iterdir() if p.name.startswith(".incoming")]
        assert len(result.sha256) == 64
        assert result.cached is False
        assert result.download_url == "https://example.com/installer.msi"

    def test_new_version_under_same_filename_keeps_the_old_installer(
        self, tmp_test_dir
    ):
        """Tests that a vendor reusing one filename cannot overwrite a release."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/installer.msi"},
        }
        downloads = [(b"version one", "1.0.0"), (b"version two!", "2.0.0")]

        for content, version in downloads:
            with requests_mock.Mocker() as m:
                m.get(
                    "https://example.com/installer.msi",
                    content=content,
                    headers={"Content-Length": str(len(content))},
                )
                with patch(
                    "napt.discovery.resolve.extract_msi_metadata"
                ) as mock_extract:
                    mock_extract.return_value = MSIMetadata(
                        product_name="", product_version=version, architecture="x64"
                    )
                    run_url_download(app_config, tmp_test_dir)

        app_dir = tmp_test_dir / "test-app"
        assert (app_dir / "1.0.0" / "installer.msi").read_bytes() == b"version one"
        assert (app_dir / "2.0.0" / "installer.msi").read_bytes() == b"version two!"

    def test_unusable_msi_version_is_refused_and_leaves_nothing_behind(
        self, tmp_test_dir
    ):
        """Tests that a traversing ProductVersion creates no folder."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/installer.msi"},
        }
        content = b"fake MSI content"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=content,
                headers={"Content-Length": str(len(content))},
            )
            with patch("napt.discovery.resolve.extract_msi_metadata") as mock_extract:
                mock_extract.return_value = MSIMetadata(
                    product_name="", product_version="../../evil", architecture="x64"
                )
                with pytest.raises(ConfigError, match="cannot be used as a folder"):
                    run_url_download(app_config, tmp_test_dir)

        assert not (tmp_test_dir / "evil").exists()
        assert list((tmp_test_dir / "test-app").iterdir()) == []

    def test_missing_url_raises(self, tmp_test_dir):
        """Tests that a missing discovery.url raises ConfigError."""
        with pytest.raises(ConfigError, match="requires 'discovery.url'"):
            run_url_download({"discovery": {}}, tmp_test_dir)

    def test_download_failure_raises(self, tmp_test_dir):
        """Tests that a non-2xx download response raises NetworkError."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/installer.msi"},
        }
        with requests_mock.Mocker() as m:
            m.get("https://example.com/installer.msi", status_code=404)
            with pytest.raises(NetworkError, match="download failed"):
                run_url_download(app_config, tmp_test_dir)

    def test_unexpected_error_is_reported_as_network_error(self, tmp_test_dir):
        """Tests that a failure outside HTTP still surfaces as NetworkError."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/installer.msi"},
        }
        with patch("napt.discovery.resolve.download_file") as mock_download:
            mock_download.side_effect = OSError("disk full")
            with pytest.raises(NetworkError, match="Failed to download"):
                run_url_download(app_config, tmp_test_dir)

    @pytest.mark.parametrize(
        ("raised", "expected", "fragment"),
        [
            # The installer's own problems keep their own type and message.
            (ConfigError("Unknown platform 'Itanium'"), ConfigError, "Itanium"),
            (PackagingError("Template is empty"), PackagingError, "Template"),
            # Missing tooling and anything unexpected are packaging failures,
            # not network ones: the download itself succeeded.
            (NotImplementedError("msitools"), PackagingError, "msitools"),
            (RuntimeError("boom"), PackagingError, "Failed to extract"),
        ],
    )
    def test_extraction_failure_keeps_its_meaning(
        self, tmp_test_dir, raised, expected, fragment
    ):
        """Tests that a metadata error is not relabelled as a download error."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/installer.msi"},
        }
        fake_content = b"not a real MSI"
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_content,
                headers={"Content-Length": str(len(fake_content))},
            )
            with patch("napt.discovery.resolve.extract_msi_metadata") as mock_extract:
                mock_extract.side_effect = raised
                with pytest.raises(expected, match=fragment):
                    run_url_download(app_config, tmp_test_dir)

    def test_discovers_version_from_msix(self, tmp_test_dir):
        """Tests that an MSIX's Identity version is read the same way."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/app.msix"},
        }
        with requests_mock.Mocker() as m:
            m.get("https://example.com/app.msix", content=b"x", headers={})
            with patch("napt.discovery.resolve.extract_msix_metadata") as extract:
                extract.return_value = MSIXMetadata(
                    identity_name="App",
                    version="4.41.105.0",
                    architecture="x64",
                    display_name="App",
                    publisher="CN=Vendor",
                )
                result = run_url_download(app_config, tmp_test_dir)

        assert result.version == "4.41.105.0"
        assert result.version_source == "msix"
        assert result.file_path == tmp_test_dir / "test-app" / "4.41.105.0" / "app.msix"

    def test_exe_is_refused(self, tmp_test_dir):
        """Tests that a file with no readable version is refused with guidance."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/setup.exe"},
        }
        with requests_mock.Mocker() as m:
            m.get("https://example.com/setup.exe", content=b"x", headers={})
            with pytest.raises(ConfigError, match="MSI and MSIX installers only"):
                run_url_download(app_config, tmp_test_dir)

        assert list((tmp_test_dir / "test-app").iterdir()) == []


_SIDECAR_URL = "https://example.com/installer.msi"


_CACHED_BYTES = b"fake cached msi"
_CACHED_SHA256 = hashlib.sha256(_CACHED_BYTES).hexdigest()


def _seed_previous_download(
    app_dir,
    *,
    version="1.0.0",
    filename="installer.msi",
    url=_SIDECAR_URL,
    etag='W/"abc123"',
    with_installer=True,
):
    """Writes a sidecar file and, by default, the installer it points at.

    The recorded hash is the installer's real hash, since reuse re-checks
    the file against it."""
    app_dir.mkdir(parents=True)
    if with_installer:
        installer = app_dir / version / filename
        installer.parent.mkdir(parents=True, exist_ok=True)
        installer.write_bytes(_CACHED_BYTES)
    (app_dir / ".download.json").write_text(
        json.dumps(
            {
                "url": url,
                "discovered_version": None,
                "etag": etag,
                "last_modified": None,
                "version": version,
                "filename": filename,
                "sha256": _CACHED_SHA256,
            }
        ),
        encoding="utf-8",
    )


def _run_with_msi_version(app_config, output_dir, version):
    """Runs url_download with MSI version extraction stubbed out."""
    with patch("napt.discovery.resolve.extract_msi_metadata") as mock_extract:
        mock_extract.return_value = MSIMetadata(
            product_name="", product_version=version, architecture="x64"
        )
        return run_url_download(app_config, output_dir)


class TestUrlDownloadSidecar:
    """Tests for url_download's conditional requests and sidecar file."""

    APP_CONFIG = {"id": "test-app", "discovery": {"url": _SIDECAR_URL}}

    def test_download_then_304_reuses_installer(self, tmp_test_dir):
        """Tests that a run's sidecar lets the next run reuse the installer."""
        fake_msi = b"fake MSI content"
        with requests_mock.Mocker() as m:
            m.get(
                _SIDECAR_URL,
                [
                    {
                        "content": fake_msi,
                        "headers": {
                            "Content-Length": str(len(fake_msi)),
                            "ETag": 'W/"abc123"',
                        },
                    },
                    {"status_code": 304},
                ],
            )
            first = _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "1.0.0")
            second = _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "1.0.0")
            conditional = m.request_history[1].headers.get("If-None-Match")

        assert first.cached is False
        assert conditional == 'W/"abc123"'
        assert second.cached is True
        assert second.file_path == first.file_path
        assert second.version == "1.0.0"
        assert second.sha256 == first.sha256

    def test_lowercase_etag_header_is_recorded(self, tmp_test_dir):
        """Tests that an ETag sent under a lowercase header name is kept."""
        with requests_mock.Mocker() as m:
            m.get(
                _SIDECAR_URL,
                content=b"msi",
                headers={"Content-Length": "3", "etag": '"lower"'},
            )
            _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "1.0.0")

        sidecar = json.loads(
            (tmp_test_dir / "test-app" / ".download.json").read_text(encoding="utf-8")
        )
        assert sidecar["etag"] == '"lower"'
        assert sidecar["version"] == "1.0.0"
        assert sidecar["filename"] == "installer.msi"

    def test_304_uses_recorded_filename_not_url(self, tmp_test_dir):
        """Tests that HTTP 304 reuses the recorded file, not a URL-derived name."""
        url = "https://example.com/download?token=abc"
        app_config = {"id": "test-app", "discovery": {"url": url}}
        _seed_previous_download(
            tmp_test_dir / "test-app",
            version="2.1.0",
            filename="MyApp Setup.msi",
            url=url,
        )

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download", status_code=304)
            result = _run_with_msi_version(app_config, tmp_test_dir, "unused")

        expected = tmp_test_dir / "test-app" / "2.1.0" / "MyApp Setup.msi"
        assert result.file_path == expected
        assert result.version == "2.1.0"
        assert result.sha256 == _CACHED_SHA256
        assert result.cached is True

    def test_changed_file_gets_its_own_version_folder(self, tmp_test_dir):
        """Tests that a vendor rollback is filed under the version it carries."""
        app_dir = tmp_test_dir / "test-app"
        _seed_previous_download(app_dir, version="2.0.0")
        older_msi = b"the older release"

        with requests_mock.Mocker() as m:
            m.get(
                _SIDECAR_URL,
                content=older_msi,
                headers={"Content-Length": str(len(older_msi)), "ETag": '"rolled"'},
            )
            result = _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "1.9.0")

        assert result.version == "1.9.0"
        assert result.cached is False
        assert result.file_path == app_dir / "1.9.0" / "installer.msi"
        assert result.file_path.read_bytes() == older_msi
        assert (app_dir / "2.0.0" / "installer.msi").read_bytes() == b"fake cached msi"
        sidecar = json.loads((app_dir / ".download.json").read_text(encoding="utf-8"))
        assert sidecar["version"] == "1.9.0"
        assert sidecar["etag"] == '"rolled"'

    @pytest.mark.parametrize(
        "seed",
        [
            pytest.param({"with_installer": False}, id="installer-missing"),
            pytest.param({"url": "https://example.com/old.msi"}, id="url-changed"),
            pytest.param({"etag": None}, id="no-validators"),
            pytest.param({"version": "../escape"}, id="unsafe-version"),
            pytest.param({"filename": "a/b.msi"}, id="unsafe-filename"),
        ],
    )
    def test_unusable_sidecar_downloads_unconditionally(self, tmp_test_dir, seed):
        """Tests that a sidecar that cannot be honored sends no conditions."""
        app_dir = tmp_test_dir / "test-app"
        _seed_previous_download(app_dir, **seed)

        with requests_mock.Mocker() as m:
            m.get(_SIDECAR_URL, content=b"msi", headers={"Content-Length": "3"})
            result = _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "1.0.0")
            sent = m.last_request.headers

        assert "If-None-Match" not in sent
        assert "If-Modified-Since" not in sent
        assert result.cached is False
        assert result.file_path.read_bytes() == b"msi"

    @pytest.mark.parametrize("content", ["not json", "[]", '{"url": 1}'])
    def test_corrupt_sidecar_is_treated_as_missing(self, tmp_test_dir, content):
        """Tests that an unreadable sidecar costs a download, not an error."""
        app_dir = tmp_test_dir / "test-app"
        app_dir.mkdir()
        (app_dir / ".download.json").write_text(content, encoding="utf-8")

        with requests_mock.Mocker() as m:
            m.get(_SIDECAR_URL, content=b"msi", headers={"Content-Length": "3"})
            result = _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "1.0.0")

        assert result.cached is False
        assert result.version == "1.0.0"

    def test_unwritable_sidecar_warns_and_keeps_the_download(
        self, tmp_test_dir, capsys
    ):
        """Tests that a sidecar write failure does not fail the discovery."""
        # A directory where the sidecar file belongs makes the write fail.
        (tmp_test_dir / "test-app" / ".download.json").mkdir(parents=True)

        with requests_mock.Mocker() as m:
            m.get(_SIDECAR_URL, content=b"msi", headers={"Content-Length": "3"})
            result = _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "1.0.0")

        assert result.cached is False
        assert result.file_path.read_bytes() == b"msi"
        assert "Could not write" in capsys.readouterr().out

    def test_failed_sidecar_write_leaves_the_old_sidecar_intact(
        self, tmp_test_dir, capsys
    ):
        """Tests that a sidecar write that fails before the rename keeps the
        previous sidecar unchanged instead of leaving a truncated one."""
        import os
        from pathlib import Path
        from unittest.mock import patch

        app_dir = tmp_test_dir / "test-app"
        _seed_previous_download(app_dir)
        before = (app_dir / ".download.json").read_text(encoding="utf-8")
        real_replace = os.replace

        def _replace(src, dst):
            # Only the sidecar's rename fails; the installer's own
            # .part rename must still succeed.
            if Path(dst).name == ".download.json":
                raise OSError(28, "No space")
            return real_replace(src, dst)

        with requests_mock.Mocker() as m:
            m.get(_SIDECAR_URL, content=b"msi", headers={"Content-Length": "3"})
            with patch("napt.files.os.replace", side_effect=_replace):
                result = _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "2.0.0")

        assert result.file_path.read_bytes() == b"msi"
        assert (app_dir / ".download.json").read_text(encoding="utf-8") == before
        assert [p.name for p in app_dir.iterdir() if p.is_file()] == [".download.json"]
        assert "Could not write" in capsys.readouterr().out

    def test_failed_download_leaves_sidecar_untouched(self, tmp_test_dir):
        """Tests that the sidecar is only rewritten after a finished download."""
        app_dir = tmp_test_dir / "test-app"
        _seed_previous_download(app_dir)
        before = (app_dir / ".download.json").read_text(encoding="utf-8")

        with requests_mock.Mocker() as m:
            m.get(_SIDECAR_URL, content=b"msi", headers={"Content-Length": "3"})
            with pytest.raises(ConfigError, match="cannot be used as a folder name"):
                _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, "../bad")

        assert (app_dir / ".download.json").read_text(encoding="utf-8") == before

    @pytest.mark.parametrize(
        ("version", "hint"),
        [
            ("v2.0", "captures only '2.0'"),
            ("release-2.0", "captures only '2.0'"),
            ("latest", "version_path or version_pattern"),
        ],
    )
    def test_version_without_leading_digit_is_refused(
        self, tmp_test_dir, version, hint
    ):
        """Tests that a version a device would read as 0 stops discovery."""
        app_dir = tmp_test_dir / "test-app"

        with requests_mock.Mocker() as m:
            m.get(_SIDECAR_URL, content=b"msi", headers={"Content-Length": "3"})
            with pytest.raises(ConfigError, match="does not start with a number"):
                try:
                    _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, version)
                except ConfigError as err:
                    assert hint in str(err)
                    raise

        assert list(app_dir.iterdir()) == []

    @pytest.mark.parametrize(
        "version",
        ["1.9999999999999999999", "9999999999999999999", "1.0.1234567890123456789"],
    )
    def test_version_segment_past_int64_is_refused(self, tmp_test_dir, version):
        """Tests that a segment a device cannot cast to Int64 stops
        discovery, since its detection script would throw on it."""
        app_dir = tmp_test_dir / "test-app"

        with requests_mock.Mocker() as m:
            m.get(_SIDECAR_URL, content=b"msi", headers={"Content-Length": "3"})
            with pytest.raises(ConfigError, match="more than 18 digits"):
                _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, version)

        assert list(app_dir.iterdir()) == []

    @pytest.mark.parametrize(
        "version", ["2.0", "2024.10.15-hotfix2", "01.02", "1.123456789012345678"]
    )
    def test_version_with_leading_digit_is_accepted(self, tmp_test_dir, version):
        """Tests that a version starting with a digit passes, whatever follows."""
        with requests_mock.Mocker() as m:
            m.get(_SIDECAR_URL, content=b"msi", headers={"Content-Length": "3"})
            result = _run_with_msi_version(self.APP_CONFIG, tmp_test_dir, version)

        assert result.version == version

    def test_no_cache_works(self, tmp_test_dir):
        """Tests that url_download works with no earlier download on disk."""
        app_config = {
            "id": "test-app",
            "discovery": {"url": "https://example.com/installer.msi"},
        }
        fake_msi = b"fake MSI no cache"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/installer.msi",
                content=fake_msi,
                headers={"Content-Length": str(len(fake_msi))},
            )
            with patch("napt.discovery.resolve.extract_msi_metadata") as mock_extract:
                mock_extract.return_value = MSIMetadata(
                    product_name="", product_version="1.0.0", architecture="x64"
                )
                result = run_url_download(app_config, tmp_test_dir)

        assert result.version == "1.0.0"
        assert result.file_path == tmp_test_dir / "test-app" / "1.0.0" / "installer.msi"
        assert result.file_path.exists()


class TestVersionFirstStrategies:
    """Tests for version-first strategies (web_scrape, api_github, api_json)."""

    def test_web_scrape_with_css_selector(self):
        """Test web_scrape.discover() with CSS selector."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/download.html",
                "link_selector": 'a[href$="-x64.msi"]',
                "version_pattern": r"7z(\d{2})(\d{2})-x64",
                "version_format": "{0}.{1}",
            }
        }

        # Mock HTML page
        html_content = """
        <html>
            <body>
                <div class="downloads">
                    <a href="/a/7z2501-x64.msi">Download 64-bit</a>
                    <a href="/a/7z2501.msi">Download 32-bit</a>
                </div>
            </body>
        </html>
        """

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)

            version_info = strategy.discover(app_config)

        assert isinstance(version_info, RemoteVersion)
        assert version_info.version == "25.01"
        assert version_info.download_url == "https://example.com/a/7z2501-x64.msi"
        assert version_info.source == "web_scrape"

    def test_web_scrape_with_regex_pattern(self):
        """Test web_scrape.discover() with regex fallback."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/download.html",
                "link_pattern": r'href="(/files/app-v[0-9.]+-installer\.msi)"',
                "version_pattern": r"app-v([0-9.]+)-installer",
            }
        }

        html_content = '<a href="/files/app-v1.2.3-installer.msi">Download</a>'

        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html_content)

            version_info = strategy.discover(app_config)

        assert isinstance(version_info, RemoteVersion)
        assert version_info.version == "1.2.3"
        assert (
            version_info.download_url
            == "https://example.com/files/app-v1.2.3-installer.msi"
        )
        assert version_info.source == "web_scrape"

    def test_api_github_discover(self):
        """Test api_github.discover() returns RemoteVersion without
        downloading."""
        strategy = ApiGithubStrategy()
        app_config = {
            "discovery": {
                "repo": "owner/repo",
                "asset_pattern": r".*\.msi$",
                "version_pattern": r"v?([0-9.]+)",
            }
        }

        release_data = {
            "tag_name": "v1.2.3",
            "prerelease": False,
            "assets": [
                {
                    "name": "installer.msi",
                    "browser_download_url": "https://github.com/owner/repo/releases/download/v1.2.3/installer.msi",
                }
            ],
        }

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )

            version_info = strategy.discover(app_config)

        assert isinstance(version_info, RemoteVersion)
        assert version_info.version == "1.2.3"
        assert "github.com" in version_info.download_url
        assert version_info.source == "api_github"

    def test_api_json_discover(self):
        """Test api_json.discover() returns RemoteVersion without downloading."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
            }
        }

        api_response = {
            "version": "1.2.3",
            "download_url": "https://example.com/installer.msi",
        }

        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/latest", json=api_response)

            version_info = strategy.discover(app_config)

        assert isinstance(version_info, RemoteVersion)
        assert version_info.version == "1.2.3"
        assert version_info.download_url == "https://example.com/installer.msi"
        assert version_info.source == "api_json"


# =============================================================================
# WebScrapeStrategy — error cases and validate_config
# =============================================================================


class TestWebScrapeStrategyErrors:
    """Tests error handling in WebScrapeStrategy.discover()."""

    def test_missing_page_url_raises(self):
        """Tests that missing page_url raises ConfigError."""
        strategy = WebScrapeStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.page_url'"):
            strategy.discover(
                {"discovery": {"link_selector": "a", "version_pattern": "."}}
            )

    def test_missing_link_finding_method_raises(self):
        """Tests that omitting link_selector and link_pattern raises ConfigError."""
        strategy = WebScrapeStrategy()
        with pytest.raises(ConfigError, match="link_selector.*link_pattern"):
            strategy.discover(
                {
                    "discovery": {
                        "page_url": "https://example.com",
                        "version_pattern": r"(\d+)",
                    }
                }
            )

    def test_missing_version_pattern_raises(self):
        """Tests that missing version_pattern raises ConfigError."""
        strategy = WebScrapeStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.version_pattern'"):
            strategy.discover(
                {
                    "discovery": {
                        "page_url": "https://example.com",
                        "link_selector": "a",
                    }
                }
            )

    def test_page_fetch_failure_raises(self):
        """Tests that a non-2xx page response raises NetworkError."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": "a",
                "version_pattern": r"(\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get("https://example.com/dl.html", status_code=503)
            with pytest.raises(NetworkError, match="Failed to fetch page"):
                strategy.discover(app_config)

    def test_css_selector_not_found_raises(self):
        """Tests that a CSS selector matching nothing raises ConfigError."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": 'a[href$=".msi"]',
                "version_pattern": r"(\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/dl.html",
                text="<html><body>no links here</body></html>",
            )
            with pytest.raises(ConfigError, match="did not match any elements"):
                strategy.discover(app_config)

    def test_regex_link_pattern_not_found_raises(self):
        """Tests that a regex link_pattern matching nothing raises ConfigError."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_pattern": r'href="(/files/nomatch\.msi)"',
                "version_pattern": r"(\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/dl.html", text="<html><body>nothing</body></html>"
            )
            with pytest.raises(ConfigError, match="did not match anything"):
                strategy.discover(app_config)

    def test_unmatched_optional_link_group_is_no_match(self):
        """Tests that a link_pattern group that took no part in the match
        is reported as no match instead of joining None onto the page URL."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_pattern": r"(/files/[^\"]+)?download",
                "version_pattern": r"(\d+\.\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get("https://example.com/dl.html", text="<a>download</a>")
            with pytest.raises(ConfigError, match="did not match anything on page"):
                strategy.discover(app_config)

    def test_unmatched_optional_version_group_is_no_match(self):
        """Tests that a version_pattern group that took no part in the match
        is reported as no match instead of formatting the text None."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": "a",
                "version_pattern": r"installer(-(\d+))?",
            }
        }
        with requests_mock.Mocker() as m:
            m.get("https://example.com/dl.html", text='<a href="/installer.exe">x</a>')
            with pytest.raises(ConfigError, match="did not match"):
                strategy.discover(app_config)

    def test_version_pattern_no_match_raises(self):
        """Tests that a version_pattern not matching the URL raises ConfigError."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": "a",
                "version_pattern": r"no_match_here(\d+)",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/dl.html",
                text='<a href="/files/installer.msi">Download</a>',
            )
            with pytest.raises(ConfigError, match="did not match"):
                strategy.discover(app_config)

    def test_version_format_with_multiple_groups(self):
        """Tests that version_format combines multiple capture groups correctly."""
        strategy = WebScrapeStrategy()
        app_config = {
            "discovery": {
                "page_url": "https://example.com/dl.html",
                "link_selector": "a",
                "version_pattern": r"v(\d+)\.(\d+)\.(\d+)",
                "version_format": "{0}.{1}.{2}",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/dl.html",
                text='<a href="/app-v3.14.1-x64.msi">Download</a>',
            )
            version_info = strategy.discover(app_config)
        assert version_info.version == "3.14.1"
        assert version_info.source == "web_scrape"


class TestWebScrapeValidateConfig:
    """Tests for WebScrapeStrategy.validate_config()."""

    def test_valid_config_returns_empty(self):
        """Tests that a fully valid config returns no errors."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "page_url": "https://example.com",
                    "link_selector": "a",
                    "version_pattern": r"v([0-9.]+)",
                }
            }
        )
        assert errors == []

    def test_missing_page_url(self):
        """Tests that missing page_url is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {"discovery": {"link_selector": "a", "version_pattern": "."}}
        )
        assert any("page_url" in e for e in errors)

    def test_missing_link_methods(self):
        """Tests that missing both link fields is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "page_url": "https://example.com",
                    "version_pattern": ".",
                }
            }
        )
        assert any("link_selector" in e or "link_pattern" in e for e in errors)

    def test_missing_version_pattern(self):
        """Tests that missing version_pattern is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {"discovery": {"page_url": "https://example.com", "link_selector": "a"}}
        )
        assert any("version_pattern" in e for e in errors)

    def test_invalid_version_pattern_regex(self):
        """Tests that an invalid version_pattern regex is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "page_url": "https://example.com",
                    "link_selector": "a",
                    "version_pattern": "[unclosed",
                }
            }
        )
        assert any("regex" in e.lower() or "Invalid" in e for e in errors)

    def test_invalid_link_pattern_regex(self):
        """Tests that an invalid link_pattern regex is reported."""
        strategy = WebScrapeStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "page_url": "https://example.com",
                    "link_pattern": "[unclosed",
                    "version_pattern": r"(\d+)",
                }
            }
        )
        assert any("regex" in e.lower() or "Invalid" in e for e in errors)


# =============================================================================
# ApiGithubStrategy: error cases and validate_config
# =============================================================================


class TestApiGithubStrategyErrors:
    """Tests error handling in ApiGithubStrategy.discover()."""

    def test_missing_repo_raises(self):
        """Tests that missing repo raises ConfigError."""
        strategy = ApiGithubStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.repo'"):
            strategy.discover({"discovery": {"asset_pattern": ".*"}})

    def test_invalid_repo_format_raises(self):
        """Tests that repo without slash raises ConfigError."""
        strategy = ApiGithubStrategy()
        with pytest.raises(ConfigError, match="Invalid repo format"):
            strategy.discover({"discovery": {"repo": "noslash", "asset_pattern": ".*"}})

    def test_missing_asset_pattern_raises(self):
        """Tests that missing asset_pattern raises ConfigError."""
        strategy = ApiGithubStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.asset_pattern'"):
            strategy.discover({"discovery": {"repo": "owner/repo"}})

    def test_repo_not_found_raises(self):
        """Tests that a 404 API response raises NetworkError."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": ".*"}}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                status_code=404,
            )
            with pytest.raises(NetworkError, match="not found"):
                strategy.discover(app_config)

    def test_non_json_response_raises(self):
        """Tests that a 200 that is not JSON is a NetworkError, not a
        traceback."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": ".*"}}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                text="<html>maintenance</html>",
            )
            with pytest.raises(NetworkError, match="Invalid JSON"):
                strategy.discover(app_config)

    def test_json_that_is_not_an_object_raises(self):
        """Tests that a JSON body of the wrong shape is a NetworkError."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": ".*"}}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=["unexpected"],
            )
            with pytest.raises(NetworkError, match="Unexpected GitHub API response"):
                strategy.discover(app_config)

    def test_unmatched_optional_group_is_no_match(self):
        """Tests that a capture group that took no part in the match is
        reported as the pattern not matching, not as version None."""
        strategy = ApiGithubStrategy()
        app_config = {
            "discovery": {
                "repo": "owner/repo",
                "asset_pattern": ".*",
                "version_pattern": r"release-?(\d+)?",
            }
        }
        release_data = {
            "tag_name": "release",
            "prerelease": False,
            "assets": [{"name": "a.msi", "browser_download_url": "https://x/a.msi"}],
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )
            with pytest.raises(ConfigError, match="did not match"):
                strategy.discover(app_config)

    def test_rate_limited_raises(self):
        """Tests that a 403 with the limit exhausted names the rate limit."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": ".*"}}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                status_code=403,
                headers={"X-RateLimit-Remaining": "0"},
            )
            with pytest.raises(NetworkError, match="rate limit"):
                strategy.discover(app_config)

    def test_forbidden_for_another_reason_is_not_called_a_rate_limit(self):
        """Tests that a 403 with requests remaining is reported as a refusal."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": ".*"}}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                status_code=403,
                reason="Forbidden",
                headers={"X-RateLimit-Remaining": "42"},
            )
            with pytest.raises(NetworkError, match="403") as info:
                strategy.discover(app_config)
        assert "rate limit" not in str(info.value)

    def test_no_assets_raises(self):
        """Tests that a release with no assets raises NetworkError."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": r".*\.msi$"}}
        release_data = {"tag_name": "v1.0.0", "prerelease": False, "assets": []}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )
            with pytest.raises(NetworkError, match="has no assets"):
                strategy.discover(app_config)

    def test_no_matching_asset_raises(self):
        """Tests that no asset matching the pattern raises ConfigError."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": r".*\.msi$"}}
        release_data = {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "assets": [
                {
                    "name": "installer.exe",
                    "browser_download_url": "https://example.com/installer.exe",
                }
            ],
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )
            with pytest.raises(ConfigError, match="No assets matched"):
                strategy.discover(app_config)


class TestApiGithubValidateConfig:
    """Tests for ApiGithubStrategy.validate_config()."""

    def test_valid_config_returns_empty(self):
        """Tests that a fully valid config returns no errors."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config(
            {"discovery": {"repo": "owner/repo", "asset_pattern": r".*\.msi$"}}
        )
        assert errors == []

    def test_missing_repo(self):
        """Tests that missing repo is reported."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config({"discovery": {"asset_pattern": r".*\.msi$"}})
        assert any("repo" in e for e in errors)

    def test_invalid_repo_format(self):
        """Tests that repo without slash is reported."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config(
            {"discovery": {"repo": "noslash", "asset_pattern": r".*\.msi$"}}
        )
        assert any("owner/repo" in e for e in errors)

    def test_missing_asset_pattern(self):
        """Tests that missing asset_pattern is reported."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config({"discovery": {"repo": "owner/repo"}})
        assert any("asset_pattern" in e for e in errors)

    def test_invalid_version_pattern_regex(self):
        """Tests that an invalid version_pattern regex is reported."""
        strategy = ApiGithubStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "repo": "owner/repo",
                    "asset_pattern": r".*",
                    "version_pattern": "[unclosed",
                }
            }
        )
        assert any("regex" in e.lower() or "Invalid" in e for e in errors)


# =============================================================================
# ApiJsonStrategy: error cases and validate_config
# =============================================================================


class TestApiJsonStrategyErrors:
    """Tests error handling in ApiJsonStrategy.discover()."""

    def test_missing_api_url_raises(self):
        """Tests that missing api_url raises ConfigError."""
        strategy = ApiJsonStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.api_url'"):
            strategy.discover(
                {
                    "discovery": {
                        "version_path": "version",
                        "download_url_path": "url",
                    }
                }
            )

    def test_missing_version_path_raises(self):
        """Tests that missing version_path raises ConfigError."""
        strategy = ApiJsonStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.version_path'"):
            strategy.discover(
                {
                    "discovery": {
                        "api_url": "https://api.example.com",
                        "download_url_path": "url",
                    }
                }
            )

    def test_missing_download_url_path_raises(self):
        """Tests that missing download_url_path raises ConfigError."""
        strategy = ApiJsonStrategy()
        with pytest.raises(ConfigError, match="requires 'discovery.download_url_path'"):
            strategy.discover(
                {
                    "discovery": {
                        "api_url": "https://api.example.com",
                        "version_path": "version",
                    }
                }
            )

    def test_http_error_raises(self):
        """Tests that a non-2xx API response raises NetworkError."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "url",
            }
        }
        with requests_mock.Mocker() as m:
            m.get("https://api.example.com/latest", status_code=500)
            with pytest.raises(NetworkError, match="API request failed"):
                strategy.discover(app_config)

    def test_invalid_json_response_raises(self):
        """Tests that a non-JSON response raises NetworkError."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "url",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                text="not json at all",
                status_code=200,
            )
            with pytest.raises(NetworkError, match="Invalid JSON"):
                strategy.discover(app_config)

    def test_version_path_not_found_raises(self):
        """Tests that a version_path that matches nothing raises ConfigError."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "nonexistent_field",
                "download_url_path": "download_url",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                json={"version": "1.0.0", "download_url": "https://example.com/f.msi"},
            )
            with pytest.raises(ConfigError, match="did not match"):
                strategy.discover(app_config)

    def test_declared_secret_expands_inside_header_value(self, monkeypatch):
        """Tests that ${VAR} anywhere in a header value is replaced from the
        environment when org.yaml binds the variable to the API host."""
        monkeypatch.setenv("TEST_API_TOKEN", "secret123")
        strategy = ApiJsonStrategy()
        app_config = {
            "secrets": {"TEST_API_TOKEN": {"hosts": ["api.example.com"]}},
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
                "headers": {"Authorization": "Bearer ${TEST_API_TOKEN}"},
            },
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                json={
                    "version": "1.0.0",
                    "download_url": "https://example.com/file.msi",
                },
            )
            version_info = strategy.discover(app_config)
            assert m.last_request.headers.get("Authorization") == "Bearer secret123"
        assert version_info.version == "1.0.0"

    def test_nested_json_path(self):
        """Tests that nested JSONPath expressions extract values correctly."""
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "release.version",
                "download_url_path": "release.windows.x64",
            }
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                json={
                    "release": {
                        "version": "3.1.4",
                        "windows": {"x64": "https://example.com/app-3.1.4-x64.msi"},
                    }
                },
            )
            version_info = strategy.discover(app_config)
        assert version_info.version == "3.1.4"
        assert "3.1.4" in version_info.download_url


class TestApiJsonVersionPattern:
    """Tests for the optional version_pattern of the api_json strategy."""

    @staticmethod
    def _discover(version_value, version_pattern=None):
        discovery = {
            "api_url": "https://api.example.com/latest",
            "version_path": "version",
            "download_url_path": "url",
        }
        if version_pattern is not None:
            discovery["version_pattern"] = version_pattern
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.example.com/latest",
                json={"version": version_value, "url": "https://example.com/a.msi"},
            )
            return ApiJsonStrategy().discover({"discovery": discovery})

    def test_absent_pattern_uses_the_value_as_is(self):
        """Tests that without a pattern the API's value is not touched."""
        assert self._discover("v2.0").version == "v2.0"

    def test_unmatched_optional_group_is_no_match(self):
        """Tests that a group that took no part in the match is reported as
        the pattern not matching, not as version None."""
        with pytest.raises(ConfigError, match="did not match"):
            self._discover("release", r"release-?(\d+)?")

    def test_capture_group_narrows_the_value(self):
        """Tests that capture group 1 becomes the version."""
        assert self._discover("v2.0", r"v?([0-9.]+)").version == "2.0"
        assert self._discover("2.0 (stable)", r"([0-9.]+)").version == "2.0"

    def test_pattern_without_group_uses_the_full_match(self):
        """Tests that a pattern with no capture group keeps the whole match."""
        assert self._discover("build-2024.10", r"[0-9.]+").version == "2024.10"

    def test_pattern_that_does_not_match_raises(self):
        """Tests that a non-matching pattern is a configuration error."""
        with pytest.raises(ConfigError, match="did not match the API's version"):
            self._discover("latest", r"[0-9]+\.[0-9]+")

    def test_invalid_pattern_raises(self):
        """Tests that an invalid regex is a configuration error at discovery."""
        with pytest.raises(ConfigError, match="Invalid version_pattern regex"):
            self._discover("2.0", r"([0-9")


class TestApiJsonValidateConfig:
    """Tests for ApiJsonStrategy.validate_config()."""

    def test_version_pattern_must_be_a_string(self):
        """Tests that a non-string version_pattern is reported."""
        errors = ApiJsonStrategy().validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com/latest",
                    "version_path": "version",
                    "download_url_path": "download_url",
                    "version_pattern": 5,
                }
            }
        )
        assert errors == ["discovery.version_pattern must be a string"]

    def test_invalid_version_pattern_regex_reported(self):
        """Tests that an invalid version_pattern regex is reported."""
        errors = ApiJsonStrategy().validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com/latest",
                    "version_path": "version",
                    "download_url_path": "download_url",
                    "version_pattern": "([0-9",
                }
            }
        )
        assert len(errors) == 1
        assert errors[0].startswith("Invalid version_pattern regex")

    def test_valid_version_pattern_accepted(self):
        """Tests that a valid version_pattern adds no errors."""
        errors = ApiJsonStrategy().validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com/latest",
                    "version_path": "version",
                    "download_url_path": "download_url",
                    "version_pattern": r"v?([0-9.]+)",
                }
            }
        )
        assert errors == []

    def test_valid_config_returns_empty(self):
        """Tests that a fully valid config returns no errors."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com/latest",
                    "version_path": "version",
                    "download_url_path": "download_url",
                }
            }
        )
        assert errors == []

    def test_missing_api_url(self):
        """Tests that missing api_url is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "version_path": "version",
                    "download_url_path": "url",
                }
            }
        )
        assert any("api_url" in e for e in errors)

    def test_missing_version_path(self):
        """Tests that missing version_path is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "download_url_path": "url",
                }
            }
        )
        assert any("version_path" in e for e in errors)

    def test_missing_download_url_path(self):
        """Tests that missing download_url_path is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "version_path": "version",
                }
            }
        )
        assert any("download_url_path" in e for e in errors)

    def test_headers_not_dict_reported(self):
        """Tests that a non-dict headers value is reported."""
        strategy = ApiJsonStrategy()
        errors = strategy.validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "version_path": "version",
                    "download_url_path": "url",
                    "headers": "not-a-dict",
                }
            }
        )
        assert any("headers" in e for e in errors)

    def test_header_value_must_be_a_string(self):
        """Tests that a non-string header value is reported."""
        errors = ApiJsonStrategy().validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "version_path": "version",
                    "download_url_path": "url",
                    "headers": {"X-Count": 5},
                }
            }
        )
        assert any("headers.X-Count" in e and "string" in e for e in errors)

    def test_undeclared_secret_in_header_is_reported(self):
        """Tests that a header naming a variable org.yaml does not declare
        fails validation, before any request could be made."""
        errors = ApiJsonStrategy().validate_config(
            {
                "discovery": {
                    "api_url": "https://api.example.com",
                    "version_path": "version",
                    "download_url_path": "url",
                    "headers": {"Authorization": "${AZURE_CLIENT_SECRET}"},
                }
            }
        )
        assert any("AZURE_CLIENT_SECRET" in e for e in errors)

    def test_secret_bound_to_another_host_is_reported(self):
        """Tests that a declared secret whose hosts exclude api_url fails."""
        errors = ApiJsonStrategy().validate_config(
            {
                "secrets": {"API_TOKEN": {"hosts": ["api.vendor.com"]}},
                "discovery": {
                    "api_url": "https://evil.example.com/latest",
                    "version_path": "version",
                    "download_url_path": "url",
                    "headers": {"Authorization": "${API_TOKEN}"},
                },
            }
        )
        assert any("Refusing to send secret API_TOKEN" in e for e in errors)

    def test_secret_bound_to_the_api_host_is_valid(self):
        """Tests that a declared secret sent to its bound host passes."""
        errors = ApiJsonStrategy().validate_config(
            {
                "secrets": {"API_TOKEN": {"hosts": ["api.vendor.com"]}},
                "discovery": {
                    "api_url": "https://api.vendor.com/latest",
                    "version_path": "version",
                    "download_url_path": "url",
                    "headers": {"Authorization": "Bearer ${API_TOKEN}"},
                },
            }
        )
        assert errors == []


class TestApiJsonSecrets:
    """Tests that api_json only sends secrets where org.yaml allows."""

    _API = "https://api.example.com/latest"

    def _config(self, headers, secrets=None):
        return {
            "secrets": secrets or {},
            "discovery": {
                "api_url": self._API,
                "version_path": "version",
                "download_url_path": "download_url",
                "headers": headers,
            },
        }

    def test_undeclared_variable_is_refused_before_any_request(self, monkeypatch):
        """Tests that a recipe cannot reach a variable org.yaml does not
        declare, even when it is set in the environment."""
        monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
        config = self._config({"Authorization": "${AZURE_CLIENT_SECRET}"})
        with requests_mock.Mocker() as m:
            m.get(self._API, json={"version": "1", "download_url": "https://x/a"})
            with pytest.raises(ConfigError, match="AZURE_CLIENT_SECRET"):
                ApiJsonStrategy().discover(config)
        assert m.call_count == 0

    def test_unset_declared_secret_is_an_error(self, monkeypatch):
        """Tests that a missing secret stops discovery instead of sending
        the request without the header."""
        monkeypatch.delenv("API_TOKEN", raising=False)
        config = self._config(
            {"Authorization": "${API_TOKEN}"},
            {"API_TOKEN": {"hosts": ["api.example.com"]}},
        )
        with requests_mock.Mocker() as m:
            m.get(self._API, json={"version": "1", "download_url": "https://x/a"})
            with pytest.raises(ConfigError, match="API_TOKEN"):
                ApiJsonStrategy().discover(config)
        assert m.call_count == 0

    def test_secret_bound_elsewhere_is_refused(self, monkeypatch):
        """Tests that a secret bound to another host never leaves for api_url."""
        monkeypatch.setenv("API_TOKEN", "s")
        config = self._config(
            {"Authorization": "${API_TOKEN}"},
            {"API_TOKEN": {"hosts": ["api.vendor.com"]}},
        )
        with requests_mock.Mocker() as m:
            m.get(self._API, json={"version": "1", "download_url": "https://x/a"})
            with pytest.raises(ConfigError, match="Refusing to send secret"):
                ApiJsonStrategy().discover(config)
        assert m.call_count == 0

    def test_redirect_to_another_host_is_refused(self, monkeypatch):
        """Tests that the API cannot bounce a secret-bearing request to
        another host."""
        monkeypatch.setenv("API_TOKEN", "s")
        config = self._config(
            {"X-API-Key": "${API_TOKEN}"},
            {"API_TOKEN": {"hosts": ["api.example.com"]}},
        )
        with requests_mock.Mocker() as m:
            m.get(
                self._API,
                status_code=302,
                headers={"Location": "https://evil.example.com/latest"},
            )
            m.get(
                "https://evil.example.com/latest",
                json={"version": "1", "download_url": "https://x/a"},
            )
            with pytest.raises(NetworkError, match="evil.example.com"):
                ApiJsonStrategy().discover(config)
        assert m.call_count == 1

    def test_plain_headers_still_follow_redirects(self):
        """Tests that a request without secrets behaves as before."""
        config = self._config({"Accept": "application/json"})
        with requests_mock.Mocker() as m:
            m.get(
                self._API,
                status_code=302,
                headers={"Location": "https://cdn.example.com/latest"},
            )
            m.get(
                "https://cdn.example.com/latest",
                json={"version": "1", "download_url": "https://x/a"},
            )
            assert ApiJsonStrategy().discover(config).version == "1"

    def test_oversized_version_value_is_refused(self):
        """Tests that a version value longer than any real version is not
        handed to the recipe's regex."""
        config = self._config({})
        config["discovery"]["version_pattern"] = r"v?([0-9.]+)"
        with requests_mock.Mocker() as m:
            m.get(
                self._API,
                json={"version": "1" * 5000, "download_url": "https://x/a"},
            )
            with pytest.raises(NetworkError, match="characters long"):
                ApiJsonStrategy().discover(config)


class TestApiGithubToken:
    """Tests for the api_github token under the secrets binding."""

    _API = "https://api.github.com/repos/owner/repo/releases/latest"
    _RELEASE = {
        "tag_name": "v1.2.3",
        "prerelease": False,
        "assets": [
            {"name": "installer.msi", "browser_download_url": "https://x/i.msi"}
        ],
    }

    def _config(self, token, secrets=None):
        return {
            "secrets": secrets or {},
            "discovery": {
                "repo": "owner/repo",
                "asset_pattern": r".*\.msi$",
                "token": token,
            },
        }

    _DECLARED = {"GITHUB_TOKEN": {"hosts": ["api.github.com"]}}

    def test_declared_token_variable_is_sent(self, monkeypatch):
        """Tests that a token org.yaml binds to api.github.com is sent."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
        with requests_mock.Mocker() as m:
            m.get(self._API, json=self._RELEASE)
            ApiGithubStrategy().discover(
                self._config("${GITHUB_TOKEN}", self._DECLARED)
            )
            assert m.last_request.headers["Authorization"] == "Bearer ghp_x"

    def test_undeclared_token_variable_is_refused(self, monkeypatch):
        """Tests that the token, like a header, cannot name a variable
        org.yaml does not declare, even one that is set."""
        monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
        with requests_mock.Mocker() as m:
            m.get(self._API, json=self._RELEASE)
            with pytest.raises(ConfigError, match="AZURE_CLIENT_SECRET"):
                ApiGithubStrategy().discover(self._config("${AZURE_CLIENT_SECRET}"))
        assert m.call_count == 0

    def test_unset_token_variable_is_an_error(self, monkeypatch):
        """Tests that an unset token variable stops discovery rather than
        sending the request unauthenticated."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with requests_mock.Mocker() as m:
            m.get(self._API, json=self._RELEASE)
            with pytest.raises(ConfigError, match="not set"):
                ApiGithubStrategy().discover(
                    self._config("${GITHUB_TOKEN}", self._DECLARED)
                )
        assert m.call_count == 0

    def test_declared_token_bound_elsewhere_is_refused(self, monkeypatch):
        """Tests that a secret org.yaml binds to another host is not sent
        to GitHub."""
        monkeypatch.setenv("VENDOR_KEY", "k")
        config = self._config(
            "${VENDOR_KEY}", {"VENDOR_KEY": {"hosts": ["api.vendor.com"]}}
        )
        with requests_mock.Mocker() as m:
            m.get(self._API, json=self._RELEASE)
            with pytest.raises(ConfigError, match="Refusing to send secret"):
                ApiGithubStrategy().discover(config)
        assert m.call_count == 0

    def test_declared_token_bound_elsewhere_fails_validation(self):
        """Tests that napt validate reports the same refusal."""
        errors = ApiGithubStrategy().validate_config(
            self._config("${VENDOR_KEY}", {"VENDOR_KEY": {"hosts": ["api.vendor.com"]}})
        )
        assert any("Refusing to send secret VENDOR_KEY" in e for e in errors)

    def test_literal_token_is_sent_only_to_github(self):
        """Tests that a token written into the recipe is still bound to
        api.github.com, so a redirect elsewhere does not carry it."""
        with requests_mock.Mocker() as m:
            m.get(self._API, json=self._RELEASE)
            ApiGithubStrategy().discover(self._config("plain-token"))
            assert m.last_request.headers["Authorization"] == "Bearer plain-token"

        with requests_mock.Mocker() as m:
            m.get(
                self._API,
                status_code=302,
                headers={"Location": "https://evil.example.com/latest"},
            )
            m.get("https://evil.example.com/latest", json=self._RELEASE)
            with pytest.raises(NetworkError, match="evil.example.com"):
                ApiGithubStrategy().discover(self._config("plain-token"))
        assert m.call_count == 1

    def test_non_string_token_fails_validation(self):
        """Tests that a token that is not a string is reported."""
        errors = ApiGithubStrategy().validate_config(self._config(5))
        assert "discovery.token: Must be a string" in errors

    def test_oversized_tag_is_refused(self):
        """Tests that an absurdly long tag is not handed to version_pattern."""
        release = dict(self._RELEASE, tag_name="v" + "1" * 5000)
        with requests_mock.Mocker() as m:
            m.get(self._API, json=release)
            with pytest.raises(NetworkError, match="characters long"):
                ApiGithubStrategy().discover(self._config(None))

    def test_oversized_asset_name_is_refused(self):
        """Tests that an absurdly long asset name is not handed to
        asset_pattern."""
        release = dict(
            self._RELEASE,
            assets=[{"name": "a" * 5000, "browser_download_url": "https://x/a"}],
        )
        with requests_mock.Mocker() as m:
            m.get(self._API, json=release)
            with pytest.raises(NetworkError, match="characters long"):
                ApiGithubStrategy().discover(self._config(None))


class TestWebScrapeLimits:
    """Tests that web_scrape bounds what recipe patterns run over."""

    def _config(self, **overrides):
        discovery = {
            "page_url": "https://example.com/download.html",
            "link_pattern": r'href="([^"]+\.msi)"',
            "version_pattern": r"(\d+\.\d+)",
        }
        discovery.update(overrides)
        return {"discovery": discovery}

    def test_oversized_page_is_refused(self):
        """Tests that a page larger than any download page is rejected
        before link_pattern runs over it."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/download.html",
                content=b"<a>" + b"x" * (5 * 1024 * 1024 + 1),
            )
            with pytest.raises(NetworkError, match="bytes"):
                WebScrapeStrategy().discover(self._config())

    def test_oversized_link_is_refused(self):
        """Tests that an absurdly long matched link is not handed to
        version_pattern."""
        html = f'<a href="/{"a" * 5000}/1.0.msi">x</a>'
        with requests_mock.Mocker() as m:
            m.get("https://example.com/download.html", text=html)
            with pytest.raises(NetworkError, match="characters long"):
                WebScrapeStrategy().discover(self._config())
