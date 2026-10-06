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

"""What the NAPT app registration must contain.

The redirect URIs, Microsoft Graph permissions, and federated credential
default that `napt auth setup` provisions and `napt auth status` checks
for. Kept apart from the provisioning code so the CLI can build its parser
and print the portal checklist without loading the Azure libraries.
"""

from __future__ import annotations

LOCALHOST_REDIRECT = "http://localhost"
BROKER_REDIRECT_TEMPLATE = "ms-appx-web://Microsoft.AAD.BrokerPlugin/{client_id}"

# Graph permissions NAPT needs to run, whether granted as application
# permissions (service principal, Azure CLI session) or delegated permissions
# (interactive). `napt auth status` checks a token against this set, and the
# two lists below, which `napt auth setup` grants, are built from it.
REQUIRED_PERMISSIONS = ("DeviceManagementApps.ReadWrite.All", "Group.Read.All")

# Application permissions (app roles) for CI/CD and the delegated scopes for
# interactive sign-in. User.Read is what the portal adds to every new
# registration; it lets `napt auth login` look up the tenant's name.
APPLICATION_PERMISSIONS = REQUIRED_PERMISSIONS
DELEGATED_PERMISSIONS = (*REQUIRED_PERMISSIONS, "User.Read")

# Audience Entra expects on federated tokens from any external issuer.
FEDERATED_AUDIENCE_DEFAULT = "api://AzureADTokenExchange"

# What NAPT expects of a registration. Bump it whenever
# APPLICATION_PERMISSIONS, DELEGATED_PERMISSIONS, or the redirect URIs
# change, so a re-run of `napt auth setup` reports the registration as out
# of date. It is written to the registration's internal notes as the
# ``napt/v1`` provenance stamp, mirroring the stamp on Intune apps.
SPEC_VERSION = 1
