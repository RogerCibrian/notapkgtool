"""Tests for napt.discovery: strategy registry, strategies, url_download flow."""

from __future__ import annotations

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
from napt.exceptions import ConfigError, NetworkError
from napt.versioning.msi import MSIMetadata


class TestStrategyRegistry:
    """Tests for discovery strategy registry lookup."""

    def test_get_api_github_strategy(self):
        """Tests that api_github strategy can be retrieved from the registry."""
        strategy = get_strategy("api_github")
        assert isinstance(strategy, ApiGithubStrategy)

    def test_get_unknown_strategy_raises(self):
        """Tests that an unregistered strategy name raises ConfigError."""
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
            with patch(
                "napt.discovery.url_download.extract_msi_metadata"
            ) as mock_extract:
                mock_extract.return_value = MSIMetadata(
                    product_name="", product_version="1.2.3", architecture="x64"
                )
                result = run_url_download(app_config, tmp_test_dir)

        assert result.version == "1.2.3"
        assert result.version_source == "url_download"
        app_dir = tmp_test_dir / "test-app"
        assert result.file_path == app_dir / "1.2.3" / "installer.msi"
        assert result.file_path.exists()
        assert not (app_dir / ".incoming").exists()
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
                    "napt.discovery.url_download.extract_msi_metadata"
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
            with patch(
                "napt.discovery.url_download.extract_msi_metadata"
            ) as mock_extract:
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

    def test_extraction_failure_raises(self, tmp_test_dir):
        """Tests that MSI extraction failures raise NetworkError."""
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
            with patch(
                "napt.discovery.url_download.extract_msi_metadata"
            ) as mock_extract:
                mock_extract.side_effect = NetworkError("Invalid MSI")
                with pytest.raises(
                    NetworkError, match="Failed to extract MSI ProductVersion"
                ):
                    run_url_download(app_config, tmp_test_dir)


_SIDECAR_URL = "https://example.com/installer.msi"


def _seed_previous_download(
    app_dir,
    *,
    version="1.0.0",
    filename="installer.msi",
    url=_SIDECAR_URL,
    etag='W/"abc123"',
    with_installer=True,
):
    """Writes a sidecar file and, by default, the installer it points at."""
    app_dir.mkdir(parents=True)
    if with_installer:
        installer = app_dir / version / filename
        installer.parent.mkdir(parents=True, exist_ok=True)
        installer.write_bytes(b"fake cached msi")
    (app_dir / ".download.json").write_text(
        json.dumps(
            {
                "url": url,
                "etag": etag,
                "last_modified": None,
                "version": version,
                "filename": filename,
                "sha256": "cached_sha256",
            }
        ),
        encoding="utf-8",
    )


def _run_with_msi_version(app_config, output_dir, version):
    """Runs url_download with MSI version extraction stubbed out."""
    with patch("napt.discovery.url_download.extract_msi_metadata") as mock_extract:
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
        assert result.sha256 == "cached_sha256"
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
            with patch(
                "napt.discovery.url_download.extract_msi_metadata"
            ) as mock_extract:
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
# ApiGithubStrategy — error cases and validate_config
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

    def test_rate_limited_raises(self):
        """Tests that a 403 API response raises NetworkError mentioning rate limit."""
        strategy = ApiGithubStrategy()
        app_config = {"discovery": {"repo": "owner/repo", "asset_pattern": ".*"}}
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                status_code=403,
            )
            with pytest.raises(NetworkError, match="rate limit"):
                strategy.discover(app_config)

    def test_prerelease_rejected_when_flag_false(self):
        """Tests that a prerelease latest release is rejected when prerelease=False."""
        strategy = ApiGithubStrategy()
        app_config = {
            "discovery": {
                "repo": "owner/repo",
                "asset_pattern": r".*\.msi$",
                "prerelease": False,
            }
        }
        release_data = {
            "tag_name": "v2.0.0-beta",
            "prerelease": True,
            "assets": [
                {
                    "name": "installer.msi",
                    "browser_download_url": "https://example.com/installer.msi",
                }
            ],
        }
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.github.com/repos/owner/repo/releases/latest",
                json=release_data,
            )
            with pytest.raises(NetworkError, match="pre-release"):
                strategy.discover(app_config)

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
# ApiJsonStrategy — error cases and validate_config
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

    def test_env_var_header_expansion(self, monkeypatch):
        """Tests that ${VAR} placeholders in headers are expanded from env."""
        monkeypatch.setenv("TEST_API_TOKEN", "secret123")
        strategy = ApiJsonStrategy()
        app_config = {
            "discovery": {
                "api_url": "https://api.example.com/latest",
                "version_path": "version",
                "download_url_path": "download_url",
                "headers": {"Authorization": "${TEST_API_TOKEN}"},
            }
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
            assert m.last_request.headers.get("Authorization") == "secret123"
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


class TestApiJsonValidateConfig:
    """Tests for ApiJsonStrategy.validate_config()."""

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
