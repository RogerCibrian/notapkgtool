"""
PSADT package building for NAPT.

This module handles building PSAppDeployToolkit packages from recipes and
downloaded installers. It orchestrates PSADT release management, script
generation, file copying, and branding application.

Public API:

build_package : function
    Build a complete PSADT package from a recipe and installer.
create_intunewin : function
    Create a .intunewin package from a built PSADT directory.

Example:
    from pathlib import Path
    from notapkgtool.build import build_package, create_intunewin
    
    # Build PSADT package
    build_result = build_package(
        recipe_path=Path("recipes/Google/chrome.yaml"),
        downloads_dir=Path("downloads"),
        verbose=True
    )
    
    print(f"Built: {build_result['build_dir']}")
    
    # Create .intunewin
    package_result = create_intunewin(
        build_dir=build_result['build_dir'],
        verbose=True
    )
    
    print(f"Package: {package_result['package_path']}")
"""

from .manager import build_package
from .packager import create_intunewin

__all__ = ["build_package", "create_intunewin"]

