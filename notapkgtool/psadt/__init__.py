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

"""PSAppDeployToolkit integration for NAPT.

This module handles PSAppDeployToolkit (PSADT) release management, caching,
and integration with NAPT's build system.

Example:
    Basic usage:
        ```python
        from pathlib import Path
        from notapkgtool.psadt import get_psadt_release, fetch_latest_psadt_version

        # Get latest version
        latest = fetch_latest_psadt_version()
        print(f"Latest PSADT: {latest}")

        # Download and cache
        psadt_path = get_psadt_release("latest", Path("cache/psadt"))
        print(f"PSADT cached at: {psadt_path}")
        ```

"""

from .release import (
    fetch_latest_psadt_version,
    get_psadt_release,
    is_psadt_cached,
)

__all__ = ["fetch_latest_psadt_version", "get_psadt_release", "is_psadt_cached"]
