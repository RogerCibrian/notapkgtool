import requests
from pathlib import Path
from urllib.parse import urlparse

def get_filename_from_url(url: str) -> str:
    """
    Returns a filename from the url that is passed into the function.
    """
    return Path(urlparse(url).path).name

def download_file(url: str, destination_folder: Path) -> None:
    """
    Downloads a file from the given URL and saves it to the specified destination path.

    :param url: URL of the file to download.
    :param destination: Path where the file will be saved.
    """
    response = requests.get(url, stream=True, allow_redirects=False)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"Download failed: {e}")

    if 300 <= response.status_code < 400:
        raise requests.exceptions.HTTPError(
            f"Unexpected redirect: HTTP {response.status_code} for URL: {url}",
            response=response
        )

    # Check if the response indicates success
    if 200 <= response.status_code < 300:
        if "text/html" in response.headers.get("Content-Type", ""):
            raise ValueError(
                f"Expected a file, but got an HTML page: HTTP {response.status_code}"
            )
        print(f"Successfully connected to {url}: HTTP {response.status_code}")
    else:
        raise requests.exceptions.HTTPError(
            f"Unexpected status code: HTTP {response.status_code} for URL: {url}",
            response=response
        )
    
    destination = Path(str(destination_folder) + get_filename_from_url(url))
    
    destination.parent.mkdir(parents=True, exist_ok=True)

    total_size = int(response.headers.get("Content-Length", 0))
    downloaded = 0
    last_logged_percent = -1  # So we don't spam the console

    with destination.open("wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)

                if total_size:
                    percent = int((downloaded / total_size) * 100)
                    if percent != last_logged_percent:
                        print(f"Download progress: {percent}%", end="\r")
                        last_logged_percent = percent
                else:
                    print("Warning: Server did not provide content length. Progress cannot be tracked.")

    print(f"\nDownload complete: {destination}")
