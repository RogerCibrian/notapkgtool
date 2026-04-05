"""Tests for napt.build.msix_scripts module.

Tests MSIX detection and requirements script generation including:
- MSIXDetectionConfig and MSIXRequirementsConfig dataclasses
- Script content validation (Get-AppxPackage, version comparison)
- Script filename conventions
"""

from __future__ import annotations

from pathlib import Path

from napt.build.msix_scripts import (
    MSIXDetectionConfig,
    MSIXRequirementsConfig,
    generate_msix_detection_script,
    generate_msix_requirements_script,
)


class TestMSIXDetectionConfig:
    """Tests for MSIXDetectionConfig dataclass."""

    def test_default_values(self):
        """Tests that default values are set correctly."""
        config = MSIXDetectionConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
        )

        assert config.identity_name == "com.tinyspeck.slackdesktop"
        assert config.app_name == "Slack"
        assert config.version == "4.49.81.0"
        assert config.log_format == "cmtrace"
        assert config.log_level == "INFO"
        assert config.log_rotation_mb == 3
        assert config.exact_match is False
        assert config.app_id == ""
        assert config.install_scope == "system"

    def test_custom_values(self):
        """Tests that custom values are stored correctly."""
        config = MSIXDetectionConfig(
            identity_name="com.example.app",
            app_name="Example",
            version="1.0.0.0",
            log_level="DEBUG",
            exact_match=True,
            app_id="napt-example",
            install_scope="user",
        )

        assert config.identity_name == "com.example.app"
        assert config.log_level == "DEBUG"
        assert config.exact_match is True
        assert config.app_id == "napt-example"
        assert config.install_scope == "user"


class TestMSIXRequirementsConfig:
    """Tests for MSIXRequirementsConfig dataclass."""

    def test_default_values(self):
        """Tests that default values are set correctly."""
        config = MSIXRequirementsConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
        )

        assert config.identity_name == "com.tinyspeck.slackdesktop"
        assert config.app_name == "Slack"
        assert config.version == "4.49.81.0"
        assert config.log_format == "cmtrace"
        assert config.log_level == "INFO"
        assert config.log_rotation_mb == 3
        assert config.app_id == ""
        assert config.install_scope == "system"

    def test_custom_install_scope(self):
        """Tests that install_scope is stored correctly."""
        config = MSIXRequirementsConfig(
            identity_name="com.example.app",
            app_name="Example",
            version="1.0.0.0",
            install_scope="user",
        )

        assert config.install_scope == "user"


class TestGenerateMSIXDetectionScript:
    """Tests for generate_msix_detection_script."""

    def test_script_created(self, tmp_path):
        """Tests that detection script file is created."""
        config = MSIXDetectionConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
        )
        output_path = tmp_path / "detection.ps1"

        result = generate_msix_detection_script(config, output_path)

        assert result == output_path
        assert output_path.exists()

    def test_script_contains_identity_name(self, tmp_path):
        """Tests that script contains the package identity name."""
        config = MSIXDetectionConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
        )
        output_path = tmp_path / "detection.ps1"

        generate_msix_detection_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert "com.tinyspeck.slackdesktop" in content

    def test_script_contains_version(self, tmp_path):
        """Tests that script contains the expected version."""
        config = MSIXDetectionConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
        )
        output_path = tmp_path / "detection.ps1"

        generate_msix_detection_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert "4.49.81.0" in content

    def test_system_scope_uses_provisioned_query(self, tmp_path):
        """Tests that system scope generates Get-AppxProvisionedPackage detection."""
        config = MSIXDetectionConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
            install_scope="system",
        )
        output_path = tmp_path / "detection.ps1"

        generate_msix_detection_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert "Get-AppxProvisionedPackage" in content
        assert "Get-AppxPackage -Name" not in content

    def test_user_scope_uses_per_user_query(self, tmp_path):
        """Tests that user scope generates Get-AppxPackage detection."""
        config = MSIXDetectionConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
            install_scope="user",
        )
        output_path = tmp_path / "detection.ps1"

        generate_msix_detection_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert "Get-AppxPackage -Name" in content
        assert "Get-AppxProvisionedPackage" not in content

    def test_script_exact_match(self, tmp_path):
        """Tests that exact match flag is reflected in script."""
        config = MSIXDetectionConfig(
            identity_name="com.example.app",
            app_name="Example",
            version="1.0.0.0",
            exact_match=True,
        )
        output_path = tmp_path / "detection.ps1"

        generate_msix_detection_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert "$True" in content

    def test_creates_parent_directory(self, tmp_path):
        """Tests that parent directories are created if missing."""
        config = MSIXDetectionConfig(
            identity_name="com.example.app",
            app_name="Example",
            version="1.0.0.0",
        )
        output_path = tmp_path / "subdir" / "detection.ps1"

        generate_msix_detection_script(config, output_path)

        assert output_path.exists()

    def test_no_registry_scanning_in_main_logic(self, tmp_path):
        """Tests that MSIX detection main logic does not call registry functions."""
        config = MSIXDetectionConfig(
            identity_name="com.example.app",
            app_name="Example",
            version="1.0.0.0",
        )
        output_path = tmp_path / "detection.ps1"

        generate_msix_detection_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        # Main detection logic should use Get-InstalledAppxPackage, not registry
        assert "Get-InstalledAppxPackage" in content
        # Should not call Get-UninstallKeys in the main logic
        # (it may exist in _shared_functions.ps1 include but is not called)
        main_logic = content.split("# Main detection logic")[1]
        assert "Get-UninstallKeys" not in main_logic


class TestGenerateMSIXRequirementsScript:
    """Tests for generate_msix_requirements_script."""

    def test_script_created(self, tmp_path):
        """Tests that requirements script file is created."""
        config = MSIXRequirementsConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
        )
        output_path = tmp_path / "requirements.ps1"

        result = generate_msix_requirements_script(config, output_path)

        assert result == output_path
        assert output_path.exists()

    def test_script_contains_identity_name(self, tmp_path):
        """Tests that script contains the package identity name."""
        config = MSIXRequirementsConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
        )
        output_path = tmp_path / "requirements.ps1"

        generate_msix_requirements_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert "com.tinyspeck.slackdesktop" in content

    def test_script_outputs_required(self, tmp_path):
        """Tests that script contains the Required output."""
        config = MSIXRequirementsConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
        )
        output_path = tmp_path / "requirements.ps1"

        generate_msix_requirements_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert '"Required"' in content

    def test_script_always_exits_zero(self, tmp_path):
        """Tests that requirements script always exits 0."""
        config = MSIXRequirementsConfig(
            identity_name="com.example.app",
            app_name="Example",
            version="1.0.0.0",
        )
        output_path = tmp_path / "requirements.ps1"

        generate_msix_requirements_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        # Should only have "exit 0" (never "exit 1")
        assert "exit 0" in content
        assert "exit 1" not in content

    def test_no_registry_scanning_in_main_logic(self, tmp_path):
        """Tests that MSIX requirements main logic does not call registry functions."""
        config = MSIXRequirementsConfig(
            identity_name="com.example.app",
            app_name="Example",
            version="1.0.0.0",
        )
        output_path = tmp_path / "requirements.ps1"

        generate_msix_requirements_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        # Main requirements logic should use Get-InstalledAppxPackage
        assert "Get-InstalledAppxPackage" in content
        # Should not call Get-UninstallKeys in the main logic
        main_logic = content.split("# Main requirements logic")[1]
        assert "Get-UninstallKeys" not in main_logic

    def test_system_scope_uses_provisioned_query(self, tmp_path):
        """Tests that system scope generates Get-AppxProvisionedPackage requirements."""
        config = MSIXRequirementsConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
            install_scope="system",
        )
        output_path = tmp_path / "requirements.ps1"

        generate_msix_requirements_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert "Get-AppxProvisionedPackage" in content
        assert "Get-AppxPackage -Name" not in content

    def test_user_scope_uses_per_user_query(self, tmp_path):
        """Tests that user scope generates Get-AppxPackage requirements."""
        config = MSIXRequirementsConfig(
            identity_name="com.tinyspeck.slackdesktop",
            app_name="Slack",
            version="4.49.81.0",
            install_scope="user",
        )
        output_path = tmp_path / "requirements.ps1"

        generate_msix_requirements_script(config, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert "Get-AppxPackage -Name" in content
        assert "Get-AppxProvisionedPackage" not in content
