"""Shared fixtures and helpers for upload tests."""

from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest

from napt.upload.intunewin import (
    DETECTION_XML_PATH,
    ENCRYPTED_PAYLOAD_PATH,
    IntunewinMetadata,
)

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
) -> Path:
    """Create a minimal fake package directory for upload tests.

    Args:
        tmp_path: Base directory (typically pytest's tmp_path).
        app_id: App identifier used in the directory path.
        version: Version string used in the directory path.

    Returns:
        Path to the version directory (packages/{app_id}/{version}/).

    """
    pkg_dir = tmp_path / "packages" / app_id / version
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "Invoke-AppDeployToolkit.intunewin").write_bytes(make_intunewin_bytes())
    (pkg_dir / "build-manifest.json").write_text(
        json.dumps({"architecture": "x64"}), encoding="utf-8"
    )
    (pkg_dir / f"{app_id}-Detection.ps1").write_text("# detection", encoding="utf-8")
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


@pytest.fixture
def fake_metadata() -> IntunewinMetadata:
    """Return a sample IntunewinMetadata for use in graph and manager tests."""
    return IntunewinMetadata(
        encrypted_file_name="IntunePackage.intunewin",
        unencrypted_content_size=12345,
        file_digest="dGVzdGRpZ2VzdA==",
        file_digest_algorithm="SHA256",
        encryption_key="dGVzdGVuY3J5cHRpb25rZXk=",
        mac_key="dGVzdG1hY2tleQ==",
        init_vector="dGVzdGl2",
        mac="dGVzdG1hYw==",
        profile_identifier="ProfileVersion1",
        encrypted_file_size=22,
    )
