"""
Tests for notapkgtool.io.download module.

Tests download functionality including:
- Basic downloads
- Redirects
- Content-Disposition headers
- Checksum validation
- Atomic writes
- Conditional requests (ETags)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import requests_mock

from notapkgtool.io.download import NotModifiedError, download_file


def _sha256(data: bytes) -> str:
    """Helper to compute SHA-256 hash."""
    return hashlib.sha256(data).hexdigest()


def test_download_success(tmp_test_dir: Path) -> None:
    """Test basic successful download."""
    url = "https://example.com/file.bin"
    data = b"hello world"

    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        path, digest, headers = download_file(url, tmp_test_dir)

    assert path.exists()
    assert path.read_bytes() == data
    assert digest == _sha256(data)
    assert "Content-Length" in headers


def test_follows_redirect_and_uses_final_url_name(tmp_test_dir: Path) -> None:
    """Test that redirects are followed and final URL name is used."""
    start = "https://example.com/start"
    final = "https://cdn.example.com/payload.pkg"

    with requests_mock.Mocker() as m:
        # 302 redirect to final URL
        m.get(start, status_code=302, headers={"Location": final})
        m.get(final, content=b"abc", headers={"Content-Length": "3"})
        path, _, _ = download_file(start, tmp_test_dir)

    assert path.name == "payload.pkg"
    assert path.read_bytes() == b"abc"


def test_content_disposition_filename(tmp_test_dir: Path) -> None:
    """Test that Content-Disposition header overrides URL filename."""
    url = "https://example.com/dl"
    data = b"abc"

    with requests_mock.Mocker() as m:
        m.get(
            url,
            content=data,
            headers={
                "Content-Disposition": 'attachment; filename="thing.msi"',
                "Content-Length": str(len(data)),
            },
        )
        path, _, _ = download_file(url, tmp_test_dir)

    assert path.name == "thing.msi"
    assert path.read_bytes() == data


def test_checksum_mismatch_raises_and_cleans_file(tmp_test_dir: Path) -> None:
    """Test that checksum mismatches raise error and clean up file."""
    url = "https://example.com/file.bin"

    with requests_mock.Mocker() as m:
        m.get(url, content=b"wrong", headers={"Content-Length": "5"})

        from notapkgtool.exceptions import NetworkError

        with pytest.raises(NetworkError, match="sha256 mismatch"):
            download_file(url, tmp_test_dir, expected_sha256="00" * 32)

    # Ensure file was removed after mismatch
    assert not (tmp_test_dir / "file.bin").exists()


def test_checksum_validation_success(tmp_test_dir: Path) -> None:
    """Test that correct checksum validation passes."""
    url = "https://example.com/file.bin"
    data = b"correct content"
    expected_hash = _sha256(data)

    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        path, digest, _ = download_file(
            url, tmp_test_dir, expected_sha256=expected_hash
        )

    assert path.exists()
    assert digest == expected_hash


def test_rejects_html_when_validate_content_type(tmp_test_dir: Path) -> None:
    """Test that HTML is rejected when content type validation is enabled."""
    url = "https://example.com/file"

    with requests_mock.Mocker() as m:
        m.get(url, text="<html>oops</html>", headers={"Content-Type": "text/html"})

        from notapkgtool.exceptions import ConfigError

        with pytest.raises(ConfigError, match="expected binary"):
            download_file(url, tmp_test_dir, validate_content_type=True)


def test_writes_atomically_no_part_leftovers(tmp_test_dir: Path) -> None:
    """Test that atomic writes don't leave .part files behind."""
    url = "https://example.com/file.bin"

    with requests_mock.Mocker() as m:
        m.get(url, content=b"x" * 10, headers={"Content-Length": "10"})
        path, _, _ = download_file(url, tmp_test_dir)

    # No .part files should remain after successful download
    leftovers = list(tmp_test_dir.glob("*.part"))
    assert leftovers == []
    assert path.exists()


def test_conditional_request_with_etag_not_modified(tmp_test_dir: Path) -> None:
    """Test that ETag causes NotModifiedError on 304 response."""
    url = "https://example.com/file.bin"
    etag = '"abc123"'

    with requests_mock.Mocker() as m:
        m.get(url, status_code=304)

        with pytest.raises(NotModifiedError, match="HTTP 304"):
            download_file(url, tmp_test_dir, etag=etag)


def test_conditional_request_with_last_modified_not_modified(
    tmp_test_dir: Path,
) -> None:
    """Test that Last-Modified causes NotModifiedError on 304 response."""
    url = "https://example.com/file.bin"
    last_modified = "Mon, 01 Jan 2024 00:00:00 GMT"

    with requests_mock.Mocker() as m:
        m.get(url, status_code=304)

        with pytest.raises(NotModifiedError, match="HTTP 304"):
            download_file(url, tmp_test_dir, last_modified=last_modified)


def test_conditional_request_modified_downloads(tmp_test_dir: Path) -> None:
    """Test that conditional request downloads when content is modified."""
    url = "https://example.com/file.bin"
    data = b"new content"
    etag = '"old_etag"'

    with requests_mock.Mocker() as m:
        # Server returns 200 with new content and new ETag
        m.get(
            url,
            content=data,
            headers={"Content-Length": str(len(data)), "ETag": '"new_etag"'},
        )
        path, digest, headers = download_file(url, tmp_test_dir, etag=etag)

    assert path.exists()
    assert path.read_bytes() == data
    assert headers.get("ETag") == '"new_etag"'


def test_creates_destination_folder(tmp_test_dir: Path) -> None:
    """Test that destination folder is created if it doesn't exist."""
    url = "https://example.com/file.bin"
    nested_dir = tmp_test_dir / "nested" / "path"
    data = b"test"

    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        path, _, _ = download_file(url, nested_dir)

    assert nested_dir.exists()
    assert path.exists()
    assert path.parent == nested_dir
