"""Tests for napt.build.manifest: the record a build leaves beside itself."""

from __future__ import annotations

import json

import pytest

from napt.build.manifest import read_build_manifest, write_build_manifest
from napt.exceptions import PackagingError


def _write(tmp_path, **overrides):
    version_dir = tmp_path / "builds" / "test-app" / "1.0.0"
    build_dir = version_dir / "packagefiles"
    build_dir.mkdir(parents=True, exist_ok=True)
    fields = {
        "build_dir": build_dir,
        "app_id": "test-app",
        "app_name": "Test App",
        "version": "1.0.0",
        "build_types": "both",
        "architecture": "x64",
        "installer_sha256": "a" * 64,
        "detection_script_path": version_dir / "Test-App_1.0.0-Detection.ps1",
        "requirements_script_path": None,
    }
    fields.update(overrides)
    return write_build_manifest(**fields)


class TestWriteBuildManifest:
    """Tests for build manifest generation."""

    def test_write_failure_is_a_packaging_error(self, tmp_path):
        """Tests that a manifest the file system refuses to write is reported
        by path, not as an OSError traceback."""
        version_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        (version_dir / "packagefiles").mkdir(parents=True)
        (version_dir / "build-manifest.json").mkdir()

        with pytest.raises(PackagingError, match="build-manifest.json"):
            _write(tmp_path)

    def test_manifest_contains_required_fields(self, tmp_path):
        """Tests that the manifest records what package and upload read."""
        version_dir = tmp_path / "builds" / "test-app" / "1.0.0"
        result = _write(
            tmp_path,
            requirements_script_path=version_dir / "Test-App_1.0.0-Requirements.ps1",
        )

        assert result == version_dir / "build-manifest.json"
        manifest = json.loads(result.read_text(encoding="utf-8"))
        assert manifest == {
            "app_id": "test-app",
            "app_name": "Test App",
            "version": "1.0.0",
            "win32_build_types": "both",
            "architecture": "x64",
            "installer_sha256": "a" * 64,
            "detection_script_path": "Test-App_1.0.0-Detection.ps1",
            "requirements_script_path": "Test-App_1.0.0-Requirements.ps1",
        }

    def test_manifest_without_requirements_script(self, tmp_path):
        """Tests that app_only builds record no requirements script."""
        result = _write(tmp_path, build_types="app_only")

        manifest = json.loads(result.read_text(encoding="utf-8"))
        assert manifest["win32_build_types"] == "app_only"
        assert "requirements_script_path" not in manifest

    def test_manifest_is_written_like_the_package_copy(self, tmp_path):
        """Tests that the file ends with a newline and is indented, the same
        shape 'napt package' rewrites it in."""
        result = _write(tmp_path)

        text = result.read_text(encoding="utf-8")
        assert text.endswith("}\n")
        assert text.startswith("{\n  ")

    def test_manifest_replaces_an_existing_file_atomically(self, tmp_path):
        """Tests that an earlier manifest is replaced, with no temp file left."""
        _write(tmp_path, version="1.0.0")
        version_dir = tmp_path / "builds" / "test-app" / "1.0.0"

        _write(tmp_path, app_name="Renamed")

        assert (
            json.loads(
                (version_dir / "build-manifest.json").read_text(encoding="utf-8")
            )["app_name"]
            == "Renamed"
        )
        assert sorted(p.name for p in version_dir.iterdir()) == [
            "build-manifest.json",
            "packagefiles",
        ]


class TestReadBuildManifest:
    """Tests for reading a manifest back with the keys a stage relies on."""

    REQUIRED = ("installer_sha256", "detection_script_path")
    REMEDY = "Run 'napt build' to create the build again."

    def test_round_trip(self, tmp_path):
        """Tests that a written manifest reads back whole."""
        result = _write(tmp_path)

        manifest = read_build_manifest(result.parent, self.REQUIRED, self.REMEDY)

        assert manifest["installer_sha256"] == "a" * 64
        assert manifest["app_name"] == "Test App"

    def test_missing_manifest_names_the_remedy(self, tmp_path):
        """Tests that a build without its manifest says how to get one."""
        with pytest.raises(PackagingError, match="build-manifest.json") as info:
            read_build_manifest(tmp_path, self.REQUIRED, self.REMEDY)
        assert self.REMEDY in str(info.value)

    def test_corrupt_manifest_is_a_packaging_error(self, tmp_path):
        """Tests that a manifest that is not JSON is reported, not a traceback."""
        (tmp_path / "build-manifest.json").write_text("{oops", encoding="utf-8")

        with pytest.raises(PackagingError, match="build-manifest.json"):
            read_build_manifest(tmp_path, self.REQUIRED, self.REMEDY)

    def test_manifest_that_is_not_an_object_is_a_packaging_error(self, tmp_path):
        """Tests that a manifest holding a JSON array is reported."""
        (tmp_path / "build-manifest.json").write_text("[]", encoding="utf-8")

        with pytest.raises(PackagingError, match="not a JSON object"):
            read_build_manifest(tmp_path, self.REQUIRED, self.REMEDY)

    @pytest.mark.parametrize("key", REQUIRED)
    def test_missing_required_key_is_a_packaging_error(self, tmp_path, key):
        """Tests that a manifest lacking a key the caller named is reported."""
        result = _write(tmp_path)
        data = json.loads(result.read_text(encoding="utf-8"))
        del data[key]
        result.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(PackagingError, match=f"has no {key}"):
            read_build_manifest(result.parent, self.REQUIRED, self.REMEDY)
