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

"""Exception hierarchy for NAPT.

This module defines a custom exception hierarchy that allows library users
to distinguish between different types of errors:

- ConfigError: Configuration-related errors (YAML parse, missing fields, validation failures)
- NetworkError: Network/download-related errors (API failures, download errors)
- PackagingError: Packaging/build-related errors (build failures, missing tools)

All exceptions inherit from NAPTError, allowing users to catch all NAPT errors
with a single except clause if needed.

Example:
    Catching specific error types:
        ```python
        from notapkgtool.core import discover_recipe
        from notapkgtool.exceptions import ConfigError, NetworkError

        try:
            result = discover_recipe(Path("recipe.yaml"), Path("./downloads"))
        except ConfigError as e:
            print(f"Configuration error: {e}")
        except NetworkError as e:
            print(f"Network error: {e}")
        ```

    Catching all NAPT errors:
        ```python
        from notapkgtool.exceptions import NAPTError

        try:
            result = discover_recipe(Path("recipe.yaml"), Path("./downloads"))
        except NAPTError as e:
            print(f"NAPT error: {e}")
        ```
"""

from __future__ import annotations

__all__ = [
    "NAPTError",
    "ConfigError",
    "NetworkError",
    "PackagingError",
]


class NAPTError(Exception):
    """Base exception for all NAPT errors.

    All NAPT-specific exceptions inherit from this class, allowing users
    to catch all NAPT errors with a single except clause if needed.
    """

    pass


class ConfigError(NAPTError):
    """Raised for configuration-related errors.

    This exception is raised when there are problems with:

    - YAML parsing (syntax errors, invalid structure)
    - Missing or invalid configuration fields
    - Invalid strategy configuration
    - Missing recipe files
    - Recipe validation failures

    Example:
        Catching configuration errors:
            ```python
            from notapkgtool.exceptions import ConfigError

            try:
                config = load_effective_config(Path("invalid.yaml"))
            except ConfigError as e:
                print(f"Config error: {e}")
            ```
    """

    pass


class NetworkError(NAPTError):
    """Raised for network/download-related errors.

    This exception is raised when there are problems with:

    - Download failures (HTTP errors, connection timeouts)
    - API call failures (GitHub API, JSON API endpoints)
    - Network-related version extraction errors

    Example:
        Catching network errors:
            ```python
            from notapkgtool.exceptions import NetworkError

            try:
                result = discover_recipe(Path("recipe.yaml"), Path("./downloads"))
            except NetworkError as e:
                print(f"Network error: {e}")
            ```
    """

    pass


class PackagingError(NAPTError):
    """Raised for packaging/build-related errors.

    This exception is raised when there are problems with:

    - Build failures (PSADT template processing, file operations)
    - Missing build tools (IntuneWinAppUtil.exe, PSADT template)
    - MSI extraction errors
    - Packaging operations

    Example:
        Catching packaging errors:
            ```python
            from notapkgtool.exceptions import PackagingError

            try:
                build_package(Path("recipe.yaml"), Path("./builds"))
            except PackagingError as e:
                print(f"Packaging error: {e}")
            ```
    """

    pass
