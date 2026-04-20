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

"""MSIX metadata extraction for NAPT.

This module extracts metadata from MSIX package files by reading the
embedded AppxManifest.xml. MSIX files are ZIP archives containing a
signed app package manifest with identity, display, and capability
information.

Extraction Approach:
    Uses Python's zipfile and xml.etree.ElementTree to parse
    AppxManifest.xml directly from the archive. No external dependencies
    or platform-specific tools required.

Extracted Fields:
    - Identity.Name: Package identity for ``Get-AppxPackage`` detection
    - Identity.Version: Four-part version string (e.g., "4.49.81.0")
    - Identity.ProcessorArchitecture: Mapped to NAPT architecture values
    - Properties.DisplayName: Human-readable application name
    - Properties.PublisherDisplayName: Publisher display string

Example:
    Extract metadata from an MSIX file:
        ```python
        from napt.versioning.msix import extract_msix_metadata

        metadata = extract_msix_metadata("Slack.msix")
        print(f"{metadata.display_name} {metadata.version} ({metadata.architecture})")
        # Slack 4.49.81.0 (x64)
        print(f"Identity: {metadata.identity_name}")
        # com.tinyspeck.slackdesktop
        ```

Note:
    This is pure file introspection; no network calls are made. Works
    cross-platform with no external dependencies.

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import xml.etree.ElementTree as ET
import zipfile

from napt.exceptions import ConfigError, PackagingError

# MSIX ProcessorArchitecture mapping
# See: https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-identity
_ARCH_TO_NAPT: dict[str, str] = {
    "x86": "x86",
    "x64": "x64",
    "arm64": "arm64",
    "neutral": "any",
}

# Unsupported architectures that raise ConfigError
_UNSUPPORTED_ARCHS: dict[str, str] = {
    "arm": "Windows RT 32-bit ARM is not supported by Intune",
}

# AppxManifest.xml namespace
_MANIFEST_NS = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"

# Type alias for architecture values (includes "any" for neutral packages)
Architecture = Literal["x86", "x64", "arm64", "any"]


@dataclass(frozen=True)
class MSIXMetadata:
    """Represents metadata extracted from an MSIX file.

    Attributes:
        display_name: DisplayName from Properties element.
        version: Version from Identity element (four-part, e.g.,
            "4.49.81.0").
        architecture: Installer architecture from Identity
            ProcessorArchitecture attribute. One of "x86", "x64",
            "arm64", or "any" (for architecture-neutral packages).
        identity_name: Package identity name from Identity Name attribute.
            Used for ``Get-AppxPackage -Name`` queries in detection scripts.
        publisher: PublisherDisplayName from Properties element.
    """

    display_name: str
    version: str
    architecture: Architecture
    identity_name: str
    publisher: str


def extract_msix_metadata(file_path: str | Path) -> MSIXMetadata:
    """Extracts metadata from an MSIX file's AppxManifest.xml.

    Reads the MSIX archive (ZIP format) and parses AppxManifest.xml to
    extract identity, version, architecture, display name, and publisher
    information.

    Args:
        file_path: Path to the MSIX file.

    Returns:
        MSIX metadata including display name, version, architecture,
        identity name, and publisher.

    Raises:
        PackagingError: If the MSIX file does not exist, is not a valid
            ZIP archive, does not contain AppxManifest.xml, or is missing
            required fields.
        ConfigError: If the MSIX architecture is not supported by Intune.

    Example:
        Extract MSIX metadata:
            ```python
            from pathlib import Path
            from napt.versioning.msix import extract_msix_metadata

            metadata = extract_msix_metadata(Path("Slack.msix"))
            print(f"{metadata.display_name} {metadata.version} ({metadata.architecture})")
            # Slack 4.49.81.0 (x64)
            ```

    Note:
        DisplayName may reference ms-resource strings in some packages.
        These are returned as-is; the build phase should validate that
        the display name is usable for detection.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    msix_path = Path(file_path)
    if not msix_path.exists():
        raise PackagingError(f"MSIX not found: {msix_path}")

    logger.verbose("MSIX", f"Extracting metadata from: {msix_path.name}")

    try:
        with zipfile.ZipFile(msix_path, "r") as zf:
            if "AppxManifest.xml" not in zf.namelist():
                raise PackagingError(
                    f"AppxManifest.xml not found in {msix_path.name}. "
                    f"File may not be a valid MSIX package."
                )
            manifest_bytes = zf.read("AppxManifest.xml")
    except zipfile.BadZipFile as err:
        raise PackagingError(
            f"Cannot read {msix_path.name}: not a valid ZIP/MSIX archive."
        ) from err

    root = ET.fromstring(manifest_bytes)

    # Parse Identity element
    identity = root.find(f"{{{_MANIFEST_NS}}}Identity")
    if identity is None:
        raise PackagingError(
            f"Identity element not found in {msix_path.name} " f"AppxManifest.xml."
        )

    identity_name = identity.get("Name", "")
    version = identity.get("Version", "")
    proc_arch = identity.get("ProcessorArchitecture", "")

    if not identity_name:
        raise PackagingError(f"Identity Name attribute missing in {msix_path.name}.")
    if not version:
        raise PackagingError(f"Identity Version attribute missing in {msix_path.name}.")
    if not proc_arch:
        raise PackagingError(
            f"Identity ProcessorArchitecture attribute missing in " f"{msix_path.name}."
        )

    architecture = _architecture_from_manifest(proc_arch)

    # Parse Properties element
    properties = root.find(f"{{{_MANIFEST_NS}}}Properties")
    if properties is None:
        raise PackagingError(
            f"Properties element not found in {msix_path.name} " f"AppxManifest.xml."
        )

    display_name_node = properties.find(f"{{{_MANIFEST_NS}}}DisplayName")
    publisher_node = properties.find(f"{{{_MANIFEST_NS}}}PublisherDisplayName")

    display_name = display_name_node.text if display_name_node is not None else ""
    publisher = (publisher_node.text or "") if publisher_node is not None else ""

    if not display_name:
        raise PackagingError(f"Properties DisplayName not found in {msix_path.name}.")

    logger.verbose(
        "MSIX",
        f"[OK] Extracted: {display_name} {version} ({architecture}) "
        f"[{identity_name}]",
    )

    return MSIXMetadata(
        display_name=display_name,
        version=version,
        architecture=architecture,
        identity_name=identity_name,
        publisher=publisher,
    )


def _architecture_from_manifest(proc_arch: str) -> Architecture:
    """Parses the MSIX ProcessorArchitecture into a NAPT architecture value.

    Args:
        proc_arch: ProcessorArchitecture attribute from Identity element.

    Returns:
        Architecture value: "x86", "x64", "arm64", or "any".

    Raises:
        ConfigError: If the architecture is not supported by Intune or
            is unrecognized.

    """
    arch_lower = proc_arch.lower()

    # Check for unsupported architectures first
    if arch_lower in _UNSUPPORTED_ARCHS:
        raise ConfigError(
            f"MSIX architecture '{proc_arch}' is not supported. "
            f"{_UNSUPPORTED_ARCHS[arch_lower]}."
        )

    # Map to NAPT architecture
    arch = _ARCH_TO_NAPT.get(arch_lower)
    if arch is None:
        raise ConfigError(
            f"Unknown MSIX architecture '{proc_arch}' in Identity element. "
            f"Expected one of: x86, x64, arm64, neutral."
        )

    return arch  # type: ignore[return-value]
