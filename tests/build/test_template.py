"""
Tests for napt.build.template module.

Tests Invoke-AppDeployToolkit.ps1 generation including:
- PowerShell value formatting
- $adtSession variable building
- Template substitution
- Recipe code insertion
"""

from __future__ import annotations

import pytest

from napt.build.template import (
    _build_adtsession_vars,
    _format_powershell_value,
    _insert_recipe_code,
    _replace_session_block,
    _substitute_variables,
    _warn_unrecognized_tokens,
    generate_invoke_script,
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
        """Test that already-merged app_vars are used directly."""
        # The config loader deep-merges psadt.app_vars before this function runs.
        # This test verifies the function reads the merged result correctly.
        config = {
            "psadt": {
                "app_vars": {
                    "AppLang": "EN",
                    "AppRevision": "01",
                    "AppScriptAuthor": "RecipeOverride",
                    "AppName": "Test App",
                }
            },
        }

        result = _build_adtsession_vars(config, "1.0.0", "4.1.7", "x64", "app.msi")

        assert result["AppLang"] == "EN"
        assert result["AppRevision"] == "01"
        assert result["AppScriptAuthor"] == "RecipeOverride"
        assert result["AppName"] == "Test App"

    def test_discovered_version_substitution(self):
        """Tests that {{discovered_version}} is replaced in app_vars."""
        config = {
            "psadt": {
                "app_vars": {"AppVersion": "{{discovered_version}}"},
            },
        }

        result = _build_adtsession_vars(config, "2.3.4", "4.1.7", "x64", "app.msi")

        assert result["AppVersion"] == "2.3.4"

    def test_installer_filename_substitution(self):
        """Tests that {{installer_filename}} is replaced in app_vars."""
        config = {
            "psadt": {
                "app_vars": {"AppScriptAuthor": "Installer: {{installer_filename}}"},
            },
        }

        result = _build_adtsession_vars(
            config, "2.3.4", "4.1.7", "x64", "7z2501-x64.msi"
        )

        assert result["AppScriptAuthor"] == "Installer: 7z2501-x64.msi"

    def test_auto_generated_fields(self):
        """Test auto-generated fields like AppScriptDate."""
        from datetime import date

        config = {"psadt": {"app_vars": {}}}

        result = _build_adtsession_vars(config, "1.0.0", "4.1.7", "x64", "app.msi")

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

        from napt.exceptions import PackagingError

        with pytest.raises(PackagingError, match="Could not find \\$adtSession"):
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


class TestSubstituteVariables:
    """Tests for NAPT build-time variable substitution."""

    def test_substitutes_discovered_version(self):
        """Tests that {{discovered_version}} is replaced."""
        result = _substitute_variables(
            "Git-{{discovered_version}}-64-bit.exe", "2.47.1", "git.exe"
        )

        assert result == "Git-2.47.1-64-bit.exe"

    def test_substitutes_installer_filename(self):
        """Tests that {{installer_filename}} is replaced."""
        result = _substitute_variables(
            'FilePath "{{installer_filename}}"', "25.01", "7z2501-x64.msi"
        )

        assert result == 'FilePath "7z2501-x64.msi"'

    def test_substitutes_both_tokens_multiple_occurrences(self):
        """Tests that both tokens are replaced at every occurrence."""
        text = (
            "{{installer_filename}} v{{discovered_version}} "
            "({{discovered_version}}) from {{installer_filename}}"
        )

        result = _substitute_variables(text, "1.2", "app.exe")

        assert result == "app.exe v1.2 (1.2) from app.exe"

    def test_text_without_tokens_unchanged(self):
        """Tests that text without tokens passes through unchanged."""
        text = 'Start-ADTProcess -FilePath "setup.exe" -ArgumentList "/S"'

        assert _substitute_variables(text, "1.0", "setup.exe") == text

    def test_filename_with_special_characters(self):
        """Tests that regex-special characters in filenames stay literal."""
        result = _substitute_variables(
            "{{installer_filename}}", "25.01", "7z25.01 (x64)$+.msi"
        )

        assert result == "7z25.01 (x64)$+.msi"


class TestWarnUnrecognizedTokens:
    """Tests for the unrecognized-token warning."""

    @pytest.fixture(autouse=True)
    def _verbose_logger(self, capsys):
        """Installs a visible logger and restores the default afterward."""
        from napt.logging import get_global_logger, get_logger, set_global_logger

        previous = get_global_logger()
        set_global_logger(get_logger(verbose=True))
        yield
        set_global_logger(previous)

    def test_warns_for_unknown_token(self, capsys):
        """Tests that an unknown {{snake_case}} token triggers a warning."""
        _warn_unrecognized_tokens('FilePath "{{my_var}}"', "psadt.install")

        captured = capsys.readouterr()
        assert "{{my_var}}" in captured.out
        assert "psadt.install" in captured.out

    def test_warning_names_uninstall_block(self, capsys):
        """Tests that the warning names the uninstall block."""
        _warn_unrecognized_tokens("{{other}}", "psadt.uninstall")

        captured = capsys.readouterr()
        assert "psadt.uninstall" in captured.out

    def test_no_warning_for_env_var_syntax(self, capsys):
        """Tests that ${...} env-var and PowerShell syntax is ignored."""
        code = '${GITHUB_TOKEN} and ${env:ProgramFiles} and "$($adtSession.DirFiles)"'

        _warn_unrecognized_tokens(code, "psadt.install")

        assert capsys.readouterr().out == ""

    def test_no_warning_for_format_string_escape(self, capsys):
        """Tests that .NET format-string escapes like {{0}} are ignored."""
        _warn_unrecognized_tokens('"{{0}}" -f $value', "psadt.install")

        assert capsys.readouterr().out == ""

    def test_no_warning_for_clean_code(self, capsys):
        """Tests that code without leftover tokens stays silent."""
        _warn_unrecognized_tokens('FilePath "setup.exe"', "psadt.install")

        assert capsys.readouterr().out == ""


class TestGenerateInvokeScript:
    """Tests for end-to-end script generation."""

    TEMPLATE = """$adtSession = @{
    AppName = ''
    AppVersion = ''
}

function Install-ADTDeployment {
    ## <Perform Installation tasks here>
}

function Uninstall-ADTDeployment {
    ## <Perform Uninstallation tasks here>
}
"""

    def _write_template(self, tmp_path):
        template_path = tmp_path / "Invoke-AppDeployToolkit.ps1"
        template_path.write_text(self.TEMPLATE, encoding="utf-8")
        return template_path

    def test_substitutes_variables_in_install_and_uninstall(self, tmp_path):
        """Tests that both variables are substituted in recipe code blocks."""
        config = {
            "psadt": {
                "app_vars": {"AppName": "Test", "AppVersion": "{{discovered_version}}"},
                "install": 'Start-ADTMsiProcess -FilePath "{{installer_filename}}"',
                "uninstall": 'Write-Host "Removing v{{discovered_version}}"',
            },
        }

        result = generate_invoke_script(
            self._write_template(tmp_path), config, "25.01", "4.1.7", "x64",
            "7z2501-x64.msi",
        )

        assert 'FilePath "7z2501-x64.msi"' in result
        assert 'Write-Host "Removing v25.01"' in result
        assert "AppVersion = '25.01'" in result
        assert "{{discovered_version}}" not in result
        assert "{{installer_filename}}" not in result

    def test_none_code_blocks_still_generate(self, tmp_path):
        """Tests that missing install/uninstall blocks don't break generation."""
        config = {"psadt": {"app_vars": {"AppName": "Test"}}}

        result = generate_invoke_script(
            self._write_template(tmp_path), config, "1.0", "4.1.7", "any", "app.msix"
        )

        assert "AppName = 'Test'" in result
        assert "## <Perform Installation tasks here>" in result

    def test_unknown_token_warning_fires(self, tmp_path, capsys):
        """Tests that generation warns about unrecognized tokens."""
        from napt.logging import get_global_logger, get_logger, set_global_logger

        previous = get_global_logger()
        set_global_logger(get_logger(verbose=True))
        try:
            config = {
                "psadt": {
                    "app_vars": {"AppName": "Test"},
                    "install": 'FilePath "{{my_var}}"',
                },
            }

            generate_invoke_script(
                self._write_template(tmp_path), config, "1.0", "4.1.7", "x64",
                "app.msi",
            )
        finally:
            set_global_logger(previous)

        captured = capsys.readouterr()
        assert "{{my_var}}" in captured.out
        assert "psadt.install" in captured.out
