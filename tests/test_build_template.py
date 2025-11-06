"""
Tests for notapkgtool.build.template module.

Tests Invoke-AppDeployToolkit.ps1 generation including:
- PowerShell value formatting
- $adtSession variable building
- Template substitution
- Recipe code insertion
"""

from __future__ import annotations

import pytest

from notapkgtool.build.template import (
    _build_adtsession_vars,
    _format_powershell_value,
    _insert_recipe_code,
    _replace_session_block,
)


class TestFormatPowerShellValue:
    """Tests for formatting Python values as PowerShell literals."""

    def test_format_string(self):
        """Test string formatting."""
        assert _format_powershell_value("hello") == "'hello'"

    def test_format_string_with_quotes(self):
        """Test string with single quotes (should be escaped)."""
        assert _format_powershell_value("it's") == "'it''s'"

    def test_format_bool_true(self):
        """Test boolean true."""
        assert _format_powershell_value(True) == "$true"

    def test_format_bool_false(self):
        """Test boolean false."""
        assert _format_powershell_value(False) == "$false"

    def test_format_int(self):
        """Test integer."""
        assert _format_powershell_value(42) == "42"

    def test_format_float(self):
        """Test float."""
        assert _format_powershell_value(3.14) == "3.14"

    def test_format_list(self):
        """Test list/array."""
        assert _format_powershell_value([0, 1, 2]) == "@(0, 1, 2)"

    def test_format_list_mixed(self):
        """Test list with mixed types."""
        result = _format_powershell_value([0, "test", True])
        assert result == "@(0, 'test', $true)"

    def test_format_empty_string(self):
        """Test empty string."""
        assert _format_powershell_value("") == "''"

    def test_format_none(self):
        """Test None value."""
        assert _format_powershell_value(None) == "''"


class TestBuildAdtSessionVars:
    """Tests for building $adtSession variables."""

    def test_merge_org_and_recipe_vars(self):
        """Test merging org defaults with recipe overrides."""
        config = {
            "defaults": {
                "psadt": {
                    "app_vars": {
                        "AppLang": "EN",
                        "AppRevision": "01",
                        "AppScriptAuthor": "OrgDefault",
                    }
                }
            },
            "apps": [
                {
                    "psadt": {
                        "app_vars": {
                            "AppName": "Test App",
                            "AppScriptAuthor": "RecipeOverride",
                        }
                    }
                }
            ],
        }

        result = _build_adtsession_vars(config, "1.0.0", "4.1.7")

        assert result["AppLang"] == "EN"
        assert result["AppRevision"] == "01"
        assert result["AppScriptAuthor"] == "RecipeOverride"  # Recipe wins
        assert result["AppName"] == "Test App"

    def test_discovered_version_substitution(self):
        """Test ${discovered_version} placeholder replacement."""
        config = {
            "defaults": {"psadt": {"app_vars": {}}},
            "apps": [{"psadt": {"app_vars": {"AppVersion": "${discovered_version}"}}}],
        }

        result = _build_adtsession_vars(config, "2.3.4", "4.1.7")

        assert result["AppVersion"] == "2.3.4"

    def test_auto_generated_fields(self):
        """Test auto-generated fields like AppScriptDate."""
        from datetime import date

        config = {
            "defaults": {"psadt": {"app_vars": {}}},
            "apps": [{"psadt": {"app_vars": {}}}],
        }

        result = _build_adtsession_vars(config, "1.0.0", "4.1.7")

        assert "AppScriptDate" in result
        assert result["AppScriptDate"] == date.today().strftime("%Y-%m-%d")
        assert result["DeployAppScriptVersion"] == "4.1.7"


class TestReplaceSessionBlock:
    """Tests for replacing $adtSession hashtable."""

    def test_replace_session_block(self):
        """Test replacing $adtSession block in template."""
        template = """
$adtSession = @{
    AppName = ''
    AppVersion = ''
}
"""

        vars_dict = {"AppName": "Test App", "AppVersion": "1.0.0"}

        result = _replace_session_block(template, vars_dict)

        assert "AppName = 'Test App'" in result
        assert "AppVersion = '1.0.0'" in result
        assert "$adtSession = @{" in result

    def test_replace_session_missing_block_raises(self):
        """Test error when $adtSession block not found."""
        template = "# No session block here"
        vars_dict = {}

        with pytest.raises(RuntimeError, match="Could not find \\$adtSession"):
            _replace_session_block(template, vars_dict)


class TestInsertRecipeCode:
    """Tests for inserting recipe install/uninstall code."""

    def test_insert_install_code(self):
        """Test inserting install code at marker."""
        script = """
    ## <Perform Installation tasks here>
"""

        install_code = "Write-Host 'Installing'"
        result = _insert_recipe_code(script, install_code, None)

        assert "Write-Host 'Installing'" in result

    def test_insert_uninstall_code(self):
        """Test inserting uninstall code at marker."""
        script = """
    ## <Perform Uninstallation tasks here>
"""

        uninstall_code = "Write-Host 'Uninstalling'"
        result = _insert_recipe_code(script, None, uninstall_code)

        assert "Write-Host 'Uninstalling'" in result

    def test_insert_multiline_code_with_indentation(self):
        """Test multiline code is properly indented."""
        script = """
    ## <Perform Installation tasks here>
"""

        install_code = """
Start-Process -Wait
Write-Host 'Done'
"""

        result = _insert_recipe_code(script, install_code, None)

        # Code should be indented to match PSADT style
        assert "    Start-Process -Wait" in result
        assert "    Write-Host 'Done'" in result

    def test_insert_both_install_and_uninstall(self):
        """Test inserting both install and uninstall code."""
        script = """
    ## <Perform Installation tasks here>
    ## <Perform Uninstallation tasks here>
"""

        install_code = "Install"
        uninstall_code = "Uninstall"

        result = _insert_recipe_code(script, install_code, uninstall_code)

        assert "Install" in result
        assert "Uninstall" in result

    def test_insert_none_code_no_change(self):
        """Test that None code doesn't modify script."""
        script = "    ## <Perform Installation tasks here>"

        result = _insert_recipe_code(script, None, None)

        assert result == script
