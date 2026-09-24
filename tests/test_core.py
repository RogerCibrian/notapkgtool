"""
Tests for napt.core module.

Tests core orchestration including:
- Recipe validation workflow
- discover_recipe function
- Error handling
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest
import requests_mock

from napt.discovery.manager import discover_recipe
from napt.exceptions import ConfigError
from napt.versioning.msi import MSIMetadata


class TestDiscoverRecipe:
    """Tests for discover_recipe orchestration function."""

    def test_discover_recipe_success(self, tmp_test_dir, create_yaml_file):
        """Tests the successful url_download discovery workflow end to end."""
        from napt.discovery.base import StrategyResult

        recipe_data = {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {
                "strategy": "url_download",
                "url": "https://example.com/test.msi",
            },
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with patch("napt.discovery.manager.run_url_download") as mock_run:
            mock_run.return_value = StrategyResult(
                version="1.2.3",
                version_source="msi",
                file_path=tmp_test_dir / "test.msi",
                sha256="abc123" * 8,
                download_url="https://example.com/test.msi",
                cached=False,
            )
            result = discover_recipe(
                recipe_path,
                tmp_test_dir,
                state_dir=tmp_test_dir / "state",
            )

        assert result.app_name == "Test App"
        assert result.app_id == "test-app"
        assert result.strategy == "url_download"
        assert result.version == "1.2.3"
        assert result.version_source == "msi"
        assert result.status == "success"

    def test_discover_recipe_missing_strategy_in_empty_recipe_raises(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that recipe without discovery section raises ConfigError."""
        recipe_data = {"apiVersion": "napt/v1", "name": "Test", "id": "test"}
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="Missing required field: discovery"):
            discover_recipe(
                recipe_path,
                tmp_test_dir,
                state_dir=tmp_test_dir / "state",
            )

    def test_discover_recipe_missing_strategy_raises(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that missing strategy raises ConfigError."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {},  # No strategy
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="strategy"):
            discover_recipe(
                recipe_path,
                tmp_test_dir,
                state_dir=tmp_test_dir / "state",
            )

    def test_discover_recipe_unknown_strategy_raises(
        self, tmp_test_dir, create_yaml_file
    ):
        """Test that unknown strategy raises ConfigError."""
        recipe_data = {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {"strategy": "nonexistent_strategy"},
        }
        recipe_path = create_yaml_file("recipe.yaml", recipe_data)

        with pytest.raises(ConfigError, match="Unknown discovery strategy"):
            discover_recipe(
                recipe_path,
                tmp_test_dir,
                state_dir=tmp_test_dir / "state",
            )

    def test_discover_recipe_missing_file_raises(self, tmp_test_dir):
        """Test that missing recipe file raises error."""
        nonexistent = tmp_test_dir / "nonexistent.yaml"

        with pytest.raises(ConfigError):
            discover_recipe(nonexistent, tmp_test_dir)


_PAGE = "https://example.com/download.html"


def _web_scrape_recipe(
    create_yaml_file,
    extension="exe",
    version_pattern=r"app-v([0-9.]+)-installer",
):
    """Creates a web_scrape recipe whose version comes from the link's filename."""
    return create_yaml_file(
        "recipe.yaml",
        {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {
                "strategy": "web_scrape",
                "page_url": _PAGE,
                "link_selector": f'a[href$=".{extension}"]',
                "version_pattern": version_pattern,
            },
        },
    )


def _serve(m, version, content, extension="exe"):
    """Mocks the vendor page and the installer link it points at."""
    name = f"app-v{version}-installer.{extension}"
    m.get(_PAGE, text=f'<a href="/{name}">Download</a>')
    m.get(
        f"https://example.com/{name}",
        content=content,
        headers={"Content-Length": str(len(content))},
    )
    return name


class TestVersionFirstResolution:
    """Tests for how a version-first strategy's finding becomes a download."""

    def test_exe_is_filed_under_the_reported_version(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that an installer with no version of its own takes the page's."""
        recipe_path = _web_scrape_recipe(create_yaml_file)

        with requests_mock.Mocker() as m:
            name = _serve(m, "1.2.3", b"exe bytes")
            result = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )

        assert result.version == "1.2.3"
        assert result.version_source == "web_scrape"
        assert result.file_path == tmp_test_dir / "test-app" / "1.2.3" / name
        assert result.sha256 == hashlib.sha256(b"exe bytes").hexdigest()

    def test_msi_version_wins_over_the_reported_one(
        self, tmp_test_dir, create_yaml_file, capsys
    ):
        """Tests that the MSI's own version names the folder and the release."""
        from napt.state.deployment import deployment_state_path, load_deployment_state

        recipe_path = _web_scrape_recipe(create_yaml_file, extension="msi")

        with requests_mock.Mocker() as m:
            name = _serve(m, "4.41.106", b"msi bytes", extension="msi")
            with patch("napt.discovery.resolve.extract_msi_metadata") as extract:
                extract.return_value = MSIMetadata(
                    product_name="", product_version="4.41.106.0", architecture="x64"
                )
                result = discover_recipe(
                    recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                )

        assert result.version == "4.41.106.0"
        assert result.version_source == "msi"
        assert result.file_path == tmp_test_dir / "test-app" / "4.41.106.0" / name
        # --state-dir is the state root; files live under deployment/, where
        # build, promote, and status read them.
        state = load_deployment_state(
            deployment_state_path(tmp_test_dir / "state" / "deployment", "test-app")
        )
        assert state["pending"]["version"] == "4.41.106.0"
        sidecar = json.loads(
            (tmp_test_dir / "test-app" / ".download.json").read_text(encoding="utf-8")
        )
        assert sidecar["discovered_version"] == "4.41.106"
        assert sidecar["version"] == "4.41.106.0"
        out = capsys.readouterr().out
        assert "Installer reports version 4.41.106.0" in out
        assert "web_scrape reported 4.41.106" in out

    def test_same_reported_version_reuses_the_download(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a page still reporting last run's version costs no request."""
        recipe_path = _web_scrape_recipe(create_yaml_file, extension="msi")

        with requests_mock.Mocker() as m:
            name = _serve(m, "4.41.106", b"msi bytes", extension="msi")
            with patch("napt.discovery.resolve.extract_msi_metadata") as extract:
                extract.return_value = MSIMetadata(
                    product_name="", product_version="4.41.106.0", architecture="x64"
                )
                first = discover_recipe(
                    recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                )
            with patch("napt.discovery.resolve.download_file") as mock_download:
                second = discover_recipe(
                    recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                )

        mock_download.assert_not_called()
        assert second.version == "4.41.106.0"
        assert second.version_source == "msi"
        assert second.file_path == tmp_test_dir / "test-app" / "4.41.106.0" / name
        assert second.sha256 == first.sha256

    def test_wrong_first_download_is_corrected_once_the_vendor_catches_up(
        self, tmp_test_dir, create_yaml_file, capsys
    ):
        """Tests that a page ahead of its file keeps being checked until they agree."""
        recipe_path = _web_scrape_recipe(create_yaml_file, extension="msi")
        state_dir = tmp_test_dir / "state"
        link = "https://example.com/app-v2.1-installer.msi"
        msi_versions = iter(["2.0", "2.1"])

        def run():
            with patch("napt.discovery.resolve.extract_msi_metadata") as extract:
                extract.side_effect = lambda _path: MSIMetadata(
                    product_name="",
                    product_version=next(msi_versions),
                    architecture="x64",
                )
                return discover_recipe(recipe_path, tmp_test_dir, state_dir=state_dir)

        with requests_mock.Mocker() as m:
            m.get(_PAGE, text='<a href="/app-v2.1-installer.msi">Download</a>')
            m.get(
                link,
                [
                    # Monday: the page says 2.1, the link still serves 2.0.
                    {"content": b"old", "headers": {"ETag": '"e-2.0"'}},
                    # Monday, later: unchanged.
                    {"status_code": 304},
                    # Wednesday: the real 2.1 file arrives.
                    {"content": b"new!", "headers": {"ETag": '"e-2.1"'}},
                ],
            )
            monday = run()
            monday_again = run()
            wednesday = run()
            thursday = run()
            installer_requests = [
                r for r in m.request_history if r.url.startswith(link)
            ]

        app_dir = tmp_test_dir / "test-app"
        assert monday.version == "2.0"
        assert monday_again.version == "2.0"
        assert installer_requests[1].headers["If-None-Match"] == '"e-2.0"'
        assert wednesday.version == "2.1"
        assert wednesday.file_path == app_dir / "2.1" / "app-v2.1-installer.msi"
        assert (app_dir / "2.0" / "app-v2.1-installer.msi").read_bytes() == b"old"
        assert thursday.version == "2.1"
        assert len(installer_requests) == 3  # Thursday made no request
        # Warned on Monday, Monday again, and at the start of Wednesday's run
        # (before the fetch showed the vendor had caught up); not on Thursday.
        out = capsys.readouterr().out
        assert out.count("web_scrape reports version 2.1 but the installer is 2.0") == 3

    def test_format_only_difference_is_trusted(
        self, tmp_test_dir, create_yaml_file, capsys
    ):
        """Tests that 4.41.106 against 4.41.106.0 skips with no request or warning."""
        recipe_path = _web_scrape_recipe(create_yaml_file, extension="msi")

        with requests_mock.Mocker() as m:
            _serve(m, "4.41.106", b"msi bytes", extension="msi")
            with patch("napt.discovery.resolve.extract_msi_metadata") as extract:
                extract.return_value = MSIMetadata(
                    product_name="", product_version="4.41.106.0", architecture="x64"
                )
                discover_recipe(
                    recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                )
                discover_recipe(
                    recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                )
            installer_requests = [
                r for r in m.request_history if r.url.endswith(".msi")
            ]

        assert len(installer_requests) == 1
        assert "but the installer is" not in capsys.readouterr().out

    def test_mismatch_without_validators_downloads_every_run(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a server with no ETag gets a full download while mismatched."""
        recipe_path = _web_scrape_recipe(create_yaml_file, extension="msi")

        with requests_mock.Mocker() as m:
            _serve(m, "2.1", b"old", extension="msi")
            with patch("napt.discovery.resolve.extract_msi_metadata") as extract:
                extract.return_value = MSIMetadata(
                    product_name="", product_version="2.0", architecture="x64"
                )
                for _ in range(2):
                    discover_recipe(
                        recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                    )
            installer_requests = [
                r for r in m.request_history if r.url.endswith(".msi")
            ]

        assert len(installer_requests) == 2
        assert all("If-None-Match" not in r.headers for r in installer_requests)

    def test_reuse_ignores_a_changed_download_url(self, tmp_test_dir, create_yaml_file):
        """Tests that the same release behind a new link does not defeat the skip."""
        recipe_path = _web_scrape_recipe(create_yaml_file)

        with requests_mock.Mocker() as m:
            _serve(m, "1.2.3", b"exe bytes")
            discover_recipe(recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state")
            m.get(
                _PAGE, text='<a href="/mirror2/app-v1.2.3-installer.exe">Download</a>'
            )
            with patch("napt.discovery.resolve.download_file") as mock_download:
                result = discover_recipe(
                    recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                )

        mock_download.assert_not_called()
        assert result.version == "1.2.3"

    def test_older_version_is_downloaded_not_relabelled(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a vendor rollback never reuses the newer version's file."""
        recipe_path = _web_scrape_recipe(create_yaml_file)

        with requests_mock.Mocker() as m:
            _serve(m, "2.0.0", b"the 2.0.0 installer")
            discover_recipe(recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state")
            name = _serve(m, "1.9.0", b"the 1.9.0 installer")
            result = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )

        app_dir = tmp_test_dir / "test-app"
        assert result.version == "1.9.0"
        assert result.file_path == app_dir / "1.9.0" / name
        assert result.sha256 == hashlib.sha256(b"the 1.9.0 installer").hexdigest()
        assert (app_dir / "2.0.0" / "app-v2.0.0-installer.exe").read_bytes() == (
            b"the 2.0.0 installer"
        )

    def test_missing_installer_is_downloaded_again(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a sidecar pointing at a deleted file does not skip."""
        recipe_path = _web_scrape_recipe(create_yaml_file)

        with requests_mock.Mocker() as m:
            _serve(m, "1.2.3", b"exe bytes")
            first = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )
            first.file_path.unlink()
            requests_before = len(m.request_history)
            second = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )
            downloaded = len(m.request_history) - requests_before

        assert downloaded == 2  # the page, then the installer
        assert second.file_path == first.file_path
        assert second.file_path.read_bytes() == b"exe bytes"

    @pytest.mark.parametrize(("served", "warns"), [("1.9.0", True), ("2.1.0", False)])
    def test_warns_when_pending_is_lower_than_published(
        self, tmp_test_dir, create_yaml_file, capsys, served, warns
    ):
        """Tests that a downgrade is recorded as pending and called out."""
        from napt.state.deployment import (
            create_default_deployment_state,
            deployment_state_path,
            load_deployment_state,
            save_deployment_state,
        )

        recipe_path = _web_scrape_recipe(create_yaml_file)
        state_path = deployment_state_path(
            tmp_test_dir / "state" / "deployment", "test-app"
        )
        state = create_default_deployment_state()
        state["published"] = {"version": "2.0.0", "sha256": "published"}
        save_deployment_state(state, state_path)

        with requests_mock.Mocker() as m:
            _serve(m, served, b"installer")
            discover_recipe(recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state")

        assert load_deployment_state(state_path)["pending"]["version"] == served
        assert ("is LOWER than the published" in capsys.readouterr().out) is warns

    def test_unusable_version_leaves_nothing_behind(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a version with path segments is refused after download."""
        # Captures everything between the markers, separators included.
        recipe_path = _web_scrape_recipe(
            create_yaml_file, version_pattern=r"app-v(.+)-installer"
        )
        state_dir = tmp_test_dir / "state"

        with requests_mock.Mocker() as m:
            m.get(_PAGE, text='<a href="/app-v2.0/stable-installer.exe">Download</a>')
            m.get(
                "https://example.com/app-v2.0/stable-installer.exe",
                content=b"x",
                headers={"Content-Length": "1"},
            )
            with pytest.raises(ConfigError, match="cannot be used as a folder"):
                discover_recipe(
                    recipe_path, tmp_test_dir, stateless=True, state_dir=state_dir
                )

        assert list((tmp_test_dir / "test-app").iterdir()) == []
        assert not state_dir.exists()
