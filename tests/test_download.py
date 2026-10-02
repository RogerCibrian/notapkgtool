"""Tests for napt.download module."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
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


def test_content_disposition_unknown_charset_falls_back(tmp_test_dir: Path) -> None:
    """Tests that an RFC 5987 charset Python does not know falls through to
    filename= instead of failing the download."""
    url = "https://example.com/dl"
    data = b"abc"

    with requests_mock.Mocker() as m:
        m.get(
            url,
            content=data,
            headers={
                "Content-Disposition": (
                    "attachment; filename*=x-unknown''setup%20v2.msi; "
                    'filename="fallback.msi"'
                ),
                "Content-Length": str(len(data)),
            },
        )
        result = download_file(url, tmp_test_dir)

    assert result.file_path.name == "fallback.msi"


def test_transport_failure_is_a_network_error(tmp_test_dir: Path) -> None:
    """Tests that a connection failure is reported as NetworkError, not raw."""
    url = "https://example.com/file.bin"

    with requests_mock.Mocker() as m:
        m.get(url, exc=requests.ConnectionError("reset by peer"))
        with pytest.raises(NetworkError, match="download failed for"):
            download_file(url, tmp_test_dir)


def test_failure_mid_stream_is_a_network_error_and_removes_the_part_file(
    tmp_test_dir: Path,
) -> None:
    """Tests that a connection dropped while the body streams is reported
    and leaves no partial file behind."""
    url = "https://example.com/file.bin"

    def _drop(*args, **kwargs):
        yield b"first chunk"
        raise requests.exceptions.ChunkedEncodingError("connection broken")

    with requests_mock.Mocker() as m:
        m.get(url, content=b"first chunk and more", headers={"Content-Length": "20"})
        with patch("requests.Response.iter_content", side_effect=_drop):
            with pytest.raises(NetworkError, match="download failed for"):
                download_file(url, tmp_test_dir)

    assert list(tmp_test_dir.iterdir()) == []


def test_download_logs_under_approved_prefixes(tmp_test_dir: Path) -> None:
    """Tests that download progress and completion use the transport and
    file prefixes, not one of their own."""
    url = "https://example.com/file.bin"
    data = b"x" * 4096
    logger = MagicMock()

    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        with patch("napt.download.download.get_global_logger", return_value=logger):
            download_file(url, tmp_test_dir)

    prefixes = {
        call.args[0]
        for method in ("info", "warning", "verbose", "debug", "progress")
        for call in getattr(logger, method).call_args_list
    }
    assert prefixes
    assert "DOWNLOAD" not in prefixes
    assert prefixes <= {"HTTP", "FILE"}


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


def _download_with_header(tmp_test_dir: Path, disposition: str) -> Path:
    """Downloads a small payload whose server announces the given filename."""
    url = "https://example.com/latest"
    data = b"payload"
    with requests_mock.Mocker() as m:
        m.get(
            url,
            content=data,
            headers={
                "Content-Length": str(len(data)),
                "Content-Disposition": disposition,
            },
        )
        return download_file(url, tmp_test_dir).file_path


@pytest.mark.parametrize(
    "disposition",
    [
        'attachment; filename="../../evil.exe"',
        r'attachment; filename="..\..\evil.exe"',
        'attachment; filename="C:/Windows/evil.exe"',
        "attachment; filename*=UTF-8''..%2F..%2Fevil.exe",
        "attachment; filename*=UTF-8''%2e%2e%5c%2e%2e%5cevil.exe",
    ],
)
def test_server_filename_cannot_leave_download_folder(
    tmp_test_dir: Path, disposition: str
) -> None:
    """Tests that path segments in a server filename are discarded."""
    download_dir = tmp_test_dir / "downloads" / "napt-app"

    saved = _download_with_header(download_dir, disposition)

    assert saved == download_dir / "evil.exe"
    assert saved.exists()
    assert not (tmp_test_dir / "evil.exe").exists()
    assert not (tmp_test_dir / "downloads" / "evil.exe").exists()


def test_powershell_active_characters_are_replaced_in_filename(
    tmp_test_dir: Path, capsys
) -> None:
    """Tests that a hostile filename is rewritten and the change is reported."""
    saved = _download_with_header(
        tmp_test_dir, 'attachment; filename="setup$(Start-Process calc).msi"'
    )

    assert saved.name == "setup_(Start-Process calc).msi"
    output = capsys.readouterr().out
    assert "setup$(Start-Process calc).msi" in output
    assert "setup_(Start-Process calc).msi" in output


def test_unusable_server_filename_falls_back_to_url_name(tmp_test_dir: Path) -> None:
    """Tests that a reserved or empty server filename yields the URL name."""
    saved = _download_with_header(tmp_test_dir, 'attachment; filename="NUL.msi"')

    assert saved.name == "latest"


def test_ordinary_server_filename_is_kept_without_warning(
    tmp_test_dir: Path, capsys
) -> None:
    """Tests that a normal filename is saved as-is and nothing is reported."""
    saved = _download_with_header(
        tmp_test_dir, 'attachment; filename="Setup (x64).msi"'
    )

    assert saved.name == "Setup (x64).msi"
    assert "unsafe" not in capsys.readouterr().out


def test_falls_back_to_default_name_when_no_candidate_is_usable(
    tmp_test_dir: Path,
) -> None:
    """Tests that download.bin is used when header and URL names are unusable."""
    url = "https://example.com/files/NUL"
    data = b"payload"
    with requests_mock.Mocker() as m:
        m.get(
            url,
            content=data,
            headers={
                "Content-Length": str(len(data)),
                "Content-Disposition": 'attachment; filename=".."',
            },
        )
        result = download_file(url, tmp_test_dir)

    assert result.file_path.name == "download.bin"
