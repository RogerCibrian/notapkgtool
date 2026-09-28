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
    link_selector=None,
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
                "link_selector": link_selector or f'a[href$=".{extension}"]',
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

    def test_reuse_ignores_a_changed_query_string(self, tmp_test_dir, create_yaml_file):
        """Tests that a per-visit token in the link does not defeat the skip."""
        recipe_path = _web_scrape_recipe(create_yaml_file, link_selector="a")

        with requests_mock.Mocker() as m:
            _serve(m, "1.2.3", b"exe bytes")
            discover_recipe(recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state")
            m.get(
                _PAGE,
                text='<a href="/app-v1.2.3-installer.exe?token=day2">Download</a>',
            )
            with patch("napt.discovery.resolve.download_file") as mock_download:
                result = discover_recipe(
                    recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
                )

        mock_download.assert_not_called()
        assert result.version == "1.2.3"

    def test_changed_link_at_the_same_version_asks_the_server(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a different link (a switched asset, a re-published
        release) at an unchanged version is fetched, not reused, so state
        never pairs the new link with the old file's hash."""
        recipe_path = _web_scrape_recipe(create_yaml_file)

        with requests_mock.Mocker() as m:
            _serve(m, "1.2.3", b"x64 bytes")
            discover_recipe(recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state")
            m.get(_PAGE, text='<a href="/arm64/app-v1.2.3-installer.exe">Download</a>')
            m.get(
                "https://example.com/arm64/app-v1.2.3-installer.exe",
                content=b"arm64 bytes",
                headers={"Content-Length": "11"},
            )
            result = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )

        assert result.sha256 == hashlib.sha256(b"arm64 bytes").hexdigest()
        assert result.file_path.read_bytes() == b"arm64 bytes"
        sidecar = json.loads(
            (tmp_test_dir / "test-app" / ".download.json").read_text(encoding="utf-8")
        )
        assert sidecar["url"].endswith("/arm64/app-v1.2.3-installer.exe")
        assert sidecar["sha256"] == result.sha256

    def test_changed_link_still_reuses_on_304(self, tmp_test_dir, create_yaml_file):
        """Tests that a changed link is checked conditionally, so a mirror
        serving the same file costs one 304 and no download."""
        recipe_path = _web_scrape_recipe(create_yaml_file)

        with requests_mock.Mocker() as m:
            m.get(_PAGE, text='<a href="/app-v1.2.3-installer.exe">Download</a>')
            m.get(
                "https://example.com/app-v1.2.3-installer.exe",
                content=b"exe bytes",
                headers={"Content-Length": "9", "ETag": '"same"'},
            )
            first = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )
            m.get(_PAGE, text='<a href="/mirror/app-v1.2.3-installer.exe">Download</a>')
            m.get(
                "https://example.com/mirror/app-v1.2.3-installer.exe", status_code=304
            )
            second = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )
            mirror_requests = [r for r in m.request_history if "/mirror/" in r.url]

        assert len(mirror_requests) == 1
        assert mirror_requests[0].headers["If-None-Match"] == '"same"'
        assert second.file_path == first.file_path
        assert second.sha256 == first.sha256

    def test_tampered_installer_is_downloaded_again(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that reuse re-checks the file on disk against the sidecar's
        hash, so a replaced file is never recorded under the old hash."""
        recipe_path = _web_scrape_recipe(create_yaml_file)

        with requests_mock.Mocker() as m:
            _serve(m, "1.2.3", b"exe bytes")
            first = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )
            first.file_path.write_bytes(b"something else")
            second = discover_recipe(
                recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state"
            )
            installer_requests = [
                r for r in m.request_history if r.url.endswith(".exe")
            ]

        assert len(installer_requests) == 2
        assert second.sha256 == hashlib.sha256(b"exe bytes").hexdigest()
        assert second.file_path.read_bytes() == b"exe bytes"

    def test_same_version_redownload_keeps_the_displaced_file(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a vendor re-releasing a version under the same filename
        does not destroy the bytes the published release was built from."""
        recipe_path = create_yaml_file(
            "recipe.yaml",
            {
                "apiVersion": "napt/v1",
                "name": "Test App",
                "id": "test-app",
                "discovery": {
                    "strategy": "url_download",
                    "url": "https://example.com/setup.msi",
                },
            },
        )
        state_dir = tmp_test_dir / "state"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/setup.msi",
                [
                    {"content": b"old", "headers": {"ETag": '"e1"'}},
                    {"content": b"new!", "headers": {"ETag": '"e2"'}},
                ],
            )
            with patch("napt.discovery.resolve.extract_msi_metadata") as extract:
                extract.return_value = MSIMetadata(
                    product_name="", product_version="5.0", architecture="x64"
                )
                first = discover_recipe(recipe_path, tmp_test_dir, state_dir=state_dir)
                second = discover_recipe(recipe_path, tmp_test_dir, state_dir=state_dir)

        folder = tmp_test_dir / "test-app" / "5.0"
        assert second.file_path == folder / "setup.msi"
        assert second.file_path.read_bytes() == b"new!"
        displaced = folder / f"setup.{first.sha256[:8]}.msi"
        assert displaced.read_bytes() == b"old"
        assert sorted(p.name for p in folder.iterdir()) == sorted(
            ["setup.msi", displaced.name]
        )

    def test_repeated_redownload_of_the_same_bytes_keeps_one_aside_copy(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that displacing the same file twice does not lose the
        aside copy or fail on its existing name."""
        recipe_path = create_yaml_file(
            "recipe.yaml",
            {
                "apiVersion": "napt/v1",
                "name": "Test App",
                "id": "test-app",
                "discovery": {
                    "strategy": "url_download",
                    "url": "https://example.com/setup.msi",
                },
            },
        )
        state_dir = tmp_test_dir / "state"

        with requests_mock.Mocker() as m:
            m.get(
                "https://example.com/setup.msi",
                [
                    {"content": b"old", "headers": {"ETag": '"e1"'}},
                    {"content": b"new!", "headers": {"ETag": '"e2"'}},
                    {"content": b"old", "headers": {"ETag": '"e3"'}},
                    {"content": b"new!", "headers": {"ETag": '"e4"'}},
                ],
            )
            with patch("napt.discovery.resolve.extract_msi_metadata") as extract:
                extract.return_value = MSIMetadata(
                    product_name="", product_version="5.0", architecture="x64"
                )
                for _ in range(4):
                    discover_recipe(recipe_path, tmp_test_dir, state_dir=state_dir)

        folder = tmp_test_dir / "test-app" / "5.0"
        old_sha = hashlib.sha256(b"old").hexdigest()[:8]
        new_sha = hashlib.sha256(b"new!").hexdigest()[:8]
        assert (folder / "setup.msi").read_bytes() == b"new!"
        assert (folder / f"setup.{old_sha}.msi").read_bytes() == b"old"
        assert (folder / f"setup.{new_sha}.msi").read_bytes() == b"new!"
        assert len(list(folder.iterdir())) == 3

    def test_another_runs_download_folder_is_left_alone(
        self, tmp_test_dir, create_yaml_file
    ):
        """Tests that a run never removes a download folder another run for
        the same app is still using."""
        recipe_path = _web_scrape_recipe(create_yaml_file)
        app_dir = tmp_test_dir / "test-app"
        other = app_dir / ".incoming"
        other.mkdir(parents=True)
        (other / "app.exe.part").write_bytes(b"half")

        with requests_mock.Mocker() as m:
            _serve(m, "1.2.3", b"exe bytes")
            discover_recipe(recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state")

        assert (other / "app.exe.part").read_bytes() == b"half"
        assert not [p for p in app_dir.iterdir() if p.name.startswith(".incoming-")]

    def test_stale_download_folders_are_removed(self, tmp_test_dir, create_yaml_file):
        """Tests that a per-run folder left by a crashed run is cleaned up
        once it is old enough that no run can still be using it."""
        import os
        import time

        recipe_path = _web_scrape_recipe(create_yaml_file)
        app_dir = tmp_test_dir / "test-app"
        stale = app_dir / ".incoming-stale"
        stale.mkdir(parents=True)
        (stale / "app.exe.part").write_bytes(b"half")
        two_days_ago = time.time() - 2 * 24 * 3600
        os.utime(stale, (two_days_ago, two_days_ago))

        with requests_mock.Mocker() as m:
            _serve(m, "1.2.3", b"exe bytes")
            discover_recipe(recipe_path, tmp_test_dir, state_dir=tmp_test_dir / "state")

        assert not stale.exists()

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
