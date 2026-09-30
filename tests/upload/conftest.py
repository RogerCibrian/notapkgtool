"""Shared fixtures and helpers for upload tests."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from napt.upload.intunewin import DETECTION_XML_PATH, ENCRYPTED_PAYLOAD_PATH

_DETECTION_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<ApplicationInfo>
    <FileName>IntunePackage.intunewin</FileName>
    <UnencryptedContentSize>12345</UnencryptedContentSize>
    <EncryptionInfo>
        <EncryptionKey>dGVzdGVuY3J5cHRpb25rZXk=</EncryptionKey>
        <MacKey>dGVzdG1hY2tleQ==</MacKey>
        <InitializationVector>dGVzdGl2</InitializationVector>
        <Mac>dGVzdG1hYw==</Mac>
        <ProfileIdentifier>ProfileVersion1</ProfileIdentifier>
        <FileDigest>dGVzdGRpZ2VzdA==</FileDigest>
        <FileDigestAlgorithm>SHA256</FileDigestAlgorithm>
    </EncryptionInfo>
</ApplicationInfo>
"""


def make_intunewin_bytes(xml: str = _DETECTION_XML) -> bytes:
    """Build a minimal valid .intunewin ZIP as bytes.

    Args:
        xml: Detection.xml content to embed. Defaults to valid XML with
            all required fields.

    Returns:
        Raw bytes of a ZIP file with Detection.xml and a fake encrypted payload.

    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(DETECTION_XML_PATH, xml)
        zf.writestr(ENCRYPTED_PAYLOAD_PATH, b"fake-encrypted-payload")
    return buf.getvalue()


def make_package_dir(
    tmp_path: Path,
    app_id: str = "test-app",
    version: str = "1.0.0",
    installer_sha256: str = "a" * 64,
    build_types: str = "both",
    manifest_overrides: dict | None = None,
) -> Path:
    """Create a fake package directory the way 'napt package' lays it out.

    The manifest names the .intunewin file, the scripts, and the hash of the
    .intunewin as written, since upload resolves everything through it.

    Args:
        tmp_path: Base directory (typically pytest's tmp_path).
        app_id: App identifier used in the directory path.
        version: Version string used in the directory path.
        installer_sha256: Installer hash written to the build manifest.
        build_types: The build_types the package was built with.
        manifest_overrides: Fields merged over the manifest before writing.

    Returns:
        Path to the version directory (packages/{app_id}/{version}/).

    """
    pkg_dir = tmp_path / "packages" / app_id / version
    pkg_dir.mkdir(parents=True)
    intunewin = make_intunewin_bytes()
    (pkg_dir / "Invoke-AppDeployToolkit.intunewin").write_bytes(intunewin)
    manifest = {
        "app_id": app_id,
        "version": version,
        "architecture": "x64",
        "installer_sha256": installer_sha256,
        "win32_build_types": build_types,
        "detection_script_path": f"{app_id}-Detection.ps1",
        "intunewin_filename": "Invoke-AppDeployToolkit.intunewin",
        "intunewin_sha256": hashlib.sha256(intunewin).hexdigest(),
    }
    if build_types != "app_only":
        manifest["requirements_script_path"] = f"{app_id}-Requirements.ps1"
    manifest.update(manifest_overrides or {})
    (pkg_dir / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pkg_dir / f"{app_id}-Detection.ps1").write_text("# detection", encoding="utf-8")
    if build_types != "app_only":
        (pkg_dir / f"{app_id}-Requirements.ps1").write_text(
            "# requirements", encoding="utf-8"
        )
    return pkg_dir


@pytest.fixture
def fake_intunewin(tmp_path: Path) -> Path:
    """Write a minimal .intunewin file to tmp_path and return its path."""
    path = tmp_path / "Invoke-AppDeployToolkit.intunewin"
    path.write_bytes(make_intunewin_bytes())
    return path
