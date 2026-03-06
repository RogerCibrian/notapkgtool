# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Parses .intunewin package files for NAPT upload operations.

A .intunewin file is a ZIP archive created by IntuneWinAppUtil with the
following structure:

    IntuneWinPackage/
      Contents/
        IntunePackage.intunewin   <- encrypted payload
      Metadata/
        Detection.xml             <- encryption metadata

This module extracts the encryption metadata from Detection.xml and provides
utilities for extracting the encrypted payload for upload to Azure Blob Storage.

Example:
    Parse metadata and extract payload:
        ```python
        from pathlib import Path
        from napt.upload.intunewin import parse_intunewin, extract_encrypted_payload

        metadata = parse_intunewin(
            Path("packages/napt-chrome/Invoke-AppDeployToolkit.intunewin")
        )
        print(f"Encrypted file: {metadata.encrypted_file_name}")
        print(f"Encryption key: {metadata.encryption_key}")
        ```

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from napt.exceptions import PackagingError

__all__ = ["IntunewinMetadata", "parse_intunewin", "extract_encrypted_payload"]

DETECTION_XML_PATH = "IntuneWinPackage/Metadata/Detection.xml"
ENCRYPTED_PAYLOAD_PATH = "IntuneWinPackage/Contents/IntunePackage.intunewin"


@dataclass(frozen=True)
class IntunewinMetadata:
    """Encryption metadata extracted from a .intunewin package.

    All fields are sourced from Detection.xml inside the .intunewin ZIP archive.
    This metadata is required by the Graph API file commit endpoint.

    Attributes:
        encrypted_file_name: Filename of the encrypted payload inside the
            Contents/ directory (always "IntunePackage.intunewin").
        unencrypted_content_size: Original size in bytes before encryption.
        file_digest: Base64-encoded SHA-256 hash of the encrypted payload.
        file_digest_algorithm: Hash algorithm used (always "SHA256").
        encryption_key: Base64-encoded AES-256 encryption key.
        mac_key: Base64-encoded HMAC key for MAC verification.
        init_vector: Base64-encoded AES initialization vector.
        mac: Base64-encoded MAC value for integrity verification.
        profile_identifier: Encryption profile version (always "ProfileVersion1").
        encrypted_file_size: Byte size of the encrypted payload file.
    """

    encrypted_file_name: str
    unencrypted_content_size: int
    file_digest: str
    file_digest_algorithm: str
    encryption_key: str
    mac_key: str
    init_vector: str
    mac: str
    profile_identifier: str
    encrypted_file_size: int


def _get_text(element: ET.Element, tag: str, ns: str) -> str | None:
    """Extract text from a direct child element.

    Args:
        element: Parent XML element.
        tag: Child tag name (without namespace).
        ns: Namespace prefix with braces (e.g., '{http://...}') or empty string.

    Returns:
        Stripped text content, or None if element or text is missing.

    """
    child = element.find(f"{ns}{tag}")
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _require_text(element: ET.Element, tag: str, ns: str, path: str) -> str:
    """Extract required text from a child element.

    Args:
        element: Parent XML element.
        tag: Child tag name (without namespace).
        ns: Namespace prefix with braces or empty string.
        path: Full path for error messages (e.g., "EncryptionInfo/EncryptionKey").

    Returns:
        Stripped text content.

    Raises:
        PackagingError: If the element or its text is absent.

    """
    value = _get_text(element, tag, ns)
    if value is None:
        raise PackagingError(
            f"Detection.xml is missing required field '{path}'. "
            "The .intunewin file may be corrupt or was not created by IntuneWinAppUtil."
        )
    return value


def parse_intunewin(intunewin_path: Path) -> IntunewinMetadata:
    """Parse a .intunewin package and extract encryption metadata.

    Reads IntuneWinPackage/Metadata/Detection.xml from inside the .intunewin
    ZIP and returns all encryption fields required for the Graph API upload flow.

    Args:
        intunewin_path: Path to the .intunewin file to parse.

    Returns:
        Parsed encryption metadata from Detection.xml.

    Raises:
        PackagingError: If the file is not a valid ZIP, Detection.xml is missing,
            or required XML fields are absent or malformed.

    Example:
        Parse an existing package:
            ```python
            from pathlib import Path
            from napt.upload.intunewin import parse_intunewin

            metadata = parse_intunewin(
                Path("packages/napt-chrome/Invoke-AppDeployToolkit.intunewin")
            )
            print(metadata.encryption_key)
            ```

    """
    try:
        zf = zipfile.ZipFile(intunewin_path, "r")
    except zipfile.BadZipFile as err:
        raise PackagingError(
            f"{intunewin_path} is not a valid .intunewin file (invalid ZIP archive)"
        ) from err
    except OSError as err:
        raise PackagingError(f"Failed to open {intunewin_path}: {err}") from err

    with zf:
        # Read Detection.xml
        try:
            xml_bytes = zf.read(DETECTION_XML_PATH)
        except KeyError as err:
            raise PackagingError(
                f"{intunewin_path} is missing {DETECTION_XML_PATH}. "
                "The file may be corrupt or was not created by IntuneWinAppUtil."
            ) from err

        # Get encrypted payload file size
        try:
            payload_info = zf.getinfo(ENCRYPTED_PAYLOAD_PATH)
            encrypted_file_size = payload_info.file_size
        except KeyError as err:
            raise PackagingError(
                f"{intunewin_path} is missing {ENCRYPTED_PAYLOAD_PATH}. "
                "The file may be corrupt or was not created by IntuneWinAppUtil."
            ) from err

    # Parse XML
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as err:
        raise PackagingError(f"Detection.xml contains invalid XML: {err}") from err

    # Extract namespace from root tag (e.g., '{http://schemas.microsoft.com/...}')
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag[: root.tag.index("}") + 1]

    # Read top-level fields
    encrypted_file_name = _require_text(root, "FileName", ns, "FileName")
    unencrypted_size_str = _require_text(
        root, "UnencryptedContentSize", ns, "UnencryptedContentSize"
    )
    try:
        unencrypted_content_size = int(unencrypted_size_str)
    except ValueError as err:
        raise PackagingError(
            f"Detection.xml UnencryptedContentSize is not an integer: "
            f"'{unencrypted_size_str}'"
        ) from err

    # Read EncryptionInfo subsection
    enc_info = root.find(f"{ns}EncryptionInfo")
    if enc_info is None:
        raise PackagingError(
            "Detection.xml is missing required section 'EncryptionInfo'. "
            "The .intunewin file may be corrupt."
        )

    encryption_key = _require_text(
        enc_info, "EncryptionKey", ns, "EncryptionInfo/EncryptionKey"
    )
    mac_key = _require_text(enc_info, "MacKey", ns, "EncryptionInfo/MacKey")
    init_vector = _require_text(
        enc_info, "InitializationVector", ns, "EncryptionInfo/InitializationVector"
    )
    mac = _require_text(enc_info, "Mac", ns, "EncryptionInfo/Mac")
    profile_identifier = _require_text(
        enc_info, "ProfileIdentifier", ns, "EncryptionInfo/ProfileIdentifier"
    )
    file_digest = _require_text(enc_info, "FileDigest", ns, "EncryptionInfo/FileDigest")
    file_digest_algorithm = _require_text(
        enc_info, "FileDigestAlgorithm", ns, "EncryptionInfo/FileDigestAlgorithm"
    )

    return IntunewinMetadata(
        encrypted_file_name=encrypted_file_name,
        unencrypted_content_size=unencrypted_content_size,
        file_digest=file_digest,
        file_digest_algorithm=file_digest_algorithm,
        encryption_key=encryption_key,
        mac_key=mac_key,
        init_vector=init_vector,
        mac=mac,
        profile_identifier=profile_identifier,
        encrypted_file_size=encrypted_file_size,
    )


def extract_encrypted_payload(intunewin_path: Path, dest_dir: Path) -> Path:
    """Extract the encrypted payload from a .intunewin package.

    Extracts IntuneWinPackage/Contents/IntunePackage.intunewin to the
    destination directory for upload to Azure Blob Storage.

    Args:
        intunewin_path: Path to the .intunewin file.
        dest_dir: Directory to extract the payload into.

    Returns:
        Path to the extracted encrypted payload file.

    Raises:
        PackagingError: If the file is not a valid ZIP or the payload is missing.

    """
    try:
        zf = zipfile.ZipFile(intunewin_path, "r")
    except zipfile.BadZipFile as err:
        raise PackagingError(
            f"{intunewin_path} is not a valid .intunewin file (invalid ZIP archive)"
        ) from err
    except OSError as err:
        raise PackagingError(f"Failed to open {intunewin_path}: {err}") from err

    with zf:
        try:
            zf.extract(ENCRYPTED_PAYLOAD_PATH, dest_dir)
        except KeyError as err:
            raise PackagingError(
                f"{intunewin_path} is missing {ENCRYPTED_PAYLOAD_PATH}. "
                "The file may be corrupt or was not created by IntuneWinAppUtil."
            ) from err

    # zipfile.extract preserves the full path structure inside dest_dir
    return dest_dir / ENCRYPTED_PAYLOAD_PATH
