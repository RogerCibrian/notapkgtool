"""Invoke-AppDeployToolkit.ps1 template generation for NAPT.

This module handles generating the Invoke-AppDeployToolkit.ps1 script by
reading PSADT's template, substituting configuration values, and inserting
recipe-specific install/uninstall code.

Private Helpers:
    - _build_adtsession_vars: Build $adtSession hashtable from config
    - _replace_session_block: Replace $adtSession = @{...} in template
    - _insert_recipe_code: Insert install/uninstall code at markers
    - _format_powershell_value: Format Python values as PowerShell literals

Design Principles:
    - PSADT template remains pristine in cache
    - Generate script by substitution, not modification
    - Preserve PSADT's structure and comments
    - Support dynamic values (AppScriptDate, discovered version)
    - Merge org defaults with recipe overrides

Example:
    from pathlib import Path
    from notapkgtool.build.template import generate_invoke_script

    script = generate_invoke_script(
        template_path=Path("cache/psadt/4.1.7/Invoke-AppDeployToolkit.ps1"),
        config=recipe_config,
        version="141.0.7390.123",
        psadt_version="4.1.7"
    )

    Path("builds/app/version/Invoke-AppDeployToolkit.ps1").write_text(script)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from typing import Any


def _format_powershell_value(value: Any) -> str:
    """Format a Python value as a PowerShell literal.

    Args:
        value: Python value to convert.

    Returns:
        PowerShell literal representation.

    Example:
        >>> _format_powershell_value("hello")
        "'hello'"
        >>> _format_powershell_value(True)
        '$true'
        >>> _format_powershell_value([0, 1, 2])
        '@(0, 1, 2)'
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


def _build_adtsession_vars(
    config: dict[str, Any], version: str, psadt_version: str
) -> dict[str, Any]:
    """Build the $adtSession hashtable variables from configuration.

    Merges organization defaults with recipe-specific overrides.

    Args:
        config: Merged configuration (org + vendor + recipe).
        version: Discovered application version.
        psadt_version: PSADT version being used.

    Returns:
        Dictionary of variable name → value mappings.

    Note:
        Organization defaults come from config['defaults']['psadt']['app_vars'].
        Recipe overrides come from config['apps'][0]['psadt']['app_vars'].
        Special handling for ${discovered_version} placeholder.
        Auto-generates AppScriptDate if not set.
    """
    app = config["apps"][0]

    # Get base variables from org defaults
    org_defaults = config.get("defaults", {}).get("psadt", {}).get("app_vars", {})

    # Get recipe overrides
    recipe_overrides = app.get("psadt", {}).get("app_vars", {})

    # Merge (recipe overrides org)
    merged_vars = {**org_defaults, **recipe_overrides}

    # Replace ${discovered_version} placeholder
    for key, value in merged_vars.items():
        if isinstance(value, str) and "${discovered_version}" in value:
            merged_vars[key] = value.replace("${discovered_version}", version)

    # Add auto-generated fields
    merged_vars.setdefault("AppScriptDate", date.today().strftime("%Y-%m-%d"))
    merged_vars["DeployAppScriptVersion"] = psadt_version

    # Add vendor if available
    vendor = config.get("vendor") or app.get("vendor", "")
    if vendor:
        merged_vars.setdefault("AppVendor", vendor)

    return merged_vars


def _replace_session_block(template: str, vars_dict: dict[str, Any]) -> str:
    """Replace the $adtSession = @{...} block in the template.

    Finds the hashtable initialization and replaces it with values from
    vars_dict.

    Args:
        template: PSADT template script text.
        vars_dict: Variable name → value mappings.

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
        raise RuntimeError(
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
    verbose: bool = False,
    debug: bool = False,
) -> str:
    """Generate Invoke-AppDeployToolkit.ps1 from PSADT template and config.

    Reads the PSADT template, replaces the $adtSession hashtable with
    values from the configuration, and inserts recipe-specific install/
    uninstall code.

    Args:
        template_path: Path to PSADT's Invoke-AppDeployToolkit.ps1 template.
        config: Merged configuration (org + vendor + recipe).
        version: Application version (from filesystem).
        psadt_version: PSADT version being used.
        verbose: Show verbose output. Default is False.
        debug: Show debug output. Default is False.

    Returns:
        Generated PowerShell script text.

    Raises:
        FileNotFoundError: If template doesn't exist.
        RuntimeError: If template parsing fails.

    Example:
        >>> script = generate_invoke_script(
        ...     Path("cache/psadt/4.1.7/Invoke-AppDeployToolkit.ps1"),
        ...     config,
        ...     "141.0.7390.123",
        ...     "4.1.7"
        ... )
    """
    from notapkgtool.cli import print_debug, print_verbose

    if not template_path.exists():
        raise FileNotFoundError(f"PSADT template not found: {template_path}")

    print_verbose("BUILD", f"Reading PSADT template: {template_path.name}")

    # Read template
    template = template_path.read_text(encoding="utf-8")

    # Build $adtSession variables
    print_verbose("BUILD", "Building $adtSession variables...")
    session_vars = _build_adtsession_vars(config, version, psadt_version)

    if debug:
        print_debug("BUILD", "--- $adtSession Variables ---")
        for key, value in session_vars.items():
            print_debug("BUILD", f"  {key} = {value}")

    # Replace $adtSession block
    script = _replace_session_block(template, session_vars)
    print_verbose("BUILD", "[OK] Replaced $adtSession hashtable")

    # Insert recipe code
    app = config["apps"][0]
    psadt_config = app.get("psadt", {})
    install_code = psadt_config.get("install")
    uninstall_code = psadt_config.get("uninstall")

    if install_code:
        print_verbose("BUILD", "Inserting install code from recipe")
    if uninstall_code:
        print_verbose("BUILD", "Inserting uninstall code from recipe")

    script = _insert_recipe_code(script, install_code, uninstall_code)

    print_verbose("BUILD", "[OK] Script generation complete")

    return script
