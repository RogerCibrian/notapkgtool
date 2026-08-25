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

"""Microsoft Entra ID authentication for NAPT.

Backs the `napt auth` command group and supplies the Graph access token
every Intune-facing command uses. Authentication needs no configuration
file:

- Developers: run `napt auth login` once (browser or OS broker); later
    commands use the cached session silently.
- CI/CD: set AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET
    (EnvironmentCredential), or sign in with an OIDC login step such as
    GitHub Actions `azure/login` (AzureCliCredential).

Modules:
    credentials - Token resolution, the interactive session store, and
        the `napt auth login/logout/status` operations.
    registration - App registration provisioning for `napt auth setup`.
"""
