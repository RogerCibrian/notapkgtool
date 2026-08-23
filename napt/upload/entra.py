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

"""Entra ID app registration provisioning for `napt auth setup`.

Creates -- or brings up to spec -- the app registration that
[napt.upload.auth][] signs in with, so an administrator never has to click
through the portal:

- The application object with `http://localhost` and the Windows broker
    redirect URI as a Mobile-and-desktop platform, and the Microsoft Graph
    permissions NAPT needs declared as both application permissions (CI/CD)
    and delegated permissions (interactive sign-in).
- Its service principal, with tenant-wide admin consent for both kinds of
    permission.
- Optionally, a federated identity credential that lets a CI/CD platform's
    workflow obtain tokens through OIDC with no client secret. The issuer
    and subject come from the user; NAPT carries no platform-specific
    knowledge.

Every step is idempotent: an existing registration (found by display name
or ``--client-id``) is patched with only what is missing, and rerunning on a
complete registration changes nothing.

The run is bootstrapped with a short-lived token from the Microsoft Graph
Command Line Tools first-party application -- the same one `Connect-MgGraph`
uses -- requested in the browser and held in memory only. It needs an
account holding at least the Application Administrator role. NAPT does not
store that account or its tokens; the browser may keep its own sign-in.

Redirect URIs and permissions are always written to the application object,
never to the service principal, where a directory sync could drop them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
import time

import msal

from napt import __version__
from napt.exceptions import AuthError, ConfigError, NetworkError
from napt.upload.auth import (
    _AUTHORITY_BASE,
    _LOGIN_TIMEOUT,
    AuthConfig,
    _msal_error,
    _remember,
    load_auth_store,
)
from napt.upload.graph import _graph_request, _json_headers

__all__ = [
    "BROKER_REDIRECT_TEMPLATE",
    "FEDERATED_AUDIENCE_DEFAULT",
    "LOCALHOST_REDIRECT",
    "SPEC_VERSION",
    "SetupResult",
    "SetupSpec",
    "setup_app_registration",
]

_GRAPH_V1 = "https://graph.microsoft.com/v1.0"

# Microsoft Graph Command Line Tools: first-party public client with the
# loopback redirect registered, used only to obtain the bootstrap token.
_GRAPH_CLI_TOOLS_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

# Microsoft Graph's own application ID, the resource every permission targets.
_MS_GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"

_BOOTSTRAP_SCOPES = [
    "https://graph.microsoft.com/Application.ReadWrite.All",
    "https://graph.microsoft.com/AppRoleAssignment.ReadWrite.All",
    "https://graph.microsoft.com/DelegatedPermissionGrant.ReadWrite.All",
]

LOCALHOST_REDIRECT = "http://localhost"
BROKER_REDIRECT_TEMPLATE = "ms-appx-web://Microsoft.AAD.BrokerPlugin/{client_id}"

# Application permissions (app roles) for CI/CD and the delegated scopes for
# interactive sign-in. User.Read is what the portal adds to every new
# registration; it lets `napt auth login` look up the tenant's name.
APPLICATION_PERMISSIONS = ("DeviceManagementApps.ReadWrite.All", "Group.Read.All")
DELEGATED_PERMISSIONS = (
    "DeviceManagementApps.ReadWrite.All",
    "Group.Read.All",
    "User.Read",
)

# Audience Entra expects on federated tokens from any external issuer.
FEDERATED_AUDIENCE_DEFAULT = "api://AzureADTokenExchange"

# Provenance stamp written to the application's internal notes (the
# "Internal notes" box under Branding & properties), mirroring the
# ``napt/v1`` stamp on Intune apps. SPEC_VERSION describes what NAPT expects
# of a registration -- bump it whenever APPLICATION_PERMISSIONS,
# DELEGATED_PERMISSIONS, or the redirect URIs change, so a re-run of
# `napt auth setup` reports the registration as out of date.
SPEC_VERSION = 1
_STAMP_PREFIX = "napt/v1"
_STAMP_RE = re.compile(
    r"^napt/v1 spec=(?P<spec>\d+) version=(?P<version>\S+) provisioned=(?P<date>\S+)$"
)

# A just-created service principal can take a few seconds to replicate; the
# consent endpoints 404 until it does.
_REPLICATION_ATTEMPTS = 6
_REPLICATION_WAIT = 5.0

_HINT_BOOTSTRAP_FAILED = (
    "Could not sign in to create the app registration.\n\n"
    "This step signs in with the Microsoft Graph Command Line Tools app and\n"
    "needs an account holding at least the Application Administrator\n"
    "role. If your tenant blocks that app, use\n"
    "'napt auth setup --print-only' and complete the steps in the portal.\n"
)


@dataclass(frozen=True)
class SetupSpec:
    """What `napt auth setup` should provision.

    Attributes:
        tenant_id: Directory (tenant) ID to provision in.
        display_name: Display name of the app registration to find or
            create.
        client_id: Existing registration to bring up to spec instead of
            matching by display name.
        federated_issuer: OIDC issuer URL of the CI platform to trust (for
            example GitHub Actions' ``https://token.actions.githubusercontent.com``),
            or ``None`` for no federated credential.
        federated_subject: Subject claim the platform presents for the
            workflow that may obtain tokens; its format is defined by the
            platform (for GitHub Actions, ``repo:owner/name:ref:refs/heads/main``).
        federated_audience: Audience claim; Entra's standard value is the
            default.
        federated_name: Display name of the credential; derived from the
            subject when not given.
        adopt: Take over a registration matched by display name that NAPT
            did not create (no provenance stamp). Not needed when
            ``client_id`` names the registration explicitly.
    """

    tenant_id: str
    display_name: str = "NAPT"
    client_id: str | None = None
    federated_issuer: str | None = None
    federated_subject: str | None = None
    federated_audience: str = FEDERATED_AUDIENCE_DEFAULT
    federated_name: str | None = None
    adopt: bool = False

    def __post_init__(self) -> None:
        """Rejects a federated credential given only an issuer or only a subject."""
        if bool(self.federated_issuer) != bool(self.federated_subject):
            raise ConfigError(
                "A federated credential needs both an issuer and a subject "
                "(--federated-issuer and --federated-subject)"
            )

    @property
    def federated_credential_name(self) -> str | None:
        """Name of the federated credential: given, or derived from the subject."""
        if not self.federated_subject:
            return None
        if self.federated_name:
            return self.federated_name
        # Entra allows letters, digits, and hyphens, up to 120 characters.
        derived = re.sub(r"[^A-Za-z0-9]+", "-", self.federated_subject).strip("-")
        return f"napt-{derived}"[:120]


@dataclass
class SetupResult:
    """What `napt auth setup` found or created.

    Attributes:
        tenant_id: Tenant the registration lives in.
        client_id: Application (client) ID to use with NAPT.
        display_name: The registration's display name.
        created: Whether the application object was created by this run.
        adopted: Whether this run took over a registration NAPT did not
            create.
        needs_adopt: The registration matched by name carries no NAPT stamp
            and ``adopt`` was not given; nothing was changed.
        previous_spec: Spec version the registration was stamped with before
            this run, or ``None`` if it had no stamp.
        changes: Human-readable list of what this run added; empty when the
            registration was already complete.
    """

    tenant_id: str
    client_id: str
    display_name: str
    created: bool = False
    adopted: bool = False
    needs_adopt: bool = False
    previous_spec: int | None = None
    changes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Provenance stamp
# ---------------------------------------------------------------------------


def _render_stamp() -> str:
    today = datetime.now(UTC).date().isoformat()
    return (
        f"{_STAMP_PREFIX} spec={SPEC_VERSION} version={__version__} provisioned={today}"
    )


def _parse_stamp(notes: str | None) -> dict[str, str] | None:
    """Returns the stamp's fields from the notes text, or ``None`` if absent."""
    for line in (notes or "").splitlines():
        match = _STAMP_RE.match(line.strip())
        if match:
            return match.groupdict()
    return None


def _with_stamp(notes: str | None) -> str:
    """Returns ``notes`` with the stamp line replaced or prepended.

    Every other line an administrator wrote is preserved verbatim.
    """
    kept = [
        line
        for line in (notes or "").splitlines()
        if not line.strip().startswith(_STAMP_PREFIX + " ")
    ]
    return "\n".join([_render_stamp(), *kept]).rstrip()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _bootstrap_token(tenant_id: str) -> str:
    """Signs an administrator in through the browser for the provisioning run.

    Uses an in-memory MSAL cache so the administrator's session is gone when
    the process exits.

    Raises:
        AuthError: If the sign-in fails or is canceled.
    """
    app = msal.PublicClientApplication(
        _GRAPH_CLI_TOOLS_CLIENT_ID,
        authority=f"{_AUTHORITY_BASE}/{tenant_id}",
    )
    print("Opening your browser to sign in as an administrator...")
    try:
        result = app.acquire_token_interactive(
            _BOOTSTRAP_SCOPES, prompt="select_account", timeout=_LOGIN_TIMEOUT
        )
    except Exception as err:  # MSAL surfaces transport failures as raw errors
        raise AuthError(f"{_HINT_BOOTSTRAP_FAILED}Details: {err}") from err
    if "access_token" not in result:
        raise AuthError(f"{_HINT_BOOTSTRAP_FAILED}Details: {_msal_error(result)}")
    return result["access_token"]


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def _get(token: str, path: str, context: str) -> dict:
    return _graph_request("GET", f"{_GRAPH_V1}{path}", context, _json_headers(token))


def _post(token: str, path: str, body: dict, context: str) -> dict:
    return _graph_request(
        "POST",
        f"{_GRAPH_V1}{path}",
        context,
        _json_headers(token),
        json=body,
        idempotent=False,
    )


def _patch(token: str, path: str, body: dict, context: str) -> None:
    _graph_request("PATCH", f"{_GRAPH_V1}{path}", context, _json_headers(token), body)


def _post_after_replication(token: str, path: str, body: dict, context: str) -> dict:
    """POSTs, retrying a 404 that means the target has not replicated yet."""
    for attempt in range(1, _REPLICATION_ATTEMPTS + 1):
        try:
            return _post(token, path, body, context)
        except NetworkError as err:
            if "HTTP 404" not in str(err) or attempt == _REPLICATION_ATTEMPTS:
                raise
            time.sleep(_REPLICATION_WAIT)
    raise NetworkError(f"{context}: retry attempts exhausted")  # pragma: no cover


def _graph_permission_ids(token: str) -> tuple[dict[str, str], dict[str, str], str]:
    """Maps permission names to IDs on Microsoft Graph's service principal.

    Returns:
        ``(app_roles, scopes, graph_sp_id)`` -- app role IDs by value,
        delegated scope IDs by value, and the Graph service principal's
        object ID in this tenant.

    Raises:
        ConfigError: If a required permission name is unknown to Graph.
    """
    data = _get(
        token,
        f"/servicePrincipals?$filter=appId eq '{_MS_GRAPH_APP_ID}'"
        "&$select=id,appRoles,oauth2PermissionScopes",
        "Looking up Microsoft Graph permissions",
    )
    graph_sp = (data.get("value") or [{}])[0]
    roles = {r["value"]: r["id"] for r in graph_sp.get("appRoles", [])}
    scopes = {s["value"]: s["id"] for s in graph_sp.get("oauth2PermissionScopes", [])}
    missing = [p for p in APPLICATION_PERMISSIONS if p not in roles] + [
        p for p in DELEGATED_PERMISSIONS if p not in scopes
    ]
    if missing or "id" not in graph_sp:
        raise ConfigError(
            "Microsoft Graph did not report the permissions NAPT needs: "
            f"{', '.join(missing) or 'service principal not found'}"
        )
    return roles, scopes, graph_sp["id"]


# ---------------------------------------------------------------------------
# Application object
# ---------------------------------------------------------------------------


def _find_application(token: str, spec: SetupSpec) -> dict | None:
    """Finds the registration by client ID or display name.

    Raises:
        ConfigError: If several registrations share the display name.
    """
    select = "$select=id,appId,displayName,notes,publicClient,requiredResourceAccess"
    if spec.client_id:
        data = _get(
            token,
            f"/applications?$filter=appId eq '{spec.client_id}'&{select}",
            "Looking up app registration by client ID",
        )
        apps = data.get("value") or []
        if not apps:
            raise ConfigError(
                f"No app registration with client ID {spec.client_id} in "
                f"tenant {spec.tenant_id}"
            )
        return apps[0]
    name = spec.display_name.replace("'", "''")
    data = _get(
        token,
        f"/applications?$filter=displayName eq '{name}'&{select}",
        "Looking up app registration by name",
    )
    apps = data.get("value") or []
    if len(apps) > 1:
        ids = ", ".join(a["appId"] for a in apps)
        raise ConfigError(
            f"{len(apps)} app registrations are named '{spec.display_name}' "
            f"({ids}). Re-run with --client-id to choose one."
        )
    return apps[0] if apps else None


def _required_resource_access(
    roles: dict[str, str], scopes: dict[str, str]
) -> list[dict]:
    return [{"id": roles[p], "type": "Role"} for p in APPLICATION_PERMISSIONS] + [
        {"id": scopes[p], "type": "Scope"} for p in DELEGATED_PERMISSIONS
    ]


def _merge_resource_access(existing: list[dict], wanted: list[dict]) -> list[dict]:
    """Returns ``existing`` with NAPT's Graph entries added; other resources kept."""
    merged = [r for r in existing if r.get("resourceAppId") != _MS_GRAPH_APP_ID]
    graph_entry = next(
        (r for r in existing if r.get("resourceAppId") == _MS_GRAPH_APP_ID),
        {"resourceAppId": _MS_GRAPH_APP_ID, "resourceAccess": []},
    )
    have = {(a["id"], a["type"]) for a in graph_entry.get("resourceAccess", [])}
    access = list(graph_entry.get("resourceAccess", []))
    access.extend(a for a in wanted if (a["id"], a["type"]) not in have)
    merged.append({"resourceAppId": _MS_GRAPH_APP_ID, "resourceAccess": access})
    return merged


def _ensure_application(
    token: str,
    spec: SetupSpec,
    roles: dict[str, str],
    scopes: dict[str, str],
    result: SetupResult,
) -> dict:
    """Creates the application or patches a found one up to spec.

    Returns:
        The application object with at least ``id`` and ``appId``.
    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    wanted_access = _required_resource_access(roles, scopes)
    app = _find_application(token, spec)

    if app is None:
        app = _post(
            token,
            "/applications",
            {
                "displayName": spec.display_name,
                "signInAudience": "AzureADMyOrg",
                "notes": _render_stamp(),
                "publicClient": {"redirectUris": [LOCALHOST_REDIRECT]},
                "requiredResourceAccess": [
                    {"resourceAppId": _MS_GRAPH_APP_ID, "resourceAccess": wanted_access}
                ],
            },
            "Creating app registration",
        )
        result.created = True
        result.changes.append(f"Created app registration '{spec.display_name}'")
        # The broker redirect embeds the client ID, known only after creation.
        _patch(
            token,
            f"/applications/{app['id']}",
            {
                "publicClient": {
                    "redirectUris": [
                        LOCALHOST_REDIRECT,
                        BROKER_REDIRECT_TEMPLATE.format(client_id=app["appId"]),
                    ]
                }
            },
            "Adding redirect URIs",
        )
        result.changes.append("Added redirect URIs (browser and Windows broker)")
        return app

    stamp = _parse_stamp(app.get("notes"))
    if stamp is None:
        if not spec.client_id and not spec.adopt:
            result.needs_adopt = True
            return app
        result.adopted = True
        logger.info(
            "AUTH",
            f"Adopting registration '{app.get('displayName')}' ({app['appId']}) "
            "that NAPT did not create",
        )
    else:
        result.previous_spec = int(stamp["spec"])
        if result.previous_spec < SPEC_VERSION:
            logger.info(
                "AUTH",
                f"Registration is at spec {result.previous_spec}; NAPT "
                f"{__version__} expects spec {SPEC_VERSION}. Updating.",
            )

    patch: dict = {}
    wanted_uris = [
        LOCALHOST_REDIRECT,
        BROKER_REDIRECT_TEMPLATE.format(client_id=app["appId"]),
    ]
    have_uris = (app.get("publicClient") or {}).get("redirectUris") or []
    missing_uris = [u for u in wanted_uris if u not in have_uris]
    if missing_uris:
        patch["publicClient"] = {"redirectUris": have_uris + missing_uris}
        result.changes.append("Added redirect URIs: " + ", ".join(missing_uris))

    existing_access = app.get("requiredResourceAccess") or []
    merged_access = _merge_resource_access(existing_access, wanted_access)
    if merged_access != existing_access:
        patch["requiredResourceAccess"] = merged_access
        result.changes.append("Added Microsoft Graph API permissions")

    if (
        stamp is None
        or stamp["spec"] != str(SPEC_VERSION)
        or stamp["version"] != __version__
    ):
        patch["notes"] = _with_stamp(app.get("notes"))
        result.changes.append(
            f"Stamped internal notes: {_STAMP_PREFIX} spec={SPEC_VERSION} "
            f"version={__version__}"
        )

    if patch:
        _patch(token, f"/applications/{app['id']}", patch, "Updating app registration")
    return app


# ---------------------------------------------------------------------------
# Service principal and consent
# ---------------------------------------------------------------------------


def _ensure_service_principal(token: str, app: dict, result: SetupResult) -> str:
    """Returns the service principal object ID, creating it if needed."""
    data = _get(
        token,
        f"/servicePrincipals?$filter=appId eq '{app['appId']}'&$select=id",
        "Looking up service principal",
    )
    sps = data.get("value") or []
    if sps:
        return sps[0]["id"]
    sp = _post(
        token,
        "/servicePrincipals",
        {"appId": app["appId"]},
        "Creating service principal",
    )
    result.changes.append("Created service principal")
    return sp["id"]


def _ensure_app_role_consent(
    token: str,
    sp_id: str,
    graph_sp_id: str,
    roles: dict[str, str],
    result: SetupResult,
) -> None:
    """Grants admin consent for application permissions (app role assignments)."""
    data = _get(
        token,
        f"/servicePrincipals/{sp_id}/appRoleAssignments?$select=appRoleId,resourceId",
        "Listing application permission grants",
    )
    granted = {
        a["appRoleId"]
        for a in data.get("value") or []
        if a.get("resourceId") == graph_sp_id
    }
    for permission in APPLICATION_PERMISSIONS:
        role_id = roles[permission]
        if role_id in granted:
            continue
        _post_after_replication(
            token,
            f"/servicePrincipals/{sp_id}/appRoleAssignments",
            {"principalId": sp_id, "resourceId": graph_sp_id, "appRoleId": role_id},
            f"Granting application permission {permission}",
        )
        result.changes.append(f"Granted application permission {permission}")


def _ensure_delegated_consent(
    token: str, sp_id: str, graph_sp_id: str, result: SetupResult
) -> None:
    """Grants tenant-wide admin consent for the delegated permissions."""
    data = _get(
        token,
        "/oauth2PermissionGrants"
        f"?$filter=clientId eq '{sp_id}' and consentType eq 'AllPrincipals'"
        f" and resourceId eq '{graph_sp_id}'",
        "Listing delegated permission grants",
    )
    grants = data.get("value") or []
    if not grants:
        _post_after_replication(
            token,
            "/oauth2PermissionGrants",
            {
                "clientId": sp_id,
                "consentType": "AllPrincipals",
                "resourceId": graph_sp_id,
                "scope": " ".join(DELEGATED_PERMISSIONS),
            },
            "Granting delegated permissions",
        )
        result.changes.append(
            "Granted delegated permissions " + ", ".join(DELEGATED_PERMISSIONS)
        )
        return
    grant = grants[0]
    have = set((grant.get("scope") or "").split())
    missing = [p for p in DELEGATED_PERMISSIONS if p not in have]
    if not missing:
        return
    _patch(
        token,
        f"/oauth2PermissionGrants/{grant['id']}",
        {"scope": " ".join(sorted(have | set(missing)))},
        "Updating delegated permission grant",
    )
    result.changes.append("Granted delegated permissions " + ", ".join(missing))


# ---------------------------------------------------------------------------
# Federated credential
# ---------------------------------------------------------------------------


def _ensure_federated_credential(
    token: str, app: dict, spec: SetupSpec, result: SetupResult
) -> None:
    """Adds the OIDC federated credential when ``spec`` asks for one."""
    name = spec.federated_credential_name
    issuer = spec.federated_issuer
    subject = spec.federated_subject
    if not name or not issuer or not subject:
        return
    data = _get(
        token,
        f"/applications/{app['id']}/federatedIdentityCredentials",
        "Listing federated credentials",
    )
    for cred in data.get("value") or []:
        if cred.get("issuer") == issuer and cred.get("subject") == subject:
            return
    _post(
        token,
        f"/applications/{app['id']}/federatedIdentityCredentials",
        {
            "name": name,
            "issuer": issuer,
            "subject": subject,
            "audiences": [spec.federated_audience],
            "description": "NAPT CI/CD (OIDC)",
        },
        "Adding federated credential",
    )
    result.changes.append(f"Added federated credential for {subject} ({issuer})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def setup_app_registration(spec: SetupSpec) -> SetupResult:
    """Creates or completes the NAPT app registration in a tenant.

    Signs an administrator in, then finds or creates the application,
    adds any missing redirect URIs and Graph permissions, ensures the
    service principal exists with admin consent for every permission, and
    adds the GitHub federated credential when requested. Finally records
    the tenant and client ID as the active tenant for `napt auth login`.

    Args:
        spec: What to provision.

    Returns:
        The registration's IDs and the list of changes made.

    Raises:
        AuthError: If the administrator sign-in fails or lacks the rights
            to manage applications.
        ConfigError: If the display name is ambiguous, a given client ID
            does not exist, or Graph reports unexpected permission data.
        NetworkError: On Graph API failures.

    Example:
        Provision a tenant and trust a CI workflow through OIDC:
            ```python
            from napt.upload.entra import SetupSpec, setup_app_registration

            result = setup_app_registration(
                SetupSpec(
                    tenant_id="<tenant id>",
                    federated_issuer="https://token.actions.githubusercontent.com",
                    federated_subject="repo:contoso/intune-apps:ref:refs/heads/main",
                )
            )
            print(result.client_id, result.changes)
            ```

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    token = _bootstrap_token(spec.tenant_id)

    roles, scopes, graph_sp_id = _graph_permission_ids(token)
    result = SetupResult(
        tenant_id=spec.tenant_id, client_id="", display_name=spec.display_name
    )

    app = _ensure_application(token, spec, roles, scopes, result)
    result.client_id = app["appId"]
    result.display_name = app.get("displayName") or spec.display_name
    if result.needs_adopt:
        return result
    logger.info("AUTH", f"App registration: {result.display_name} ({result.client_id})")

    sp_id = _ensure_service_principal(token, app, result)
    _ensure_app_role_consent(token, sp_id, graph_sp_id, roles, result)
    _ensure_delegated_consent(token, sp_id, graph_sp_id, result)
    _ensure_federated_credential(token, app, spec, result)

    # Keep an existing session for this tenant when the client ID is unchanged.
    known = load_auth_store().tenants.get(spec.tenant_id)
    if known is not None and known.client_id == result.client_id:
        _remember(known)
    else:
        _remember(AuthConfig(client_id=result.client_id, tenant_id=spec.tenant_id))
    logger.verbose("AUTH", "Saved tenant and client ID for 'napt auth login'")
    return result
