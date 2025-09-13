from pathlib import Path
import hashlib
import io
import requests
import requests_mock
import notapkgtool.processors.download as dl


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_download_success(tmp_path: Path):
    url = "https://example.com/file.bin"
    data = b"hello world"
    with requests_mock.Mocker() as m:
        m.get(url, content=data, headers={"Content-Length": str(len(data))})
        path, digest = dl.download_file(url, tmp_path)

    assert path.exists()
    assert path.read_bytes() == data
    assert digest == _sha256(data)


def test_follows_redirect_and_uses_final_url_name(tmp_path: Path):
    start = "https://example.com/start"
    final = "https://cdn.example.com/payload.pkg"
    with requests_mock.Mocker() as m:
        m.get(start, status_code=302, headers={"Location": final})
        m.get(final, content=b"abc")
        path, _ = dl.download_file(start, tmp_path)
    assert path.name == "payload.pkg"


def test_content_disposition_filename(tmp_path: Path):
    url = "https://example.com/dl"
    data = b"abc"
    with requests_mock.Mocker() as m:
        m.get(
            url,
            content=data,
            headers={"Content-Disposition": 'attachment; filename="thing.msi"'},
        )
        path, _ = dl.download_file(url, tmp_path)
    assert path.name == "thing.msi"


def test_checksum_mismatch_raises_and_cleans_file(tmp_path: Path):
    url = "https://example.com/file.bin"
    with requests_mock.Mocker() as m:
        m.get(url, content=b"wrong")
        try:
            dl.download_file(url, tmp_path, expected_sha256="00" * 32)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "sha256 mismatch" in str(e)
    # ensure file was removed
    # the name comes from URL: file.bin
    assert not (tmp_path / "file.bin").exists()


def test_rejects_html_when_validate_content_type(tmp_path: Path):
    url = "https://example.com/file"
    with requests_mock.Mocker() as m:
        m.get(url, text="<html>oops</html>", headers={"Content-Type": "text/html"})
        try:
            dl.download_file(url, tmp_path, validate_content_type=True)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "expected binary" in str(e)


def test_writes_atomically(tmp_path: Path, monkeypatch):
    # Intercept rename to simulate atomicity path shape
    url = "https://example.com/file.bin"
    with requests_mock.Mocker() as m:
        m.get(url, content=b"x" * 10)
        path, _ = dl.download_file(url, tmp_path)
    # ensure no .part leftovers
    leftovers = list(tmp_path.glob("*.part"))
    assert leftovers == []
    assert path.exists()
