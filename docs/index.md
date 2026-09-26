# NAPT - Not a Pkg Tool

> **Automated Windows application packaging and deployment to Microsoft Intune using PSAppDeployToolkit**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Overview

NAPT is a Python CLI.
It runs on Windows, Linux, and macOS; creating .intunewin packages requires
Windows.

### What NAPT automates

Without NAPT, each new app version means checking the vendor for a release,
editing a PSAppDeployToolkit (PSADT) template, writing detection and
requirements scripts, running IntuneWinAppUtil.exe, uploading in the Intune
portal, and assigning the app to groups.
NAPT does each step from one YAML recipe per app.

### Key features

- **Version discovery** - Finds new versions from vendor APIs, GitHub
  releases, download pages, or fixed URLs, and does not download an
  unchanged installer again
- **YAML recipes** - One recipe per app, with layered configuration
  (organization, vendor, parent recipe, recipe)
- **PSADT packaging** - Builds the PSADT deployment with detection and
  requirements scripts, then the .intunewin package
- **Intune upload** - Uploads to Microsoft Intune through the Graph API
- **Ring promotion** - `napt promote` moves each release through deployment
  rings and reports assignment drift; `napt status` shows every app's
  published version, pending release, and ring positions
- **Intune sign-in** - `napt auth setup` creates the app registration;
  `napt auth login` signs in

## Getting started

See the [Quick start guide](quick-start.md) for installation and setup.

## Creating recipes

Recipes are YAML files that define how to discover, download, and package an
application.

**Example recipes:**

- **[chrome.yaml](https://github.com/RogerCibrian/notapkgtool/blob/main/recipes/Google/chrome.yaml)** - url_download strategy with MSI version extraction
- **[git.yaml](https://github.com/RogerCibrian/notapkgtool/blob/main/recipes/Git/git.yaml)** - api_github strategy for GitHub Releases
- **[7zip-x64-msi.yaml](https://github.com/RogerCibrian/notapkgtool/blob/main/recipes/7-Zip/7zip-x64-msi.yaml)** - web_scrape strategy for vendor download pages

**Note:** The `recipes/` and `defaults/` directories in this repository are
working examples used for development and testing.
They are not included in the pip package.
Run `napt init` to create your own workspace with a starter `org.yaml`.

A recipe uses one of four discovery strategies: `url_download`, `web_scrape`,
`api_github`, or `api_json`.
The [Recipe reference](recipe-reference.md#discovery-configuration) defines
their fields;
[Common tasks](common-tasks.md#create-a-recipe-for-a-github-release-app)
walks through a recipe for each.

## Contributing

See [Contributing](contributing.md) to suggest features or report problems.

## License

Apache License 2.0; see
[LICENSE](https://github.com/RogerCibrian/notapkgtool/blob/main/LICENSE).

## Author

**Roger Cibrian**

## Acknowledgments

- Draws inspiration from [AutoPkg](https://github.com/autopkg/autopkg) for macOS application packaging automation
- Uses [PSAppDeployToolkit](https://psappdeploytoolkit.com/) (PSADT) for Windows application packaging
- Uses [IntuneWinAppUtil](https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool) for creating .intunewin packages

