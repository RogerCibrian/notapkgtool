"""
PSADT package building for NAPT.

This module handles building PSAppDeployToolkit packages from recipes and
downloaded installers. It orchestrates PSADT release management, script
generation, file copying, and branding application.

Public API
----------
build_package : function
    Build a complete PSADT package from a recipe and installer.

Example
-------
    from pathlib import Path
    from notapkgtool.build import build_package
    
    result = build_package(
        recipe_path=Path("recipes/Google/chrome.yaml"),
        downloads_dir=Path("downloads"),
        verbose=True
    )
    
    print(f"Built: {result['build_dir']}")
    print(f"Version: {result['version']}")
"""

from .manager import build_package

__all__ = ["build_package"]

