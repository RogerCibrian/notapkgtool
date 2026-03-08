"""Tests for napt.download module."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import requests_mock

from napt.download.download import download_file
from napt.exceptions import NetworkError, NotModifiedError


def _sha256(data: bytes) -> str:
    """Compute SHA-256 hash."""
    return hashlib.sha256(data).hexdigest()


def test_download_success(tmp_test_dir: Path) -> None:
    """Tests that a basic download succeeds and returns DownloadResult."""
    url = "https://example.com/file.bin"
    data = b"hello world"

    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        result = download_file(url, tmp_test_dir)

    assert result.file_path.exists()
    assert result.file_path.read_bytes() == data
    assert result.sha256 == _sha256(data)
    assert "Content-Length" in result.headers


def test_follows_redirect_and_uses_final_url_name(tmp_test_dir: Path) -> None:
    """Tests that redirects are followed and final URL name is used."""
    start = "https://example.com/start"
    final = "https://cdn.example.com/payload.pkg"

    with requests_mock.Mocker() as m:
        # 302 redirect to final URL
        m.get(start, status_code=302, headers={"Location": final})
        m.get(final, content=b"abc", headers={"Content-Length": "3"})
        result = download_file(start, tmp_test_dir)

    assert result.file_path.name == "payload.pkg"
    assert result.file_path.read_bytes() == b"abc"


def test_content_disposition_filename(tmp_test_dir: Path) -> None:
    """Tests that Content-Disposition header overrides URL filename."""
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
        result = download_file(url, tmp_test_dir)

    assert result.file_path.name == "thing.msi"
    assert result.file_path.read_bytes() == data


def test_content_disposition_filename_star_takes_precedence(tmp_test_dir: Path) -> None:
    """Tests that filename*= (RFC 5987) takes precedence over filename=."""
    url = "https://example.com/dl"
    data = b"abc"

    with requests_mock.Mocker() as m:
        m.get(
            url,
            content=data,
            headers={
                "Content-Disposition": (
                    "attachment; "
                    'filename="fallback.msi"; '
                    "filename*=UTF-8''Google%20Chrome%20Setup.msi"
                ),
                "Content-Length": str(len(data)),
            },
        )
        result = download_file(url, tmp_test_dir)

    assert result.file_path.name == "Google Chrome Setup.msi"


def test_content_disposition_filename_star_only(tmp_test_dir: Path) -> None:
    """Tests that filename*= alone is parsed correctly (RFC 5987)."""
    url = "https://example.com/dl"
    data = b"abc"

    with requests_mock.Mocker() as m:
        m.get(
            url,
            content=data,
            headers={
                "Content-Disposition": (
                    "attachment; filename*=UTF-8''My%20App%20Setup.exe"
                ),
                "Content-Length": str(len(data)),
            },
        )
        result = download_file(url, tmp_test_dir)

    assert result.file_path.name == "My App Setup.exe"


def test_content_disposition_malformed_filename_star_falls_back(
    tmp_test_dir: Path,
) -> None:
    """Tests that malformed filename*= falls through to filename=."""
    url = "https://example.com/dl"
    data = b"abc"

    with requests_mock.Mocker() as m:
        m.get(
            url,
            content=data,
            headers={
                # Malformed filename*= (no charset'lang'value structure)
                "Content-Disposition": (
                    'attachment; filename*=malformed; filename="fallback.msi"'
                ),
                "Content-Length": str(len(data)),
            },
        )
        result = download_file(url, tmp_test_dir)

    assert result.file_path.name == "fallback.msi"


def test_checksum_mismatch_raises_and_cleans_part_file(tmp_test_dir: Path) -> None:
    """Tests that checksum mismatch raises NetworkError and removes .part file."""
    url = "https://example.com/file.bin"

    with requests_mock.Mocker() as m:
        m.get(url, content=b"wrong", headers={"Content-Length": "5"})

        with pytest.raises(NetworkError, match="sha256 mismatch"):
            download_file(url, tmp_test_dir, expected_sha256="00" * 32)

    # The .part file should be gone (mismatch cleans up before rename)
    assert not list(tmp_test_dir.glob("*.part"))
    # The final file should not exist either
    assert not (tmp_test_dir / "file.bin").exists()


def test_checksum_validation_success(tmp_test_dir: Path) -> None:
    """Tests that correct checksum validation passes."""
    url = "https://example.com/file.bin"
    data = b"correct content"
    expected_hash = _sha256(data)

    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        result = download_file(url, tmp_test_dir, expected_sha256=expected_hash)

    assert result.file_path.exists()
    assert result.sha256 == expected_hash


def test_rejects_html_when_validate_content_type(tmp_test_dir: Path) -> None:
    """Tests that HTML is rejected when content type validation is enabled."""
    from napt.exceptions import ConfigError

    url = "https://example.com/file"

    with requests_mock.Mocker() as m:
        m.get(url, text="<html>oops</html>", headers={"Content-Type": "text/html"})

        with pytest.raises(ConfigError, match="expected binary"):
            download_file(url, tmp_test_dir, validate_content_type=True)


def test_writes_atomically_no_part_leftovers(tmp_test_dir: Path) -> None:
    """Tests that atomic writes don't leave .part files behind."""
    url = "https://example.com/file.bin"

    with requests_mock.Mocker() as m:
        m.get(url, content=b"x" * 10, headers={"Content-Length": "10"})
        result = download_file(url, tmp_test_dir)

    # No .part files should remain after successful download
    leftovers = list(tmp_test_dir.glob("*.part"))
    assert leftovers == []
    assert result.file_path.exists()


def test_conditional_request_with_etag_not_modified(tmp_test_dir: Path) -> None:
    """Tests that ETag causes NotModifiedError on 304 response."""
    url = "https://example.com/file.bin"
    etag = '"abc123"'

    with requests_mock.Mocker() as m:
        m.get(url, status_code=304)

        with pytest.raises(NotModifiedError, match="HTTP 304"):
            download_file(url, tmp_test_dir, etag=etag)


def test_conditional_request_with_last_modified_not_modified(
    tmp_test_dir: Path,
) -> None:
    """Tests that Last-Modified causes NotModifiedError on 304 response."""
    url = "https://example.com/file.bin"
    last_modified = "Mon, 01 Jan 2024 00:00:00 GMT"

    with requests_mock.Mocker() as m:
        m.get(url, status_code=304)

        with pytest.raises(NotModifiedError, match="HTTP 304"):
            download_file(url, tmp_test_dir, last_modified=last_modified)


def test_conditional_request_modified_downloads(tmp_test_dir: Path) -> None:
    """Tests that conditional request downloads when content is modified."""
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
        result = download_file(url, tmp_test_dir, etag=etag)

    assert result.file_path.exists()
    assert result.file_path.read_bytes() == data
    assert result.headers.get("ETag") == '"new_etag"'


def test_creates_destination_folder(tmp_test_dir: Path) -> None:
    """Tests that destination folder is created if it doesn't exist."""
    url = "https://example.com/file.bin"
    nested_dir = tmp_test_dir / "nested" / "path"
    data = b"test"

    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        result = download_file(url, nested_dir)

    assert nested_dir.exists()
    assert result.file_path.exists()
    assert result.file_path.parent == nested_dir


def test_incomplete_download_raises_network_error(tmp_test_dir: Path) -> None:
    """Tests that Content-Length mismatch raises NetworkError."""
    url = "https://example.com/file.bin"
    data = b"short"

    with requests_mock.Mocker() as m:
        # Report 100 bytes but only send 5
        m.get(url, content=data, headers={"Content-Length": "100"})

        with pytest.raises(NetworkError, match="Incomplete download"):
            download_file(url, tmp_test_dir)

    # .part file should be cleaned up
    assert not list(tmp_test_dir.glob("*.part"))
