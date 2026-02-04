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

"""
PSADT package building for NAPT.

This module handles building PSAppDeployToolkit packages from recipes and
downloaded installers. It orchestrates PSADT release management, script
generation, file copying, and branding application.

Example:
    from pathlib import Path
    from napt.build import build_package, create_intunewin

    # Build PSADT package
    build_result = build_package(
        recipe_path=Path("recipes/Google/chrome.yaml"),
        downloads_dir=Path("downloads"),
        verbose=True
    )

    print(f"Built: {build_result.build_dir}")

    # Create .intunewin
    package_result = create_intunewin(
        build_dir=build_result.build_dir,
        verbose=True
    )

    print(f"Package: {package_result.package_path}")
"""

from .manager import build_package
from .packager import create_intunewin

__all__ = ["build_package", "create_intunewin"]
