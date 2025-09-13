from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import requests_mock

import notapkgtool.processors.download as dl


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_download_success(tmp_path: Path) -> None:
    url = "https://example.com/file.bin"
    data = b"hello world"

    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        path, digest = dl.download_file(url, tmp_path)

    assert path.exists()
    assert path.read_bytes() == data
    assert digest == _sha256(data)


def test_follows_redirect_and_uses_final_url_name(tmp_path: Path) -> None:
    start = "https://example.com/start"
    final = "https://cdn.example.com/payload.pkg"

    with requests_mock.Mocker() as m:
        # 302 to final URL
        m.get(start, status_code=302, headers={"Location": final})
        m.get(final, content=b"abc", headers={"Content-Length": "3"})
        path, _ = dl.download_file(start, tmp_path)

    assert path.name == "payload.pkg"
    assert path.read_bytes() == b"abc"


def test_content_disposition_filename(tmp_path: Path) -> None:
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
        path, _ = dl.download_file(url, tmp_path)

    assert path.name == "thing.msi"
    assert path.read_bytes() == data


def test_checksum_mismatch_raises_and_cleans_file(tmp_path: Path) -> None:
    url = "https://example.com/file.bin"

    with requests_mock.Mocker() as m:
        m.get(url, content=b"wrong", headers={"Content-Length": "5"})

        with pytest.raises(ValueError, match="sha256 mismatch"):
            dl.download_file(url, tmp_path, expected_sha256="00" * 32)

    # ensure file was removed after mismatch
    assert not (tmp_path / "file.bin").exists()


def test_rejects_html_when_validate_content_type(tmp_path: Path) -> None:
    url = "https://example.com/file"

    with requests_mock.Mocker() as m:
        m.get(url, text="<html>oops</html>", headers={"Content-Type": "text/html"})

        with pytest.raises(ValueError, match="expected binary"):
            dl.download_file(url, tmp_path, validate_content_type=True)


def test_writes_atomically_no_part_leftovers(tmp_path: Path) -> None:
    url = "https://example.com/file.bin"

    with requests_mock.Mocker() as m:
        m.get(url, content=b"x" * 10, headers={"Content-Length": "10"})
        path, _ = dl.download_file(url, tmp_path)

    # no .part files should remain after a successful download
    leftovers = list(tmp_path.glob("*.part"))
    assert leftovers == []
    assert path.exists()
