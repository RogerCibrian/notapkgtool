"""
Tests for napt.build.packager module.

Tests .intunewin package creation including:
- Build structure validation
- IntuneWinAppUtil.exe handling
- Package creation

These are UNIT tests using mocked data for fast execution.
For integration tests with real IntuneWinAppUtil.exe, see test_integration_packaging.py.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from napt.build.packager import (
    INTUNEWIN_CONTENTS_API,
    INTUNEWIN_GITHUB_API,
    _execute_packaging,
    _get_intunewin_tool,
    _verify_build_structure,
    create_intunewin,
    fetch_latest_intunewin_version,
)
from napt.exceptions import ConfigError, NetworkError, PackagingError

# All tests in this file are unit tests (fast, mocked)

_INSTALLER_BYTES = b"installer bytes"
_INSTALLER_SHA256 = hashlib.sha256(_INSTALLER_BYTES).hexdigest()


def _make_build_dir(
    tmp_path: Path,
    app_id: str = "test-app",
    version: str = "1.0.0",
    detection: bool = True,
    requirements: bool = False,
    manifest: bool = True,
) -> Path:
    """Create a valid build version dir the way 'napt build' lays it out.

    Args:
        tmp_path: Pytest tmp_path fixture.
        app_id: App identifier used in the directory path.
        version: Version string used in the directory path.
        detection: If True, create a Detection.ps1 script and name it in
            the manifest.
        requirements: If True, create a Requirements.ps1 script and name it
            in the manifest.
        manifest: If False, leave the build manifest out.

    Returns:
        Path to the version directory (builds/{app_id}/{version}/).
    """
    version_dir = tmp_path / "builds" / app_id / version
    packagefiles = version_dir / "packagefiles"
    packagefiles.mkdir(parents=True)
    (packagefiles / "PSAppDeployToolkit").mkdir()
    (packagefiles / "Files").mkdir()
    (packagefiles / "Files" / "setup.msi").write_bytes(_INSTALLER_BYTES)
    (packagefiles / "Invoke-AppDeployToolkit.ps1").write_text("script")
    (packagefiles / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")
    data = {
        "app_id": app_id,
        "app_name": "Test App",
        "version": version,
        "win32_build_types": "both" if requirements else "app_only",
        "architecture": "x64",
        "installer_sha256": _INSTALLER_SHA256,
    }
    if detection:
        (version_dir / f"{app_id}-Detection.ps1").write_text("detection script")
        data["detection_script_path"] = f"{app_id}-Detection.ps1"
    if requirements:
        (version_dir / f"{app_id}-Requirements.ps1").write_text("requirements script")
        data["requirements_script_path"] = f"{app_id}-Requirements.ps1"
    if manifest:
        (version_dir / "build-manifest.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
    return version_dir


def _fake_execute(tool_path, source_dir, setup_file, output_dir):
    """Stands in for IntuneWinAppUtil: writes one package into output_dir."""
    package = output_dir / "Invoke-AppDeployToolkit.intunewin"
    package.write_bytes(b"intunewin bytes")
    return package


_DOWNLOAD_URL_PREFIX = (
    "https://raw.githubusercontent.com/microsoft/Microsoft-Win32-Content-Prep-Tool"
)


class TestFetchLatestIntunewinVersion:
    """Tests for fetching latest IntuneWinAppUtil version from GitHub."""

    def test_fetch_latest_success_bare_tag(self, requests_mock):
        """Tests version extraction when tag has no v prefix."""
        requests_mock.get(INTUNEWIN_GITHUB_API, json={"tag_name": "1.8.6"})

        assert fetch_latest_intunewin_version() == "1.8.6"

    def test_fetch_latest_success_v_prefix(self, requests_mock):
        """Tests that v prefix is stripped from tag name."""
        requests_mock.get(INTUNEWIN_GITHUB_API, json={"tag_name": "v1.8.6"})

        assert fetch_latest_intunewin_version() == "1.8.6"

    def test_fetch_latest_api_error(self, requests_mock):
        """Tests NetworkError on GitHub API failure."""
        requests_mock.get(INTUNEWIN_GITHUB_API, status_code=500)

        with pytest.raises(
            NetworkError, match="Failed to fetch latest IntuneWinAppUtil"
        ):
            fetch_latest_intunewin_version()

    def test_fetch_latest_invalid_tag(self, requests_mock):
        """Tests NetworkError when tag name cannot be parsed."""
        requests_mock.get(INTUNEWIN_GITHUB_API, json={"tag_name": "not-a-version"})

        with pytest.raises(NetworkError, match="Could not extract version"):
            fetch_latest_intunewin_version()

    @pytest.mark.parametrize("tag", ["v1.8.6-rc1", "1.8.6.beta", "v1.8.6 hotfix"])
    def test_fetch_latest_tag_with_a_suffix_is_rejected(self, requests_mock, tag):
        """Tests that a tag with a suffix is never cut down to a bare version."""
        requests_mock.get(INTUNEWIN_GITHUB_API, json={"tag_name": tag})

        with pytest.raises(NetworkError, match="Could not extract version"):
            fetch_latest_intunewin_version()


def _blob_sha(data: bytes) -> str:
    """Computes the git blob SHA-1 GitHub's contents API reports for a file."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _serve_tool(
    requests_mock,
    tag: str,
    content: bytes = b"fake exe",
    *,
    size: int | None = None,
    sha: str | None = None,
) -> None:
    """Mocks the contents API lookup for a tag and the download it points at.

    Args:
        requests_mock: The requests_mock fixture.
        tag: The tag the lookup is made for.
        content: What the download serves.
        size: The size the lookup reports; the content's own by default.
        sha: The blob hash the lookup reports; the content's own by default.
    """
    download_url = f"{_DOWNLOAD_URL_PREFIX}/{tag}/IntuneWinAppUtil.exe"
    requests_mock.get(
        f"{INTUNEWIN_CONTENTS_API}?ref={tag}",
        json={
            "name": "IntuneWinAppUtil.exe",
            "size": len(content) if size is None else size,
            "sha": _blob_sha(content) if sha is None else sha,
            "download_url": download_url,
        },
    )
    requests_mock.get(download_url, content=content)


class TestGetIntunewinTool:
    """Tests for _get_intunewin_tool version resolution and caching."""

    def test_cache_hit_returns_path(self, tmp_path):
        """Tests that a cached tool is returned without downloading."""
        cache_dir = tmp_path / "tools"
        tool_path = cache_dir / "1.8.6" / "IntuneWinAppUtil.exe"
        tool_path.parent.mkdir(parents=True)
        tool_path.write_bytes(b"fake exe")

        result = _get_intunewin_tool(cache_dir, "1.8.6")

        assert result == tool_path

    def test_release_with_path_segments_is_rejected(self, tmp_path):
        """Tests that an intunewin.release value cannot point outside the cache."""
        with pytest.raises(ConfigError, match="Invalid intunewin.release"):
            _get_intunewin_tool(tmp_path / "tools", "../../outside")

    @patch("napt.build.packager.fetch_latest_intunewin_version")
    def test_latest_resolves_via_api(self, mock_fetch, tmp_path, requests_mock):
        """Tests that 'latest' calls fetch_latest_intunewin_version."""
        mock_fetch.return_value = "1.8.6"
        _serve_tool(requests_mock, "v1.8.6")

        _get_intunewin_tool(tmp_path / "tools", "latest")

        mock_fetch.assert_called_once()

    def test_v_prefix_stripped_from_release(self, tmp_path, requests_mock):
        """Tests that a user-specified v prefix is normalised."""
        cache_dir = tmp_path / "tools"
        _serve_tool(requests_mock, "v1.8.6")

        result = _get_intunewin_tool(cache_dir, "v1.8.6")

        assert result == cache_dir / "1.8.6" / "IntuneWinAppUtil.exe"

    def test_lookup_uses_v_prefix_tag_first(self, tmp_path, requests_mock):
        """Tests that the lookup tries v{version} before the bare tag."""
        cache_dir = tmp_path / "tools"
        _serve_tool(requests_mock, "v1.8.6")

        result = _get_intunewin_tool(cache_dir, "1.8.6")

        assert result.exists()
        assert result == cache_dir / "1.8.6" / "IntuneWinAppUtil.exe"

    def test_lookup_falls_back_to_bare_tag(self, tmp_path, requests_mock):
        """Tests fallback to the bare tag when the v-prefixed one 404s."""
        cache_dir = tmp_path / "tools"
        requests_mock.get(f"{INTUNEWIN_CONTENTS_API}?ref=v1.8.3", status_code=404)
        _serve_tool(requests_mock, "1.8.3")

        result = _get_intunewin_tool(cache_dir, "1.8.3")

        assert result.exists()
        assert result == cache_dir / "1.8.3" / "IntuneWinAppUtil.exe"

    def test_both_tags_404_raises_network_error(self, tmp_path, requests_mock):
        """Tests NetworkError when both tag formats return 404."""
        requests_mock.get(f"{INTUNEWIN_CONTENTS_API}?ref=v9.9.9", status_code=404)
        requests_mock.get(f"{INTUNEWIN_CONTENTS_API}?ref=9.9.9", status_code=404)

        with pytest.raises(NetworkError, match="not found"):
            _get_intunewin_tool(tmp_path / "tools", "9.9.9")

    def test_download_cached_on_disk(self, tmp_path, requests_mock):
        """Tests downloaded tool is written to the versioned cache path."""
        cache_dir = tmp_path / "tools"
        _serve_tool(requests_mock, "v1.8.6", b"fake exe content")

        result = _get_intunewin_tool(cache_dir, "1.8.6")

        assert result.read_bytes() == b"fake exe content"
        assert result.parent == cache_dir / "1.8.6"

    def test_download_not_matching_the_reported_hash_is_refused(
        self, tmp_path, requests_mock
    ):
        """Tests that a download whose bytes are not the file the repository
        holds at that tag is refused and not cached."""
        _serve_tool(requests_mock, "v1.8.6", b"fake exe", sha="0" * 40)

        with pytest.raises(NetworkError, match="hash"):
            _get_intunewin_tool(tmp_path / "tools", "1.8.6")

        assert not (tmp_path / "tools" / "1.8.6").exists()

    def test_download_not_matching_the_reported_size_is_refused(
        self, tmp_path, requests_mock
    ):
        """Tests that a truncated download is refused and not cached."""
        _serve_tool(requests_mock, "v1.8.6", b"fake exe", size=62520)

        with pytest.raises(NetworkError, match="bytes"):
            _get_intunewin_tool(tmp_path / "tools", "1.8.6")

        assert not (tmp_path / "tools" / "1.8.6").exists()

    def test_lookup_that_is_not_json_is_a_network_error(self, tmp_path, requests_mock):
        """Tests that a lookup answered with HTML is reported, not a traceback."""
        requests_mock.get(f"{INTUNEWIN_CONTENTS_API}?ref=v1.8.6", text="<html>")

        with pytest.raises(NetworkError, match="Invalid JSON"):
            _get_intunewin_tool(tmp_path / "tools", "1.8.6")

    def test_lookup_that_is_not_an_object_is_a_network_error(
        self, tmp_path, requests_mock
    ):
        """Tests that a lookup answered with a JSON array is reported."""
        requests_mock.get(f"{INTUNEWIN_CONTENTS_API}?ref=v1.8.6", json=["x"])

        with pytest.raises(NetworkError, match="Unexpected GitHub API response"):
            _get_intunewin_tool(tmp_path / "tools", "1.8.6")

    def test_lookup_network_failure_is_a_network_error(self, tmp_path, requests_mock):
        """Tests that a lookup that cannot reach GitHub is reported."""
        requests_mock.get(
            f"{INTUNEWIN_CONTENTS_API}?ref=v1.8.6",
            exc=requests.ConnectionError("no route"),
        )

        with pytest.raises(NetworkError, match="Failed to look up"):
            _get_intunewin_tool(tmp_path / "tools", "1.8.6")

    def test_lookup_without_a_download_url_is_a_network_error(
        self, tmp_path, requests_mock
    ):
        """Tests that a lookup that names no download URL is reported."""
        requests_mock.get(
            f"{INTUNEWIN_CONTENTS_API}?ref=v1.8.6",
            json={"name": "IntuneWinAppUtil.exe", "size": 8, "sha": "0" * 40},
        )

        with pytest.raises(NetworkError, match="no download URL"):
            _get_intunewin_tool(tmp_path / "tools", "1.8.6")

    def test_download_network_failure_is_a_network_error(self, tmp_path, requests_mock):
        """Tests that a download that cannot reach GitHub is reported."""
        _serve_tool(requests_mock, "v1.8.6")
        requests_mock.get(
            f"{_DOWNLOAD_URL_PREFIX}/v1.8.6/IntuneWinAppUtil.exe",
            exc=requests.ConnectionError("reset"),
        )

        with pytest.raises(NetworkError, match="Failed to download"):
            _get_intunewin_tool(tmp_path / "tools", "1.8.6")

    def test_lookup_sends_the_github_token(self, tmp_path, requests_mock, monkeypatch):
        """Tests that a GITHUB_TOKEN in the environment authenticates the
        lookup, since it counts against the API's unauthenticated limit."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        _serve_tool(requests_mock, "v1.8.6")

        _get_intunewin_tool(tmp_path / "tools", "1.8.6")

        lookup = next(r for r in requests_mock.request_history if "contents" in r.url)
        assert lookup.headers["Authorization"] == "Bearer ghp_test"


class TestVerifyBuildStructure:
    """Tests for build directory validation."""

    def test_verify_valid_structure(self, tmp_path):
        """Tests that a valid PSADT directory passes validation."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        # Create required structure
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        # Should not raise
        _verify_build_structure(build_dir)

    def test_verify_missing_psadt_raises(self, tmp_path):
        """Tests error when PSAppDeployToolkit directory is missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ConfigError, match="Missing.*PSAppDeployToolkit"):
            _verify_build_structure(build_dir)

    def test_verify_missing_files_raises(self, tmp_path):
        """Tests error when Files directory is missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.ps1").write_text("script")
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ConfigError, match="Missing.*Files"):
            _verify_build_structure(build_dir)

    def test_verify_missing_script_raises(self, tmp_path):
        """Tests error when Invoke-AppDeployToolkit.ps1 is missing."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "PSAppDeployToolkit").mkdir()
        (build_dir / "Files").mkdir()
        (build_dir / "Invoke-AppDeployToolkit.exe").write_bytes(b"exe")

        with pytest.raises(ConfigError, match="Missing.*Invoke-AppDeployToolkit.ps1"):
            _verify_build_structure(build_dir)


class TestExecutePackaging:
    """Tests for running the tool and finding what it wrote."""

    def _run(self, tmp_path, produced: list[str]):
        output_dir = tmp_path / "out"

        def fake_run(cmd, **kwargs):
            for name in produced:
                (output_dir / name).write_bytes(b"pkg")
            return type("Result", (), {"stdout": ""})()

        with patch("napt.build.packager.subprocess.run", side_effect=fake_run):
            return _execute_packaging(
                tmp_path / "tool.exe", tmp_path / "src", "setup.exe", output_dir
            )

    def test_the_one_file_the_tool_wrote_is_returned(self, tmp_path):
        """Tests that the package is the file the tool produced."""
        result = self._run(tmp_path, ["Invoke-AppDeployToolkit.intunewin"])

        assert result == tmp_path / "out" / "Invoke-AppDeployToolkit.intunewin"

    def test_no_output_is_an_error(self, tmp_path):
        """Tests that a tool run that produced nothing is reported."""
        with pytest.raises(PackagingError, match="no .intunewin file"):
            self._run(tmp_path, [])

    def test_more_than_one_output_is_an_error(self, tmp_path):
        """Tests that two packages in the output folder are never resolved by
        picking the newer one."""
        with pytest.raises(PackagingError, match="one .intunewin"):
            self._run(tmp_path, ["a.intunewin", "b.intunewin"])

    def test_tool_that_cannot_launch_is_an_error(self, tmp_path):
        """Tests that a tool the host cannot run (wrong platform, damaged
        file) is reported, not a traceback."""
        with patch(
            "napt.build.packager.subprocess.run",
            side_effect=OSError(8, "Exec format error"),
        ):
            with pytest.raises(PackagingError, match="Cannot run IntuneWinAppUtil"):
                _execute_packaging(
                    tmp_path / "tool.exe", tmp_path / "src", "setup.exe", tmp_path / "o"
                )


class TestCreateIntunewin:
    """Tests for .intunewin package creation."""

    @pytest.fixture(autouse=True)
    def _tool_and_execute(self):
        with (
            patch(
                "napt.build.packager._get_intunewin_tool",
                return_value=Path("tool/IntuneWinAppUtil.exe"),
            ) as get_tool,
            patch(
                "napt.build.packager._execute_packaging", side_effect=_fake_execute
            ) as execute,
        ):
            self.get_tool = get_tool
            self.execute = execute
            yield

    def test_create_intunewin_success(self, tmp_path):
        """Tests successful .intunewin creation with versioned output path."""
        build_dir = _make_build_dir(tmp_path)
        packages_dir = tmp_path / "packages"

        result = create_intunewin(build_dir, output_dir=packages_dir)

        assert result.app_id == "test-app"
        assert result.version == "1.0.0"
        assert result.status == "success"
        assert result.package_path == (
            packages_dir / "test-app" / "1.0.0" / "Invoke-AppDeployToolkit.intunewin"
        )
        assert result.package_path.read_bytes() == b"intunewin bytes"

    def test_execute_packaging_called_with_packagefiles_dir(self, tmp_path):
        """Tests that IntuneWinAppUtil runs on packagefiles/, not the version dir."""
        build_dir = _make_build_dir(tmp_path)

        create_intunewin(build_dir, output_dir=tmp_path / "packages")

        source_dir = self.execute.call_args[0][1]
        assert source_dir == build_dir.resolve() / "packagefiles"

    def test_scripts_named_by_the_manifest_are_copied(self, tmp_path):
        """Tests that the detection and requirements scripts the manifest
        names land in the package folder, and nothing else does."""
        build_dir = _make_build_dir(tmp_path, requirements=True)
        (build_dir / "Stale-Detection.ps1").write_text("stale")

        create_intunewin(build_dir, output_dir=tmp_path / "packages")

        package_dir = tmp_path / "packages" / "test-app" / "1.0.0"
        assert (package_dir / "test-app-Detection.ps1").exists()
        assert (package_dir / "test-app-Requirements.ps1").exists()
        assert not (package_dir / "Stale-Detection.ps1").exists()

    def test_script_named_by_the_manifest_but_missing_is_an_error(self, tmp_path):
        """Tests that a build whose manifest names a script that is gone
        cannot be packaged."""
        build_dir = _make_build_dir(tmp_path)
        (build_dir / "test-app-Detection.ps1").unlink()

        with pytest.raises(PackagingError, match="test-app-Detection.ps1"):
            create_intunewin(build_dir, output_dir=tmp_path / "packages")

    def test_package_manifest_records_the_intunewin(self, tmp_path):
        """Tests that the package folder's manifest names the .intunewin and
        carries its hash, for upload to verify."""
        build_dir = _make_build_dir(tmp_path)

        result = create_intunewin(build_dir, output_dir=tmp_path / "packages")

        manifest = json.loads(
            (result.package_path.parent / "build-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["intunewin_filename"] == "Invoke-AppDeployToolkit.intunewin"
        assert manifest["intunewin_sha256"] == (
            hashlib.sha256(b"intunewin bytes").hexdigest()
        )
        assert manifest["installer_sha256"] == _INSTALLER_SHA256
        assert manifest["detection_script_path"] == "test-app-Detection.ps1"

    def test_other_versions_are_left_alone(self, tmp_path):
        """Tests that packaging one version never deletes another's package."""
        build_dir = _make_build_dir(tmp_path, version="2.0.0")
        packages_dir = tmp_path / "packages"
        old_version_dir = packages_dir / "test-app" / "1.0.0"
        old_version_dir.mkdir(parents=True)
        (old_version_dir / "Invoke-AppDeployToolkit.intunewin").write_bytes(b"old")

        create_intunewin(build_dir, output_dir=packages_dir)

        assert (old_version_dir / "Invoke-AppDeployToolkit.intunewin").read_bytes() == (
            b"old"
        )
        assert (packages_dir / "test-app" / "2.0.0").exists()

    def test_own_version_folder_is_replaced_wholesale(self, tmp_path):
        """Tests that re-packaging a version leaves nothing from the earlier
        package behind."""
        build_dir = _make_build_dir(tmp_path, version="1.0.0")
        packages_dir = tmp_path / "packages"
        existing_dir = packages_dir / "test-app" / "1.0.0"
        existing_dir.mkdir(parents=True)
        (existing_dir / "Old-Name-Detection.ps1").write_text("stale")
        (existing_dir / "Invoke-AppDeployToolkit.intunewin").write_bytes(b"old")

        create_intunewin(build_dir, output_dir=packages_dir)

        assert sorted(p.name for p in existing_dir.iterdir()) == [
            "Invoke-AppDeployToolkit.intunewin",
            "build-manifest.json",
            "test-app-Detection.ps1",
        ]

    def test_failed_packaging_leaves_other_versions_intact(self, tmp_path):
        """Tests that a run that fails before producing a package has not
        removed anything the app had."""
        build_dir = _make_build_dir(tmp_path, version="2.0.0")
        packages_dir = tmp_path / "packages"
        old_version_dir = packages_dir / "test-app" / "1.0.0"
        old_version_dir.mkdir(parents=True)
        (old_version_dir / "Invoke-AppDeployToolkit.intunewin").write_bytes(b"old")
        self.get_tool.side_effect = NetworkError("rate limited")

        with pytest.raises(NetworkError):
            create_intunewin(build_dir, output_dir=packages_dir)

        assert (old_version_dir / "Invoke-AppDeployToolkit.intunewin").exists()

    def test_missing_manifest_is_an_error(self, tmp_path):
        """Tests that a build without its manifest cannot be packaged."""
        build_dir = _make_build_dir(tmp_path, manifest=False)

        with pytest.raises(ConfigError, match="build-manifest.json") as info:
            create_intunewin(build_dir, output_dir=tmp_path / "packages")
        assert "napt build" in str(info.value)

    def test_corrupt_manifest_is_an_error(self, tmp_path):
        """Tests that a manifest that is not JSON is reported, not a traceback."""
        build_dir = _make_build_dir(tmp_path)
        (build_dir / "build-manifest.json").write_text("{oops", encoding="utf-8")

        with pytest.raises(ConfigError, match="build-manifest.json"):
            create_intunewin(build_dir, output_dir=tmp_path / "packages")

    def test_manifest_that_is_not_an_object_is_an_error(self, tmp_path):
        """Tests that a manifest holding a JSON array is reported."""
        build_dir = _make_build_dir(tmp_path)
        (build_dir / "build-manifest.json").write_text("[]", encoding="utf-8")

        with pytest.raises(ConfigError, match="not a JSON object"):
            create_intunewin(build_dir, output_dir=tmp_path / "packages")

    @pytest.mark.parametrize("key", ["installer_sha256", "detection_script_path"])
    def test_manifest_missing_a_required_key_is_an_error(self, tmp_path, key):
        """Tests that a manifest without a field packaging relies on is reported."""
        build_dir = _make_build_dir(tmp_path)
        manifest_path = build_dir / "build-manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        del data[key]
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ConfigError, match=f"has no {key}"):
            create_intunewin(build_dir, output_dir=tmp_path / "packages")

    def test_installer_that_does_not_match_the_manifest_is_refused(self, tmp_path):
        """Tests that the installer inside the build is re-hashed against the
        manifest before it is packaged."""
        build_dir = _make_build_dir(tmp_path)
        (build_dir / "packagefiles" / "Files" / "setup.msi").write_bytes(b"swapped")

        with pytest.raises(PackagingError, match="does not match") as info:
            create_intunewin(build_dir, output_dir=tmp_path / "packages")
        assert "napt build" in str(info.value)

    def test_build_from_another_binary_than_recorded_is_refused(self, tmp_path):
        """Tests that a build whose installer is not the recorded release is
        refused before any packaging."""
        build_dir = _make_build_dir(tmp_path)

        with pytest.raises(PackagingError, match="recorded release"):
            create_intunewin(
                build_dir, output_dir=tmp_path / "packages", expected_sha256="b" * 64
            )
        self.execute.assert_not_called()

    def test_build_matching_the_recorded_release_is_packaged(self, tmp_path):
        """Tests that the expected hash passes when the build matches it."""
        build_dir = _make_build_dir(tmp_path)

        result = create_intunewin(
            build_dir,
            output_dir=tmp_path / "packages",
            expected_sha256=_INSTALLER_SHA256,
        )

        assert result.status == "success"

    def test_create_intunewin_invalid_structure_raises(self, tmp_path):
        """Tests error when packagefiles directory has invalid PSADT structure."""
        build_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        (build_dir / "packagefiles").mkdir(parents=True)

        with pytest.raises(ConfigError, match="Invalid PSADT build directory"):
            create_intunewin(build_dir)

    def test_create_intunewin_missing_directory_raises(self, tmp_path):
        """Tests error when build directory does not exist."""
        build_dir = tmp_path / "nonexistent" / "test-app" / "1.0.0"

        with pytest.raises(PackagingError):
            create_intunewin(build_dir)

    def test_tool_release_forwarded_to_get_tool(self, tmp_path):
        """Tests that tool_release is forwarded to _get_intunewin_tool."""
        build_dir = _make_build_dir(tmp_path)

        create_intunewin(
            build_dir, output_dir=tmp_path / "packages", tool_release="1.8.6"
        )

        _, call_release = self.get_tool.call_args[0]
        assert call_release == "1.8.6"
