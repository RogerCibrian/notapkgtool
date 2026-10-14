"""Tests for napt.build.installer: finding the installer and reading it once."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from napt.build.installer import (
    InstallerInfo,
    find_installer_file,
    inspect_installer,
    release_to_build,
)
from napt.exceptions import ConfigError, PackagingError, StateError
from napt.versioning.msi import MSIMetadata
from napt.versioning.msix import MSIXMetadata


def _sha256(data: bytes) -> str:
    """Returns the SHA-256 hex digest of the given bytes."""
    return hashlib.sha256(data).hexdigest()


def _write_state(
    state_dir: Path,
    app_id: str,
    pending: dict | None = None,
    published: dict | None = None,
) -> None:
    """Writes a deployment state file with the given releases."""
    deployment_dir = state_dir / "deployment"
    deployment_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "schemaVersion": 1,
        "published": published,
        "pending": pending,
        "rings": {},
        "retained": [],
    }
    (deployment_dir / f"{app_id}.json").write_text(json.dumps(state))


def _save_download(downloads_dir: Path, app_id: str, version: str, name: str) -> bytes:
    """Saves a fake installer where discover would and returns its content."""
    content = f"{name} {version}".encode()
    version_dir = downloads_dir / app_id / version
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / name).write_bytes(content)
    return content


def _installer(tmp_path: Path, version: str, name: str) -> Path:
    """Saves a fake installer under downloads/<id>/<version>/ and returns it."""
    _save_download(tmp_path / "downloads", "napt-app", version, name)
    return tmp_path / "downloads" / "napt-app" / version / name


def _msi(product_name="7-Zip", product_version="26.02.00.0", architecture="x64"):
    return MSIMetadata(
        product_name=product_name,
        product_version=product_version,
        architecture=architecture,
    )


def _msix(display_name="App", version="4.41.105.0", architecture="x64"):
    return MSIXMetadata(
        display_name=display_name,
        version=version,
        architecture=architecture,
        identity_name="Vendor.App",
    )


class TestReleaseToBuild:
    """Tests for choosing the release to build from deployment state."""

    PENDING = {"version": "2.0", "sha256": "bb", "url": "https://example.com/b"}
    PUBLISHED = {"version": "1.0", "sha256": "aa"}

    @staticmethod
    def _config(tmp_path: Path) -> dict:
        return {"id": "napt-app", "directories": {"state": str(tmp_path / "state")}}

    def test_pending_release_wins(self, tmp_path):
        """Tests that the pending release is built when one is recorded."""
        _write_state(tmp_path / "state", "napt-app", self.PENDING, self.PUBLISHED)

        assert release_to_build(self._config(tmp_path)) == self.PENDING

    def test_published_release_is_used_when_nothing_is_pending(self, tmp_path):
        """Tests that the published release is rebuilt when nothing is pending."""
        _write_state(tmp_path / "state", "napt-app", published=self.PUBLISHED)

        assert release_to_build(self._config(tmp_path)) == self.PUBLISHED

    def test_no_state_returns_none(self, tmp_path):
        """Tests that a missing state file yields no release."""
        assert release_to_build(self._config(tmp_path)) is None

    def test_state_dir_names_the_state_root(self, tmp_path):
        """Tests that --state-dir reads <dir>/deployment/, like the other commands."""
        _write_state(tmp_path / "custom", "napt-app", self.PENDING, self.PUBLISHED)
        # The configured location holds a different release; it must be ignored.
        _write_state(tmp_path / "state", "napt-app", published=self.PUBLISHED)

        release = release_to_build(self._config(tmp_path), tmp_path / "custom")

        assert release == self.PENDING


class TestFindInstallerFile:
    """Tests for finding the installer to build."""

    def test_finds_the_recorded_release_by_hash(self, tmp_path):
        """Tests that the file in the version folder with the recorded hash wins."""
        downloads_dir = tmp_path / "downloads"
        content = _save_download(downloads_dir, "napt-app", "2.0", "setup.exe")
        release = {"version": "2.0", "sha256": _sha256(content)}

        path, digest = find_installer_file(downloads_dir, "napt-app", release)

        assert path == downloads_dir / "napt-app" / "2.0" / "setup.exe"
        assert digest == release["sha256"]

    def test_ignores_other_versions_with_the_same_filename(self, tmp_path):
        """Tests that a newer download under the same name is not picked."""
        downloads_dir = tmp_path / "downloads"
        approved = _save_download(downloads_dir, "napt-app", "1.0", "setup.msi")
        _save_download(downloads_dir, "napt-app", "2.0", "setup.msi")
        release = {"version": "1.0", "sha256": _sha256(approved)}

        path, _digest = find_installer_file(downloads_dir, "napt-app", release)

        assert path == downloads_dir / "napt-app" / "1.0" / "setup.msi"

    def test_picks_the_matching_file_when_a_folder_holds_several(self, tmp_path):
        """Tests that a same-version re-release is told apart by hash."""
        downloads_dir = tmp_path / "downloads"
        _save_download(downloads_dir, "napt-app", "2.0", "setup-a.exe")
        wanted = _save_download(downloads_dir, "napt-app", "2.0", "setup-b.exe")
        release = {"version": "2.0", "sha256": _sha256(wanted)}

        path, _digest = find_installer_file(downloads_dir, "napt-app", release)

        assert path.name == "setup-b.exe"

    def test_changed_file_is_refused(self, tmp_path):
        """Tests that a file whose content changed since discovery is refused."""
        downloads_dir = tmp_path / "downloads"
        content = _save_download(downloads_dir, "napt-app", "2.0", "setup.exe")
        release = {"version": "2.0", "sha256": _sha256(content)}
        (downloads_dir / "napt-app" / "2.0" / "setup.exe").write_bytes(b"tampered")

        with pytest.raises(PackagingError, match="matches the recorded release"):
            find_installer_file(downloads_dir, "napt-app", release)

    def test_recorded_version_cannot_point_outside_the_app_folder(self, tmp_path):
        """Tests that an edited state file cannot steer build to another folder."""
        downloads_dir = tmp_path / "downloads"
        # A real file outside the app's folder, with a hash the state could name.
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "payload.exe").write_bytes(b"not the app")
        (downloads_dir / "napt-app").mkdir(parents=True)
        release = {"version": "../../elsewhere", "sha256": _sha256(b"not the app")}

        with pytest.raises(StateError, match="cannot be used as a folder name"):
            find_installer_file(downloads_dir, "napt-app", release)

    def test_missing_version_folder_says_to_run_discover(self, tmp_path):
        """Tests that an undownloaded release points the user at discover."""
        release = {"version": "2.0", "sha256": "ab" * 32}

        with pytest.raises(PackagingError, match="Run 'napt discover'"):
            find_installer_file(tmp_path / "downloads", "napt-app", release)

    def test_partial_download_is_not_a_candidate(self, tmp_path):
        """Tests that a leftover .part file is never hashed or returned."""
        downloads_dir = tmp_path / "downloads"
        content = _save_download(downloads_dir, "napt-app", "2.0", "setup.exe.part")
        release = {"version": "2.0", "sha256": _sha256(content)}

        with pytest.raises(PackagingError, match="matches the recorded release"):
            find_installer_file(downloads_dir, "napt-app", release)

    def test_recorded_release_applies_the_same_file_type_rule(self, tmp_path):
        """Tests that a recorded release only ever resolves to a file NAPT can
        build, the same rule the stateless lookup applies."""
        downloads_dir = tmp_path / "downloads"
        content = _save_download(downloads_dir, "napt-app", "2.0", "bundle.zip")
        release = {"version": "2.0", "sha256": _sha256(content)}

        with pytest.raises(PackagingError, match="matches the recorded release"):
            find_installer_file(downloads_dir, "napt-app", release)

    def test_no_recorded_release_uses_the_single_installer(self, tmp_path):
        """Tests that a stateless download is found when it is the only one."""
        downloads_dir = tmp_path / "downloads"
        content = _save_download(downloads_dir, "napt-app", "2.0", "setup.msix")

        path, digest = find_installer_file(downloads_dir, "napt-app", None)

        assert path == downloads_dir / "napt-app" / "2.0" / "setup.msix"
        assert digest == _sha256(content)

    def test_no_recorded_release_and_several_installers_lists_them(self, tmp_path):
        """Tests that an ambiguous stateless build stops and names the files."""
        downloads_dir = tmp_path / "downloads"
        _save_download(downloads_dir, "napt-app", "1.0", "setup.exe")
        _save_download(downloads_dir, "napt-app", "2.0", "setup.exe")

        with pytest.raises(PackagingError, match="more than one installer") as err:
            find_installer_file(downloads_dir, "napt-app", None)

        assert "1.0" in str(err.value) and "2.0" in str(err.value)

    def test_no_recorded_release_and_no_installer_raises(self, tmp_path):
        """Tests that an empty download folder points the user at discover."""
        with pytest.raises(PackagingError, match="No installer found"):
            find_installer_file(tmp_path / "downloads", "napt-app", None)

    def test_no_recorded_release_ignores_a_leftover_incoming_download(self, tmp_path):
        """Tests that a download stranded by an interrupted discover is skipped."""
        downloads_dir = tmp_path / "downloads"
        _save_download(downloads_dir, "napt-app", ".incoming", "setup.exe")
        _save_download(downloads_dir, "napt-app", "2.0", "setup.exe")

        path, _digest = find_installer_file(downloads_dir, "napt-app", None)

        assert path == downloads_dir / "napt-app" / "2.0" / "setup.exe"

    def test_no_recorded_release_and_only_a_leftover_download_raises(self, tmp_path):
        """Tests that a stranded download alone is never treated as the installer."""
        downloads_dir = tmp_path / "downloads"
        _save_download(downloads_dir, "napt-app", ".incoming", "setup.exe")

        with pytest.raises(PackagingError, match="No installer found"):
            find_installer_file(downloads_dir, "napt-app", None)


def _exe_config(make_config, **detection):
    return make_config(
        {
            "id": "napt-app",
            "name": "App",
            "psadt": {"install": "Start-ADTProcess", "uninstall": "Remove"},
            "intune": {"detection": detection},
        }
    )


class TestInspectInstaller:
    """Tests for reading the installer once and resolving what the build needs."""

    @pytest.fixture(autouse=True)
    def _verbose_logger(self):
        """Installs a visible logger and restores the default afterward."""
        from napt.logging import get_global_logger, get_logger, set_global_logger

        previous = get_global_logger()
        set_global_logger(get_logger(verbose=True))
        yield
        set_global_logger(previous)

    def test_exe_takes_the_download_folder_version(self, tmp_path, make_config):
        """Tests that an EXE takes the version discover filed it under."""
        installer = _installer(tmp_path, "26.02", "7z2602-x64.exe")
        config = _exe_config(make_config, display_name="7-Zip", architecture="x64")

        info = inspect_installer(installer, "a" * 64, config)

        assert info == InstallerInfo(
            path=installer,
            sha256="a" * 64,
            version="26.02",
            app_name="7-Zip",
            architecture="x64",
            msi=None,
            msix=None,
        )
        assert info.kind == ".exe"

    def test_msi_metadata_is_read_once(self, tmp_path, make_config):
        """Tests that one build launches one metadata read per MSI."""
        installer = _installer(tmp_path, "26.02.00.0", "7z2602-x64.msi")
        config = make_config({"id": "napt-app", "name": "App"})

        with patch(
            "napt.build.installer.extract_msi_metadata", return_value=_msi()
        ) as extract:
            info = inspect_installer(installer, "a" * 64, config)

        assert extract.call_count == 1
        assert info.version == "26.02.00.0"
        assert info.app_name == "7-Zip"
        assert info.architecture == "x64"
        assert info.msi == _msi()
        assert info.kind == ".msi"

    def test_msix_metadata_is_read_once(self, tmp_path, make_config):
        """Tests that one build parses one manifest per MSIX."""
        installer = _installer(tmp_path, "4.41.105.0", "app.msix")
        config = make_config({"id": "napt-app", "name": "App"})

        with patch(
            "napt.build.installer.extract_msix_metadata", return_value=_msix()
        ) as extract:
            info = inspect_installer(installer, "a" * 64, config)

        assert extract.call_count == 1
        assert info.app_name == "App"
        assert info.msix == _msix()
        assert info.kind == ".msix"

    def test_msi_in_the_wrong_folder_is_refused(self, tmp_path, make_config):
        """Tests that an MSI whose version differs from its folder stops the build."""
        installer = _installer(tmp_path, "26.02", "7z2602-x64.msi")
        config = make_config({"id": "napt-app", "name": "App"})

        with patch("napt.build.installer.extract_msi_metadata", return_value=_msi()):
            with pytest.raises(PackagingError, match="reports version 26.02.00.0"):
                inspect_installer(installer, "a" * 64, config)

    def test_msix_in_the_wrong_folder_is_refused(self, tmp_path, make_config):
        """Tests that an MSIX whose version differs from its folder stops the build."""
        installer = _installer(tmp_path, "4.41.105", "app.msix")
        config = make_config({"id": "napt-app", "name": "App"})

        with patch("napt.build.installer.extract_msix_metadata", return_value=_msix()):
            with pytest.raises(PackagingError, match="reports version 4.41.105.0"):
                inspect_installer(installer, "a" * 64, config)

    def test_ignored_fields_are_warned_about_once(self, tmp_path, make_config, capsys):
        """Tests that each recipe field an MSI build ignores draws one warning."""
        installer = _installer(tmp_path, "26.02.00.0", "7z2602-x64.msi")
        config = make_config(
            {
                "id": "napt-app",
                "name": "App",
                "intune": {"detection": {"display_name": "X", "architecture": "x86"}},
            }
        )

        with patch("napt.build.installer.extract_msi_metadata", return_value=_msi()):
            inspect_installer(installer, "a" * 64, config)

        out = capsys.readouterr().out
        assert (
            out.count("intune.detection.display_name is set but will be ignored") == 1
        )
        assert (
            out.count("intune.detection.architecture is set but will be ignored") == 1
        )

    def test_msi_display_name_override(self, tmp_path, make_config):
        """Tests that override_msi_display_name uses the recipe's name with the
        version substituted."""
        installer = _installer(tmp_path, "26.02.00.0", "7z2602-x64.msi")
        config = make_config(
            {
                "id": "napt-app",
                "name": "App",
                "intune": {
                    "detection": {
                        "display_name": "7-Zip {{discovered_version}}",
                        "override_msi_display_name": True,
                    }
                },
            }
        )

        with patch("napt.build.installer.extract_msi_metadata", return_value=_msi()):
            info = inspect_installer(installer, "a" * 64, config)

        assert info.app_name == "7-Zip 26.02.00.0"

    def test_override_without_display_name_is_a_config_error(
        self, tmp_path, make_config
    ):
        """Tests that the override flag without a name to use is refused."""
        installer = _installer(tmp_path, "26.02.00.0", "7z2602-x64.msi")
        config = make_config(
            {
                "id": "napt-app",
                "name": "App",
                "intune": {"detection": {"override_msi_display_name": True}},
            }
        )

        with patch("napt.build.installer.extract_msi_metadata", return_value=_msi()):
            with pytest.raises(ConfigError, match="display_name is not set"):
                inspect_installer(installer, "a" * 64, config)

    def test_msi_without_product_name_is_a_packaging_error(self, tmp_path, make_config):
        """Tests that an installer lacking the name detection needs is an
        installer problem, not a recipe problem."""
        installer = _installer(tmp_path, "26.02.00.0", "7z2602-x64.msi")
        config = make_config({"id": "napt-app", "name": "App"})

        with patch(
            "napt.build.installer.extract_msi_metadata",
            return_value=_msi(product_name=""),
        ):
            with pytest.raises(PackagingError, match="ProductName"):
                inspect_installer(installer, "a" * 64, config)

    def test_exe_without_display_name_is_a_config_error(self, tmp_path, make_config):
        """Tests that an EXE recipe must name what the detection script looks for."""
        installer = _installer(tmp_path, "26.02", "7z2602-x64.exe")
        config = _exe_config(make_config, architecture="x64")

        with pytest.raises(ConfigError, match="display_name is required"):
            inspect_installer(installer, "a" * 64, config)

    def test_exe_without_architecture_is_a_config_error(self, tmp_path, make_config):
        """Tests that an EXE recipe must say which registry view to check."""
        installer = _installer(tmp_path, "26.02", "7z2602-x64.exe")
        config = _exe_config(make_config, display_name="7-Zip")

        with pytest.raises(ConfigError, match="architecture is required"):
            inspect_installer(installer, "a" * 64, config)

    def test_exe_without_scripts_is_a_config_error(self, tmp_path, make_config):
        """Tests that an EXE recipe must supply install and uninstall commands."""
        installer = _installer(tmp_path, "26.02", "7z2602-x64.exe")
        config = make_config(
            {
                "id": "napt-app",
                "name": "App",
                "psadt": {"install": "   ", "uninstall": ""},
                "intune": {
                    "detection": {"display_name": "7-Zip", "architecture": "x64"}
                },
            }
        )

        with pytest.raises(
            ConfigError, match=r"psadt\.install and psadt\.uninstall required"
        ):
            inspect_installer(installer, "a" * 64, config)

    def test_exe_display_name_substitutes_the_version(self, tmp_path, make_config):
        """Tests that {{discovered_version}} in display_name is filled in."""
        installer = _installer(tmp_path, "26.02", "7z2602-x64.exe")
        config = _exe_config(
            make_config, display_name="7-Zip {{discovered_version}}", architecture="any"
        )

        info = inspect_installer(installer, "a" * 64, config)

        assert info.app_name == "7-Zip 26.02"
        assert info.architecture == "any"

    def test_override_flag_on_exe_warns(self, tmp_path, make_config, capsys):
        """Tests that override_msi_display_name on a non-MSI draws a warning."""
        installer = _installer(tmp_path, "26.02", "7z2602-x64.exe")
        config = _exe_config(
            make_config,
            display_name="7-Zip",
            architecture="x64",
            override_msi_display_name=True,
        )

        inspect_installer(installer, "a" * 64, config)

        assert "override_msi_display_name is set but will" in capsys.readouterr().out

    def test_control_characters_in_name_are_removed_with_a_warning(
        self, tmp_path, make_config, capsys
    ):
        """Tests that a line break in an installer's name never reaches a script."""
        installer = _installer(tmp_path, "1.0.0.0", "app.msix")
        config = make_config({"id": "napt-app", "name": "App"})

        with patch(
            "napt.build.installer.extract_msix_metadata",
            return_value=_msix(display_name="Contoso\r\nViewer", version="1.0.0.0"),
        ):
            info = inspect_installer(installer, "a" * 64, config)

        assert info.app_name == "Contoso Viewer"
        assert "contains control characters" in capsys.readouterr().out

    def test_clean_name_passes_through_silently(self, tmp_path, make_config, capsys):
        """Tests that an ordinary name is used as is, with no warning."""
        installer = _installer(tmp_path, "1.0.0.0", "app.msix")
        config = make_config({"id": "napt-app", "name": "App"})

        with patch(
            "napt.build.installer.extract_msix_metadata",
            return_value=_msix(display_name="Café Viewer™", version="1.0.0.0"),
        ):
            info = inspect_installer(installer, "a" * 64, config)

        assert info.app_name == "Café Viewer™"
        assert "control characters" not in capsys.readouterr().out
