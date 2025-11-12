"""
Manual test script for api_json discovery strategy.

This script demonstrates and tests the api_json strategy with:
1. A mock local HTTP server
2. Real public APIs (optional)

Usage:
    python tests/scripts/manual_test_api_json.py
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from notapkgtool.discovery.api_json import ApiJsonStrategy


class MockAPIHandler(BaseHTTPRequestHandler):
    """Mock API server handler for testing."""

    def log_message(self, format, *args):
        """Suppress server logs unless needed."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/api/simple":
            # Simple flat JSON
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "version": "1.2.3",
                "download_url": "https://download.example.com/app-1.2.3.msi",
            }
            self.wfile.write(json.dumps(response).encode())

        elif self.path == "/api/nested":
            # Nested JSON structure
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "release": {
                    "stable": {
                        "version": "2024.10.28",
                        "platforms": {
                            "windows": {
                                "x64": "https://download.example.com/win-x64.msi"
                            }
                        },
                    }
                }
            }
            self.wfile.write(json.dumps(response).encode())

        elif self.path == "/api/array":
            # Array response
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "releases": [
                    {
                        "version": "3.0.0",
                        "url": "https://download.example.com/v3.0.0.msi",
                    },
                    {
                        "version": "2.9.9",
                        "url": "https://download.example.com/v2.9.9.msi",
                    },
                ]
            }
            self.wfile.write(json.dumps(response).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """Handle POST requests."""
        if self.path == "/api/query":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body)
                platform = data.get("platform", "unknown")
                arch = data.get("arch", "unknown")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {
                    "result": {
                        "version": "4.5.6",
                        "platform": platform,
                        "arch": arch,
                        "url": f"https://download.example.com/{platform}-{arch}.msi",
                    }
                }
                self.wfile.write(json.dumps(response).encode())
            except Exception:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


def start_mock_server(port=8765):
    """Start mock API server in background thread."""
    server = HTTPServer(("localhost", port), MockAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)  # Give server time to start
    return server


def test_simple_json():
    """Test simple flat JSON response."""
    print("\n" + "=" * 70)
    print("TEST 1: Simple Flat JSON")
    print("=" * 70)

    strategy = ApiJsonStrategy()
    config = {
        "source": {
            "api_url": "http://localhost:8765/api/simple",
            "version_path": "version",
            "download_url_path": "download_url",
        }
    }

    print("\nConfiguration:")
    print(f"  API URL: {config['source']['api_url']}")
    print(f"  Version Path: {config['source']['version_path']}")
    print(f"  Download URL Path: {config['source']['download_url_path']}")

    try:
        # Mock the download since URL doesn't exist
        # In real usage, this would download the file
        import requests_mock

        with tempfile.TemporaryDirectory() as tmpdir:
            with requests_mock.Mocker() as m:
                # Mock the download
                m.get(
                    "https://download.example.com/app-1.2.3.msi",
                    content=b"fake installer",
                    headers={"Content-Length": "14"},
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    config, Path(tmpdir), verbose=True
                )

                print("\n✅ SUCCESS!")
                print(f"  Version: {discovered.version}")
                print(f"  Source: {discovered.source}")
                print(f"  File: {file_path.name}")
                print(f"  SHA-256: {sha256[:16]}...")

    except Exception as e:
        print(f"\n❌ FAILED: {e}")


def test_nested_json():
    """Test nested JSON structure."""
    print("\n" + "=" * 70)
    print("TEST 2: Nested JSON Structure")
    print("=" * 70)

    strategy = ApiJsonStrategy()
    config = {
        "source": {
            "api_url": "http://localhost:8765/api/nested",
            "version_path": "release.stable.version",
            "download_url_path": "release.stable.platforms.windows.x64",
        }
    }

    print("\nConfiguration:")
    print(f"  API URL: {config['source']['api_url']}")
    print(f"  Version Path: {config['source']['version_path']}")
    print(f"  Download URL Path: {config['source']['download_url_path']}")

    try:
        import requests_mock

        with tempfile.TemporaryDirectory() as tmpdir:
            with requests_mock.Mocker() as m:
                m.get(
                    "https://download.example.com/win-x64.msi",
                    content=b"fake nested installer",
                    headers={"Content-Length": "20"},
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    config, Path(tmpdir), verbose=True
                )

                print("\n✅ SUCCESS!")
                print(f"  Version: {discovered.version}")
                print(f"  Source: {discovered.source}")
                print(f"  File: {file_path.name}")
                print(f"  SHA-256: {sha256[:16]}...")

    except Exception as e:
        print(f"\n❌ FAILED: {e}")


def test_array_indexing():
    """Test array indexing with JSONPath."""
    print("\n" + "=" * 70)
    print("TEST 3: Array Indexing")
    print("=" * 70)

    strategy = ApiJsonStrategy()
    config = {
        "source": {
            "api_url": "http://localhost:8765/api/array",
            "version_path": "releases[0].version",
            "download_url_path": "releases[0].url",
        }
    }

    print("\nConfiguration:")
    print(f"  API URL: {config['source']['api_url']}")
    print(f"  Version Path: {config['source']['version_path']}")
    print(f"  Download URL Path: {config['source']['download_url_path']}")

    try:
        import requests_mock

        with tempfile.TemporaryDirectory() as tmpdir:
            with requests_mock.Mocker() as m:
                m.get(
                    "https://download.example.com/v3.0.0.msi",
                    content=b"fake array installer",
                    headers={"Content-Length": "19"},
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    config, Path(tmpdir), verbose=True
                )

                print("\n✅ SUCCESS!")
                print(f"  Version: {discovered.version}")
                print(f"  Source: {discovered.source}")
                print(f"  File: {file_path.name}")
                print(f"  SHA-256: {sha256[:16]}...")

    except Exception as e:
        print(f"\n❌ FAILED: {e}")


def test_post_request():
    """Test POST request with body."""
    print("\n" + "=" * 70)
    print("TEST 4: POST Request with Body")
    print("=" * 70)

    strategy = ApiJsonStrategy()
    config = {
        "source": {
            "api_url": "http://localhost:8765/api/query",
            "version_path": "result.version",
            "download_url_path": "result.url",
            "method": "POST",
            "body": {"platform": "windows", "arch": "x64"},
        }
    }

    print("\nConfiguration:")
    print(f"  API URL: {config['source']['api_url']}")
    print(f"  Method: {config['source']['method']}")
    print(f"  Body: {config['source']['body']}")
    print(f"  Version Path: {config['source']['version_path']}")
    print(f"  Download URL Path: {config['source']['download_url_path']}")

    try:
        import requests_mock

        with tempfile.TemporaryDirectory() as tmpdir:
            with requests_mock.Mocker() as m:
                m.get(
                    "https://download.example.com/windows-x64.msi",
                    content=b"fake post installer",
                    headers={"Content-Length": "18"},
                )

                discovered, file_path, sha256, headers = strategy.discover_version(
                    config, Path(tmpdir), verbose=True
                )

                print("\n✅ SUCCESS!")
                print(f"  Version: {discovered.version}")
                print(f"  Source: {discovered.source}")
                print(f"  File: {file_path.name}")
                print(f"  SHA-256: {sha256[:16]}...")

    except Exception as e:
        print(f"\n❌ FAILED: {e}")


def test_real_api():
    """Test against a real public API (GitHub)."""
    print("\n" + "=" * 70)
    print("TEST 5: Real API (GitHub - Optional)")
    print("=" * 70)
    print("\nThis test uses the GitHub API to fetch real data.")
    print("It may fail if you're behind a proxy or have rate limits.")

    response = input("\nRun this test? (y/n): ").strip().lower()
    if response != "y":
        print("Skipped.")
        return

    # Using Git for Windows as an example
    config = {
        "source": {
            "api_url": "https://api.github.com/repos/git-for-windows/git/releases/latest",
            "version_path": "tag_name",
            "download_url_path": "assets[0].browser_download_url",
        }
    }

    print("\nConfiguration:")
    print(f"  API URL: {config['source']['api_url']}")
    print(f"  Version Path: {config['source']['version_path']}")
    print(f"  Download URL Path: {config['source']['download_url_path']}")

    try:
        # Just test version extraction, skip download
        import requests

        response = requests.get(config["source"]["api_url"], timeout=10)
        response.raise_for_status()
        data = response.json()

        tag_name = data.get("tag_name", "N/A")
        first_asset_url = (
            data["assets"][0]["browser_download_url"] if data.get("assets") else "N/A"
        )

        print("\n✅ API Response Received!")
        print(f"  Latest Tag: {tag_name}")
        print(f"  First Asset URL: {first_asset_url[:60]}...")
        print("\nNote: Full download test skipped to save bandwidth and time.")

    except Exception as e:
        print(f"\n❌ FAILED: {e}")


def main():
    """Run all manual tests."""
    print("\n" + "=" * 70)
    print("HTTP JSON Strategy Manual Test Suite")
    print("=" * 70)
    print("\nThis script tests the api_json discovery strategy with:")
    print("  1. Simple flat JSON responses")
    print("  2. Nested JSON structures")
    print("  3. Array indexing with JSONPath")
    print("  4. POST requests with JSON body")
    print("  5. Real public API (optional)")

    # Check for requests_mock
    try:
        import requests_mock  # noqa: F401
    except ImportError:
        print("\n[WARNING] requests-mock not installed.")
        print("Install it with: pip install requests-mock")
        print("Tests will fail without it.\n")
        return

    # Start mock server
    print("\nStarting mock API server on http://localhost:8765...")
    server = start_mock_server(8765)

    try:
        # Run tests
        test_simple_json()
        test_nested_json()
        test_array_indexing()
        test_post_request()
        test_real_api()

        print("\n" + "=" * 70)
        print("All Tests Complete!")
        print("=" * 70)

    finally:
        # Cleanup
        print("\nShutting down mock server...")
        server.shutdown()


if __name__ == "__main__":
    main()
