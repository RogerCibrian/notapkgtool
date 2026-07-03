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

"""Invoke-AppDeployToolkit.ps1 template generation for NAPT.

This module handles generating the Invoke-AppDeployToolkit.ps1 script by
reading PSADT's template, substituting configuration values, and inserting
recipe-specific install/uninstall code.

Design Principles:
    - PSADT template remains pristine in cache
    - Generate script by substitution, not modification
    - Preserve PSADT's structure and comments
    - Support dynamic values (AppScriptDate, discovered version)
    - Merge org defaults with recipe overrides

Example:
    Basic usage:
        ```python
        from pathlib import Path
        from napt.build.template import generate_invoke_script

        script = generate_invoke_script(
            template_path=Path("cache/psadt/4.1.7/Invoke-AppDeployToolkit.ps1"),
            config=recipe_config,
            version="141.0.7390.123",
            psadt_version="4.1.7",
            architecture="x64",
            installer_filename="installer.msi",
        )

        Path("builds/app/version/Invoke-AppDeployToolkit.ps1").write_text(script)
        ```
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from typing import Any

from napt.exceptions import PackagingError


def _format_powershell_value(value: Any) -> str:
    """Format a Python value as a PowerShell literal.

    Args:
        value: Python value to convert.

    Returns:
        PowerShell literal representation.

    Example:
        Format values for PowerShell:
            ```python
            _format_powershell_value("hello")      # Returns: "'hello'"
            _format_powershell_value(True)         # Returns: '$true'
            _format_powershell_value([0, 1, 2])    # Returns: '@(0, 1, 2)'
            ```
    """
    if isinstance(value, bool):
        return "$true" if value else "$false"
    elif isinstance(value, str):
        # Escape single quotes in strings
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, list):
        # Format as PowerShell array
        items = [_format_powershell_value(item) for item in value]
        return f"@({', '.join(items)})"
    elif value is None or value == "":
        return "''"
    else:
        # Fallback: convert to string and quote
        return f"'{str(value)}'"


# Leftover {{snake_case}} tokens after substitution; digit-led sequences like
# the .NET format-string escape "{{0}}" intentionally don't match.
_UNRECOGNIZED_TOKEN_RE = re.compile(r"\{\{[a-z][a-z0-9_]*\}\}")

_SUPPORTED_VARIABLES = "{{discovered_version}}, {{installer_filename}}"


def _substitute_variables(text: str, version: str, installer_filename: str) -> str:
    """Substitutes NAPT build-time variables in recipe-provided text.

    Replaces {{discovered_version}} with the discovered application version
    and {{installer_filename}} with the exact filename of the installer
    copied into the package's Files directory.

    Args:
        text: Recipe-provided text that may contain variable tokens.
        version: Discovered application version.
        installer_filename: Installer filename in the Files directory.

    Returns:
        Text with all supported variable tokens replaced.
    """
    # str.replace, not re.sub: filenames may contain regex-special characters
    text = text.replace("{{discovered_version}}", version)
    return text.replace("{{installer_filename}}", installer_filename)


def _warn_unrecognized_tokens(code: str, block_name: str) -> None:
    """Warns about unrecognized variable tokens left after substitution.

    Called after [_substitute_variables][napt.build.template._substitute_variables]
    has run, so any remaining {{snake_case}} token is not a supported NAPT
    variable. Unrecognized tokens pass through to the generated PowerShell
    script verbatim.

    Args:
        code: Install or uninstall code after substitution.
        block_name: Recipe field name for the warning message (e.g.,
            "psadt.install").
    """
    from napt.logging import get_global_logger

    tokens = sorted(set(_UNRECOGNIZED_TOKEN_RE.findall(code)))
    if tokens:
        logger = get_global_logger()
        logger.warning(
            "BUILD",
            f"{block_name} contains unrecognized variable(s): "
            f"{', '.join(tokens)}. Supported NAPT variables: "
            f"{_SUPPORTED_VARIABLES}. Unrecognized tokens are left as-is "
            "in the generated script.",
        )


def _build_adtsession_vars(
    config: dict[str, Any],
    version: str,
    psadt_version: str,
    architecture: str,
    installer_filename: str,
) -> dict[str, Any]:
    """Build the $adtSession hashtable variables from configuration.

    Merges organization defaults with recipe-specific overrides.

    Args:
        config: Merged configuration (org + vendor + recipe).
        version: Discovered application version.
        psadt_version: PSADT version being used.
        architecture: Resolved installer architecture (e.g., "x64", "x86",
            "arm64", "any"). "any" is skipped — AppArch is left unset.
        installer_filename: Installer filename in the Files directory.

    Returns:
        Dictionary of variable name -> value mappings.

    Note:
        psadt.app_vars is the already-deep-merged result from code defaults,
        org.yaml, vendor.yaml, and the recipe. No manual merge needed here.
        String values get {{discovered_version}} and {{installer_filename}}
        substituted.
        Auto-generates AppScriptDate if not set.
        AppArch is set automatically from architecture (skipped for "any").
        DeployAppScriptVersion is always set to psadt_version.
    """
    # psadt.app_vars is already fully merged by the config loader
    merged_vars = dict(config.get("psadt", {}).get("app_vars", {}))

    for key, value in merged_vars.items():
        if isinstance(value, str):
            merged_vars[key] = _substitute_variables(
                value, version, installer_filename
            )

    # Add auto-generated fields
    merged_vars.setdefault("AppScriptDate", date.today().strftime("%Y-%m-%d"))
    merged_vars["DeployAppScriptVersion"] = psadt_version

    # Auto-populate AppArch from installer architecture ("any" means unset)
    if architecture and architecture != "any":
        merged_vars["AppArch"] = architecture

    # Add vendor if available
    vendor = config.get("vendor", "")
    if vendor:
        merged_vars.setdefault("AppVendor", vendor)

    return merged_vars


def _replace_session_block(template: str, vars_dict: dict[str, Any]) -> str:
    """Replace the $adtSession = @{...} block in the template.

    Finds the hashtable initialization and replaces it with values from
    vars_dict.

    Args:
        template: PSADT template script text.
        vars_dict: Variable name -> value mappings.

    Returns:
        Script with replaced $adtSession block.

    Raises:
        RuntimeError: If $adtSession block cannot be found in template.
    """
    # Find the $adtSession = @{ ... } block
    # Pattern matches from $adtSession = @{ to the closing }
    pattern = r"(\$adtSession = @\{)(.*?)(\n\})"

    match = re.search(pattern, template, re.DOTALL)
    if not match:
        raise PackagingError(
            "Could not find $adtSession hashtable in PSADT template. "
            "Template may be from an unsupported PSADT version."
        )

    # Build replacement hashtable
    lines = []
    for key, value in vars_dict.items():
        ps_value = _format_powershell_value(value)
        lines.append(f"    {key} = {ps_value}")

    replacement = "$adtSession = @{\n" + "\n".join(lines) + "\n}"

    # Replace in template
    result = re.sub(pattern, replacement, template, flags=re.DOTALL)

    return result


def _insert_recipe_code(
    script: str, install_code: str | None, uninstall_code: str | None
) -> str:
    """Insert recipe install/uninstall code at marker positions.

    Args:
        script: Generated script with placeholders.
        install_code: PowerShell code for installation.
        uninstall_code: PowerShell code for uninstallation.

    Returns:
        Script with recipe code inserted.

    Note:
        Replaces these PSADT markers:
        - "## <Perform Installation tasks here>"
        - "## <Perform Uninstallation tasks here>"
    """
    if install_code:
        # Ensure proper indentation (4 spaces to match PSADT style)
        indented_install = "\n".join(
            "    " + line if line.strip() else line
            for line in install_code.strip().split("\n")
        )

        script = script.replace(
            "    ## <Perform Installation tasks here>",
            f"    ## <Perform Installation tasks here>\n{indented_install}",
        )

    if uninstall_code:
        # Ensure proper indentation
        indented_uninstall = "\n".join(
            "    " + line if line.strip() else line
            for line in uninstall_code.strip().split("\n")
        )

        script = script.replace(
            "    ## <Perform Uninstallation tasks here>",
            f"    ## <Perform Uninstallation tasks here>\n{indented_uninstall}",
        )

    return script


def generate_invoke_script(
    template_path: Path,
    config: dict[str, Any],
    version: str,
    psadt_version: str,
    architecture: str,
    installer_filename: str,
) -> str:
    """Generate Invoke-AppDeployToolkit.ps1 from PSADT template and config.

    Reads the PSADT template, replaces the $adtSession hashtable with
    values from the configuration, and inserts recipe-specific install/
    uninstall code. NAPT variables ({{discovered_version}},
    {{installer_filename}}) are substituted in app_vars values and in the
    install/uninstall code blocks.

    Args:
        template_path: Path to PSADT's Invoke-AppDeployToolkit.ps1 template.
        config: Merged configuration (org + vendor + recipe).
        version: Application version (from filesystem).
        psadt_version: PSADT version being used.
        architecture: Resolved installer architecture (e.g., "x64", "x86",
            "arm64", "any"). Sets AppArch in the $adtSession hashtable;
            "any" leaves AppArch unset.
        installer_filename: Exact filename of the installer copied into the
            package's Files directory.

    Returns:
        Generated PowerShell script text.

    Raises:
        PackagingError: If template doesn't exist or template parsing fails.

    Example:
        Generate deployment script from template:
            ```python
            from pathlib import Path

            script = generate_invoke_script(
                Path("cache/psadt/4.1.7/Invoke-AppDeployToolkit.ps1"),
                config,
                "141.0.7390.123",
                "4.1.7",
                "x64",
                "installer.msi",
            )
            ```
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    if not template_path.exists():
        raise PackagingError(f"PSADT template not found: {template_path}")

    logger.verbose("BUILD", f"Reading PSADT template: {template_path.name}")

    # Read template
    template = template_path.read_text(encoding="utf-8")

    # Build $adtSession variables
    logger.verbose("BUILD", "Building $adtSession variables...")
    session_vars = _build_adtsession_vars(
        config, version, psadt_version, architecture, installer_filename
    )

    logger.debug("BUILD", "--- $adtSession Variables ---")
    for key, value in session_vars.items():
        logger.debug("BUILD", f"  {key} = {value}")

    # Replace $adtSession block
    script = _replace_session_block(template, session_vars)
    logger.verbose("BUILD", "[OK] Replaced $adtSession hashtable")

    # Insert recipe code
    psadt_config = config.get("psadt", {})
    install_code = psadt_config.get("install")
    uninstall_code = psadt_config.get("uninstall")

    if install_code:
        logger.verbose("BUILD", "Inserting install code from recipe")
        install_code = _substitute_variables(install_code, version, installer_filename)
        _warn_unrecognized_tokens(install_code, "psadt.install")
    if uninstall_code:
        logger.verbose("BUILD", "Inserting uninstall code from recipe")
        uninstall_code = _substitute_variables(
            uninstall_code, version, installer_filename
        )
        _warn_unrecognized_tokens(uninstall_code, "psadt.uninstall")

    script = _insert_recipe_code(script, install_code, uninstall_code)

    logger.verbose("BUILD", "[OK] Script generation complete")

    return script
