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

"""State persistence for NAPT.

This package holds two kinds of state with opposite philosophies:

- **Discovery cache** ([napt.state.cache][]): A disposable optimization
    file (default ``cache/discovery.json``) tracking discovered versions,
    ETags, and download metadata between runs. It enables conditional
    downloads (HTTP 304) and version-change detection. Deleting it costs
    one full re-download per app and nothing else.
- **Deployment state** ([napt.state.deployment][]): Authoritative per-app
    records (``state/deployment/<recipe-id>.json``) of what NAPT has
    published to Intune and what is awaiting publication. Not regenerable.
    Serialized deterministically so unchanged state produces byte-identical
    files and clean diffs.

Cache tracking is enabled by default and can be disabled with the
--stateless flag, which also disables deployment state writes.

Example:
    Reading the discovery cache:
        ```python
        from pathlib import Path
        from napt.state import load_cache

        data = load_cache(Path("cache/discovery.json"))
        entry = data.get("apps", {}).get("napt-chrome")
        ```

    Reading deployment state:
        ```python
        from pathlib import Path
        from napt.state import deployment_state_path, load_deployment_state

        path = deployment_state_path(Path("state/deployment"), "napt-chrome")
        state = load_deployment_state(path)
        pending = state.get("pending")
        ```

"""

from .cache import (
    DiscoveryCache,
    cache_file_path,
    create_default_cache,
    load_cache,
    save_cache,
)
from .deployment import (
    create_default_deployment_state,
    deployment_state_path,
    load_deployment_state,
    record_pending,
    save_deployment_state,
)

__all__ = [
    "DiscoveryCache",
    "cache_file_path",
    "create_default_cache",
    "create_default_deployment_state",
    "deployment_state_path",
    "load_cache",
    "load_deployment_state",
    "record_pending",
    "save_cache",
    "save_deployment_state",
]
