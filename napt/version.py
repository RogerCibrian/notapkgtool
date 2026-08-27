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

"""NAPT's own package version.

``pyproject.toml`` is the single source of the version; nothing in the
codebase hard-codes it. [get_version][napt.version.get_version] reads it
from the installed distribution metadata and caches the result, so the
metadata scan happens at most once per process.
"""

from __future__ import annotations

from functools import cache
from importlib.metadata import version


@cache
def get_version() -> str:
    """Returns the installed NAPT package version.

    Reads the version from the installed distribution metadata (sourced
    from ``pyproject.toml`` at install time). The lookup scans installed
    package metadata, so the result is cached for the life of the
    process.

    Returns:
        Version string, for example ``"0.9.0"``.

    """
    return version("napt")
