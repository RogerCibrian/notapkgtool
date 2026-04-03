"""Tests for napt.versioning.msix module.

Tests MSIX metadata extraction including:
- Extracting metadata from valid MSIX packages
- Architecture mapping from ProcessorArchitecture
- Error handling for invalid/missing files
- Error handling for missing manifest fields
"""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from napt.exceptions import ConfigError, PackagingError
from napt.versioning.msix import (
    MSIXMetadata,
    _architecture_from_manifest,
    extract_msix_metadata,
)

VALID_MANIFEST = """\
<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Identity
    Name="com.tinyspeck.slackdesktop"
    ProcessorArchitecture="x64"
    Publisher="CN=Slack Technologies"
    Version="4.49.81.0" />
  <Properties>
    <DisplayName>Slack</DisplayName>
    <PublisherDisplayName>Slack Technologies Inc.</PublisherDisplayName>
    <Logo>Assets/Logo.png</Logo>
  </Properties>
</Package>
"""


def _create_msix(path: Path, manifest_content: str) -> Path:
    """Creates a minimal MSIX (ZIP) file with an AppxManifest.xml."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AppxManifest.xml", manifest_content)
    return path


class TestMSIXMetadataDataclass:
    """Tests for MSIXMetadata dataclass."""

    def test_fields(self):
        """Tests that all fields are accessible."""
        metadata = MSIXMetadata(
            display_name="Slack",
            version="4.49.81.0",
            architecture="x64",
            identity_name="com.tinyspeck.slackdesktop",
            publisher="Slack Technologies Inc.",
        )

        assert metadata.display_name == "Slack"
        assert metadata.version == "4.49.81.0"
        assert metadata.architecture == "x64"
        assert metadata.identity_name == "com.tinyspeck.slackdesktop"
        assert metadata.publisher == "Slack Technologies Inc."

    def test_frozen(self):
        """Tests that the dataclass is immutable."""
        metadata = MSIXMetadata(
            display_name="Slack",
            version="4.49.81.0",
            architecture="x64",
            identity_name="com.tinyspeck.slackdesktop",
            publisher="Slack Technologies Inc.",
        )

        with pytest.raises(AttributeError):
            metadata.version = "5.0.0"


class TestArchitectureFromManifest:
    """Tests for _architecture_from_manifest."""

    def test_x86(self):
        """Tests that x86 maps correctly."""
        assert _architecture_from_manifest("x86") == "x86"

    def test_x64(self):
        """Tests that x64 maps correctly."""
        assert _architecture_from_manifest("x64") == "x64"

    def test_arm64(self):
        """Tests that arm64 maps correctly."""
        assert _architecture_from_manifest("arm64") == "arm64"

    def test_neutral(self):
        """Tests that neutral maps to any."""
        assert _architecture_from_manifest("neutral") == "any"

    def test_case_insensitive(self):
        """Tests that architecture mapping is case-insensitive."""
        assert _architecture_from_manifest("X64") == "x64"
        assert _architecture_from_manifest("Arm64") == "arm64"
        assert _architecture_from_manifest("Neutral") == "any"

    def test_unsupported_arm(self):
        """Tests that 32-bit ARM raises ConfigError."""
        with pytest.raises(ConfigError, match="not supported"):
            _architecture_from_manifest("arm")

    def test_unknown_architecture(self):
        """Tests that unknown architecture raises ConfigError."""
        with pytest.raises(ConfigError, match="Unknown MSIX architecture"):
            _architecture_from_manifest("itanium")


class TestExtractMsixMetadata:
    """Tests for extract_msix_metadata."""

    def test_valid_msix(self, tmp_path):
        """Tests that metadata is extracted from a valid MSIX."""
        msix_path = _create_msix(tmp_path / "Slack.msix", VALID_MANIFEST)
        metadata = extract_msix_metadata(msix_path)

        assert metadata.display_name == "Slack"
        assert metadata.version == "4.49.81.0"
        assert metadata.architecture == "x64"
        assert metadata.identity_name == "com.tinyspeck.slackdesktop"
        assert metadata.publisher == "Slack Technologies Inc."

    def test_neutral_architecture(self, tmp_path):
        """Tests that neutral architecture maps to any."""
        manifest = VALID_MANIFEST.replace(
            'ProcessorArchitecture="x64"',
            'ProcessorArchitecture="neutral"',
        )
        msix_path = _create_msix(tmp_path / "app.msix", manifest)
        metadata = extract_msix_metadata(msix_path)

        assert metadata.architecture == "any"

    def test_file_not_found(self):
        """Tests that missing file raises PackagingError."""
        with pytest.raises(PackagingError, match="MSIX not found"):
            extract_msix_metadata(Path("/nonexistent/app.msix"))

    def test_invalid_zip(self, tmp_path):
        """Tests that non-ZIP file raises PackagingError."""
        bad_file = tmp_path / "bad.msix"
        bad_file.write_text("not a zip file")

        with pytest.raises(PackagingError, match="not a valid ZIP"):
            extract_msix_metadata(bad_file)

    def test_missing_manifest(self, tmp_path):
        """Tests that MSIX without AppxManifest.xml raises PackagingError."""
        msix_path = tmp_path / "empty.msix"
        with zipfile.ZipFile(msix_path, "w") as zf:
            zf.writestr("other.xml", "<root/>")

        with pytest.raises(PackagingError, match="AppxManifest.xml not found"):
            extract_msix_metadata(msix_path)

    def test_missing_identity(self, tmp_path):
        """Tests that missing Identity element raises PackagingError."""
        manifest = """\
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Properties>
    <DisplayName>App</DisplayName>
    <PublisherDisplayName>Publisher</PublisherDisplayName>
  </Properties>
</Package>
"""
        msix_path = _create_msix(tmp_path / "app.msix", manifest)

        with pytest.raises(PackagingError, match="Identity element not found"):
            extract_msix_metadata(msix_path)

    def test_missing_version(self, tmp_path):
        """Tests that missing Version attribute raises PackagingError."""
        manifest = """\
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Identity Name="com.example.app" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>App</DisplayName>
    <PublisherDisplayName>Publisher</PublisherDisplayName>
  </Properties>
</Package>
"""
        msix_path = _create_msix(tmp_path / "app.msix", manifest)

        with pytest.raises(PackagingError, match="Version attribute missing"):
            extract_msix_metadata(msix_path)

    def test_missing_display_name(self, tmp_path):
        """Tests that missing DisplayName raises PackagingError."""
        manifest = """\
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Identity Name="com.example.app" ProcessorArchitecture="x64" Version="1.0.0.0" />
  <Properties>
    <PublisherDisplayName>Publisher</PublisherDisplayName>
  </Properties>
</Package>
"""
        msix_path = _create_msix(tmp_path / "app.msix", manifest)

        with pytest.raises(PackagingError, match="DisplayName not found"):
            extract_msix_metadata(msix_path)

    def test_empty_publisher_allowed(self, tmp_path):
        """Tests that empty publisher is allowed."""
        manifest = """\
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Identity Name="com.example.app" ProcessorArchitecture="x64" Version="1.0.0.0" />
  <Properties>
    <DisplayName>App</DisplayName>
  </Properties>
</Package>
"""
        msix_path = _create_msix(tmp_path / "app.msix", manifest)
        metadata = extract_msix_metadata(msix_path)

        assert metadata.publisher == ""
