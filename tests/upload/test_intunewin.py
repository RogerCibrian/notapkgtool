"""Tests for napt.upload.intunewin."""

from __future__ import annotations

from pathlib import Path

import pytest

from napt.exceptions import PackagingError
from napt.upload.intunewin import extract_encrypted_payload, parse_intunewin
from tests.upload.conftest import _DETECTION_XML, make_intunewin_bytes


def test_parse_intunewin_returns_all_fields(fake_intunewin: Path) -> None:
    """Tests that parse_intunewin extracts all metadata fields from Detection.xml."""
    metadata = parse_intunewin(fake_intunewin)

    assert metadata.encrypted_file_name == "IntunePackage.intunewin"
    assert metadata.unencrypted_content_size == 12345
    assert metadata.encryption_key == "dGVzdGVuY3J5cHRpb25rZXk="
    assert metadata.mac_key == "dGVzdG1hY2tleQ=="
    assert metadata.init_vector == "dGVzdGl2"
    assert metadata.mac == "dGVzdG1hYw=="
    assert metadata.profile_identifier == "ProfileVersion1"
    assert metadata.file_digest == "dGVzdGRpZ2VzdA=="
    assert metadata.file_digest_algorithm == "SHA256"
    assert metadata.encrypted_file_size > 0


def test_parse_intunewin_not_a_zip_raises_packaging_error(tmp_path: Path) -> None:
    """Tests that a non-ZIP file raises PackagingError."""
    bad = tmp_path / "bad.intunewin"
    bad.write_bytes(b"not a zip file")

    with pytest.raises(PackagingError, match="invalid ZIP archive"):
        parse_intunewin(bad)


def test_parse_intunewin_missing_encryption_key_raises_packaging_error(
    tmp_path: Path,
) -> None:
    """Tests that a missing EncryptionKey field raises PackagingError."""
    xml = _DETECTION_XML.replace(
        "<EncryptionKey>dGVzdGVuY3J5cHRpb25rZXk=</EncryptionKey>", ""
    )
    path = tmp_path / "app.intunewin"
    path.write_bytes(make_intunewin_bytes(xml))

    with pytest.raises(PackagingError, match="EncryptionKey"):
        parse_intunewin(path)


def test_extract_encrypted_payload_returns_extracted_path(
    fake_intunewin: Path, tmp_path: Path
) -> None:
    """Tests that extract_encrypted_payload extracts the payload and returns its path."""
    dest = tmp_path / "out"
    dest.mkdir()

    result = extract_encrypted_payload(fake_intunewin, dest)

    assert result.exists()
    assert result.read_bytes() == b"fake-encrypted-payload"


def test_extract_encrypted_payload_not_a_zip_raises_packaging_error(
    tmp_path: Path,
) -> None:
    """Tests that a non-ZIP file raises PackagingError on extract."""
    bad = tmp_path / "bad.intunewin"
    bad.write_bytes(b"not a zip file")
    dest = tmp_path / "out"
    dest.mkdir()

    with pytest.raises(PackagingError, match="invalid ZIP archive"):
        extract_encrypted_payload(bad, dest)
