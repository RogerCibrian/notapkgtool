# exceptions

Exception hierarchy for NAPT.

This module defines a custom exception hierarchy that allows library users to distinguish between different types of errors:

- **ConfigError**: Configuration-related errors (YAML parse errors, missing fields, validation failures)
- **NetworkError**: Network/download-related errors (API failures, download errors)
- **PackagingError**: Packaging/build-related errors (build failures, missing tools)

All exceptions inherit from **NAPTError**, allowing users to catch all NAPT errors with a single `except` clause if needed.

::: notapkgtool.exceptions

