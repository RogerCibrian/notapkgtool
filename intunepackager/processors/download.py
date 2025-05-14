import requests
from pathlib import Path

def download_file(url: str, destination: Path) -> None:
    """
    Downloads a file from the given URL and saves it to the specified destination path.

    :param url: URL of the file to download.
    :param destination: Path where the file will be saved.
    """
    response = requests.get(url, stream=True, allow_redirects=False)

    if 300 <= response.status_code < 400:
        raise requests.exceptions.HTTPError(
            f"Unexpected redirect ({response.status_code}) for URL: {url}",
            response=response
    )

    # Raise error for non-200 status codes
    if response.status_code != 200:
        raise requests.exceptions.HTTPError(
            f"Expected 200 OK but got {response.status_code}",
            response=response
        )
    
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as f:
        # Download in 8 KB chunks
        # This avoids loading the entire file into memory and is safer/more efficient for large files
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"Downloaded: {destination}")
