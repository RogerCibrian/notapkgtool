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

"""PSADT package building for NAPT.

Builds PSAppDeployToolkit packages from recipes and downloaded installers:
PSADT release management, script generation, file copying, and branding
application.

Modules:
    manager - Package building orchestration (build_package).
    packager - .intunewin package creation (create_intunewin).
    template - Invoke-AppDeployToolkit.ps1 generation.
    icons - Icon extraction from installers.
    registry_scripts - Detection/requirements script generation (registry).
    msix_scripts - Detection/requirements script generation (MSIX).
"""
