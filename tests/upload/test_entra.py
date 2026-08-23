"""Tests for napt.upload.entra."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from napt.exceptions import AuthError, ConfigError, NetworkError
from napt.upload import auth, entra
from napt.upload.auth import AuthConfig, AuthStore
from napt.upload.entra import SetupSpec, setup_app_registration

GRAPH_SP_ID = "graph-sp"
ROLE_IDS = {"DeviceManagementApps.ReadWrite.All": "role-dm", "Group.Read.All": "role-g"}
SCOPE_IDS = {
    "DeviceManagementApps.ReadWrite.All": "scope-dm",
    "Group.Read.All": "scope-g",
    "User.Read": "scope-u",
}


def _graph_sp_response() -> dict:
    return {
        "value": [
            {
                "id": GRAPH_SP_ID,
                "appRoles": [{"value": v, "id": i} for v, i in ROLE_IDS.items()],
                "oauth2PermissionScopes": [
                    {"value": v, "id": i} for v, i in SCOPE_IDS.items()
                ],
            }
        ]
    }


def _stamp(spec: int = entra.SPEC_VERSION, version: str | None = None) -> str:
    version = version or entra.__version__
    return f"napt/v1 spec={spec} version={version} provisioned=2026-08-18"


def _complete_app(app_id: str = "cid", object_id: str = "obj") -> dict:
    """An application object that already matches the spec, stamped by NAPT."""
    return {
        "id": object_id,
        "appId": app_id,
        "displayName": "NAPT",
        "notes": _stamp(),
        "publicClient": {
            "redirectUris": [
                entra.LOCALHOST_REDIRECT,
                entra.BROKER_REDIRECT_TEMPLATE.format(client_id=app_id),
            ]
        },
        "requiredResourceAccess": [
            {
                "resourceAppId": entra._MS_GRAPH_APP_ID,
                "resourceAccess": [
                    {"id": ROLE_IDS[p], "type": "Role"}
                    for p in entra.APPLICATION_PERMISSIONS
                ]
                + [
                    {"id": SCOPE_IDS[p], "type": "Scope"}
                    for p in entra.DELEGATED_PERMISSIONS
                ],
            }
        ],
    }


class FakeGraph:
    """Routes _graph_request calls to canned responses and records writes."""

    def __init__(self, responses: dict[tuple[str, str], dict | list[dict]]):
        # Keys are (method, path-after-v1.0 up to '?'); values are a dict, or a
        # list of dicts returned in sequence for repeated calls.
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, url, context, headers, json=None, **kwargs):
        path = url.replace(entra._GRAPH_V1, "").split("?")[0]
        self.calls.append((method, path, json))
        key = (method, path)
        if key not in self.responses:
            raise AssertionError(f"unexpected Graph call {method} {path}")
        canned = self.responses[key]
        if isinstance(canned, list):
            return canned.pop(0) if len(canned) > 1 else canned[0]
        return canned

    def writes(self) -> list[tuple[str, str, dict | None]]:
        return [c for c in self.calls if c[0] != "GET"]


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NAPT_USER_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def bootstrap():
    with patch("napt.upload.entra._bootstrap_token", return_value="tok") as b:
        yield b


def _run(graph: FakeGraph, spec: SetupSpec):
    with (
        patch("napt.upload.entra._graph_request", graph),
        patch("napt.upload.entra.time.sleep"),
    ):
        return setup_app_registration(spec)


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def test_spec_federated_credential_name_is_derived_or_given() -> None:
    """Tests that the credential name defaults to a sanitized subject."""
    derived = SetupSpec(
        tenant_id="t",
        federated_issuer="https://token.actions.githubusercontent.com",
        federated_subject="repo:o/r:ref:refs/heads/main",
    )
    assert derived.federated_credential_name == "napt-repo-o-r-ref-refs-heads-main"
    assert derived.federated_audience == entra.FEDERATED_AUDIENCE_DEFAULT

    given = SetupSpec(
        tenant_id="t",
        federated_issuer="https://gitlab.example.com",
        federated_subject="project_path:g/p:ref_type:branch:ref:main",
        federated_name="gitlab-main",
    )
    assert given.federated_credential_name == "gitlab-main"

    assert SetupSpec(tenant_id="t").federated_credential_name is None


def test_spec_requires_issuer_and_subject_together() -> None:
    """Tests that a half-specified federated credential is rejected early."""
    with pytest.raises(ConfigError, match="both an issuer and a subject"):
        SetupSpec(tenant_id="t", federated_issuer="https://x")
    with pytest.raises(ConfigError, match="both an issuer and a subject"):
        SetupSpec(tenant_id="t", federated_subject="s")


# ---------------------------------------------------------------------------
# Fresh tenant
# ---------------------------------------------------------------------------


def test_setup_creates_everything_in_a_fresh_tenant(user_dir, bootstrap) -> None:
    """Tests the full create path: app, redirect patch, SP, both consents."""
    graph = FakeGraph(
        {
            ("GET", "/servicePrincipals"): [
                _graph_sp_response(),  # Graph's own SP
                {"value": []},  # NAPT SP does not exist yet
            ],
            ("GET", "/applications"): {"value": []},
            ("POST", "/applications"): {"id": "obj", "appId": "new-cid"},
            ("PATCH", "/applications/obj"): {},
            ("POST", "/servicePrincipals"): {"id": "sp"},
            ("GET", "/servicePrincipals/sp/appRoleAssignments"): {"value": []},
            ("POST", "/servicePrincipals/sp/appRoleAssignments"): {},
            ("GET", "/oauth2PermissionGrants"): {"value": []},
            ("POST", "/oauth2PermissionGrants"): {},
        }
    )

    result = _run(graph, SetupSpec(tenant_id="tid"))

    assert result.created is True
    assert result.client_id == "new-cid"
    bootstrap.assert_called_once_with("tid")

    create = next(
        j for m, p, j in graph.writes() if (m, p) == ("POST", "/applications")
    )
    assert create is not None
    assert create["signInAudience"] == "AzureADMyOrg"
    assert create["publicClient"]["redirectUris"] == [entra.LOCALHOST_REDIRECT]
    access = create["requiredResourceAccess"][0]
    assert access["resourceAppId"] == entra._MS_GRAPH_APP_ID
    assert {(a["id"], a["type"]) for a in access["resourceAccess"]} == {
        ("role-dm", "Role"),
        ("role-g", "Role"),
        ("scope-dm", "Scope"),
        ("scope-g", "Scope"),
        ("scope-u", "Scope"),
    }

    redirect_patch = next(
        j for m, p, j in graph.writes() if (m, p) == ("PATCH", "/applications/obj")
    )
    assert redirect_patch is not None
    assert redirect_patch["publicClient"]["redirectUris"] == [
        "http://localhost",
        "ms-appx-web://Microsoft.AAD.BrokerPlugin/new-cid",
    ]

    role_posts = [
        j
        for m, p, j in graph.writes()
        if p == "/servicePrincipals/sp/appRoleAssignments"
    ]
    assert {j["appRoleId"] for j in role_posts if j} == {"role-dm", "role-g"}
    assert all(j and j["resourceId"] == GRAPH_SP_ID for j in role_posts)

    grant = next(j for m, p, j in graph.writes() if p == "/oauth2PermissionGrants")
    assert grant is not None
    assert grant["consentType"] == "AllPrincipals"
    assert grant["scope"].split() == list(entra.DELEGATED_PERMISSIONS)

    # Nothing touches the service principal's redirect URIs or permissions.
    assert not any(p == "/servicePrincipals/sp" for _, p, _ in graph.writes())

    store = auth.load_auth_store()
    assert store.active == "tid"
    assert store.tenants["tid"] == AuthConfig("new-cid", "tid")
    assert len(result.changes) >= 5


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_setup_is_a_no_op_on_a_complete_registration(user_dir, bootstrap) -> None:
    """Tests that a registration already matching the spec is left untouched."""
    graph = FakeGraph(
        {
            ("GET", "/servicePrincipals"): [
                _graph_sp_response(),
                {"value": [{"id": "sp"}]},
            ],
            ("GET", "/applications"): {"value": [_complete_app()]},
            ("GET", "/servicePrincipals/sp/appRoleAssignments"): {
                "value": [
                    {"appRoleId": "role-dm", "resourceId": GRAPH_SP_ID},
                    {"appRoleId": "role-g", "resourceId": GRAPH_SP_ID},
                ]
            },
            ("GET", "/oauth2PermissionGrants"): {
                "value": [
                    {
                        "id": "grant",
                        "scope": "User.Read Group.Read.All "
                        "DeviceManagementApps.ReadWrite.All",
                    }
                ]
            },
        }
    )

    result = _run(graph, SetupSpec(tenant_id="tid"))

    assert result.created is False
    assert result.changes == []
    assert graph.writes() == []


def test_setup_adds_only_what_is_missing(user_dir, bootstrap) -> None:
    """Tests that an old-style registration gains the broker URI and scopes only."""
    app = _complete_app()
    app["publicClient"] = {"redirectUris": ["http://localhost"]}
    # Only the application roles were declared; delegated scopes are missing.
    app["requiredResourceAccess"] = [
        {
            "resourceAppId": entra._MS_GRAPH_APP_ID,
            "resourceAccess": [
                {"id": "role-dm", "type": "Role"},
                {"id": "role-g", "type": "Role"},
            ],
        },
        {
            "resourceAppId": "other-api",
            "resourceAccess": [{"id": "x", "type": "Scope"}],
        },
    ]
    graph = FakeGraph(
        {
            ("GET", "/servicePrincipals"): [
                _graph_sp_response(),
                {"value": [{"id": "sp"}]},
            ],
            ("GET", "/applications"): {"value": [app]},
            ("PATCH", "/applications/obj"): {},
            ("GET", "/servicePrincipals/sp/appRoleAssignments"): {
                "value": [
                    {"appRoleId": "role-dm", "resourceId": GRAPH_SP_ID},
                    {"appRoleId": "role-g", "resourceId": GRAPH_SP_ID},
                ]
            },
            ("GET", "/oauth2PermissionGrants"): {
                "value": [{"id": "grant", "scope": "User.Read"}]
            },
            ("PATCH", "/oauth2PermissionGrants/grant"): {},
        }
    )

    result = _run(graph, SetupSpec(tenant_id="tid"))

    app_patch = next(
        j for m, p, j in graph.writes() if (m, p) == ("PATCH", "/applications/obj")
    )
    assert app_patch is not None
    assert app_patch["publicClient"]["redirectUris"] == [
        "http://localhost",
        "ms-appx-web://Microsoft.AAD.BrokerPlugin/cid",
    ]
    graph_access = next(
        r
        for r in app_patch["requiredResourceAccess"]
        if r["resourceAppId"] == entra._MS_GRAPH_APP_ID
    )
    assert {(a["id"], a["type"]) for a in graph_access["resourceAccess"]} == {
        ("role-dm", "Role"),
        ("role-g", "Role"),
        ("scope-dm", "Scope"),
        ("scope-g", "Scope"),
        ("scope-u", "Scope"),
    }
    # The unrelated API's permissions are preserved verbatim.
    assert {
        "resourceAppId": "other-api",
        "resourceAccess": [{"id": "x", "type": "Scope"}],
    } in (app_patch["requiredResourceAccess"])

    grant_patch = next(
        j for m, p, j in graph.writes() if p == "/oauth2PermissionGrants/grant"
    )
    assert grant_patch is not None
    assert grant_patch["scope"].split() == sorted(entra.DELEGATED_PERMISSIONS)
    assert any("redirect" in c.lower() for c in result.changes)
    assert any("delegated" in c.lower() for c in result.changes)


def test_setup_keeps_existing_session_for_same_client(user_dir, bootstrap) -> None:
    """Tests that re-running setup does not sign out a tenant already logged in."""
    auth._save_auth_store(
        AuthStore(
            active="tid",
            tenants={"tid": AuthConfig("cid", "tid", "me@x", "x.com", "X")},
        )
    )
    graph = FakeGraph(
        {
            ("GET", "/servicePrincipals"): [
                _graph_sp_response(),
                {"value": [{"id": "sp"}]},
            ],
            ("GET", "/applications"): {"value": [_complete_app()]},
            ("GET", "/servicePrincipals/sp/appRoleAssignments"): {
                "value": [
                    {"appRoleId": "role-dm", "resourceId": GRAPH_SP_ID},
                    {"appRoleId": "role-g", "resourceId": GRAPH_SP_ID},
                ]
            },
            ("GET", "/oauth2PermissionGrants"): {
                "value": [{"id": "g", "scope": " ".join(entra.DELEGATED_PERMISSIONS)}]
            },
        }
    )
    _run(graph, SetupSpec(tenant_id="tid"))
    assert auth.load_auth_store().tenants["tid"] == AuthConfig(
        "cid", "tid", "me@x", "x.com", "X"
    )


# ---------------------------------------------------------------------------
# Lookup edge cases
# ---------------------------------------------------------------------------


def test_setup_rejects_ambiguous_display_name(user_dir, bootstrap) -> None:
    """Tests that two registrations with the same name need --client-id."""
    graph = FakeGraph(
        {
            ("GET", "/servicePrincipals"): _graph_sp_response(),
            ("GET", "/applications"): {
                "value": [{"id": "a", "appId": "1"}, {"id": "b", "appId": "2"}]
            },
        }
    )
    with pytest.raises(ConfigError, match="--client-id"):
        _run(graph, SetupSpec(tenant_id="tid"))


def test_setup_with_unknown_client_id_fails(user_dir, bootstrap) -> None:
    """Tests that an explicit --client-id must exist."""
    graph = FakeGraph(
        {
            ("GET", "/servicePrincipals"): _graph_sp_response(),
            ("GET", "/applications"): {"value": []},
        }
    )
    with pytest.raises(ConfigError, match="No app registration with client ID"):
        _run(graph, SetupSpec(tenant_id="tid", client_id="nope"))


def test_setup_fails_when_graph_lacks_permission_names(user_dir, bootstrap) -> None:
    """Tests that missing Graph permission definitions are reported, not KeyError."""
    graph = FakeGraph(
        {
            ("GET", "/servicePrincipals"): {
                "value": [
                    {"id": GRAPH_SP_ID, "appRoles": [], "oauth2PermissionScopes": []}
                ]
            }
        }
    )
    with pytest.raises(ConfigError, match="DeviceManagementApps.ReadWrite.All"):
        _run(graph, SetupSpec(tenant_id="tid"))


def test_bootstrap_failure_is_an_auth_error(user_dir) -> None:
    """Tests that a canceled or blocked administrator sign-in is explained."""
    fake_app = type(
        "App",
        (),
        {
            "acquire_token_interactive": lambda self, *a, **k: {
                "error": "access_denied",
                "error_description": "AADSTS65001: consent required",
            }
        },
    )()
    with patch("napt.upload.entra.msal.PublicClientApplication", return_value=fake_app):
        with pytest.raises(AuthError, match="access_denied") as exc:
            setup_app_registration(SetupSpec(tenant_id="tid"))
    assert "--print-only" in str(exc.value)


# ---------------------------------------------------------------------------
# Replication and federated credential
# ---------------------------------------------------------------------------


def test_consent_retries_until_service_principal_replicates(
    user_dir, bootstrap
) -> None:
    """Tests that a 404 right after SP creation is retried, other errors are not."""
    attempts = {"n": 0}

    def flaky_graph(method, url, context, headers, json=None, **kwargs):
        path = url.replace(entra._GRAPH_V1, "").split("?")[0]
        if (method, path) == ("POST", "/servicePrincipals/sp/appRoleAssignments"):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise NetworkError(f"{context}: HTTP 404\nnot found")
            return {}
        return FakeGraph(
            {
                ("GET", "/servicePrincipals"): _graph_sp_response(),
                ("GET", "/applications"): {"value": [_complete_app()]},
                ("GET", "/servicePrincipals/sp/appRoleAssignments"): {
                    "value": [{"appRoleId": "role-g", "resourceId": GRAPH_SP_ID}]
                },
                ("GET", "/oauth2PermissionGrants"): {
                    "value": [
                        {"id": "g", "scope": " ".join(entra.DELEGATED_PERMISSIONS)}
                    ]
                },
            }
        )(method, url, context, headers, json, **kwargs)

    # Second /servicePrincipals GET must return the NAPT SP; FakeGraph above is
    # rebuilt per call, so answer it explicitly.
    def graph(method, url, context, headers, json=None, **kwargs):
        path = url.replace(entra._GRAPH_V1, "").split("?")[0]
        if (method, path) == ("GET", "/servicePrincipals") and "appId eq 'cid'" in url:
            return {"value": [{"id": "sp"}]}
        return flaky_graph(method, url, context, headers, json, **kwargs)

    with (
        patch("napt.upload.entra._graph_request", graph),
        patch("napt.upload.entra.time.sleep") as sleep,
    ):
        result = setup_app_registration(SetupSpec(tenant_id="tid"))

    assert attempts["n"] == 2
    sleep.assert_called_once()
    assert "Granted application permission DeviceManagementApps.ReadWrite.All" in (
        result.changes
    )


def test_setup_adds_federated_credential_once(user_dir, bootstrap) -> None:
    """Tests that the OIDC credential is created when absent and skipped when present."""

    def base() -> dict:
        # Fresh per run: FakeGraph consumes sequenced responses as it goes.
        return {
            ("GET", "/servicePrincipals"): [
                _graph_sp_response(),
                {"value": [{"id": "sp"}]},
            ],
            ("GET", "/applications"): {"value": [_complete_app()]},
            ("GET", "/servicePrincipals/sp/appRoleAssignments"): {
                "value": [
                    {"appRoleId": "role-dm", "resourceId": GRAPH_SP_ID},
                    {"appRoleId": "role-g", "resourceId": GRAPH_SP_ID},
                ]
            },
            ("GET", "/oauth2PermissionGrants"): {
                "value": [{"id": "g", "scope": " ".join(entra.DELEGATED_PERMISSIONS)}]
            },
        }

    issuer = "https://token.actions.githubusercontent.com"
    subject = "repo:contoso/apps:environment:prod"
    spec = SetupSpec(
        tenant_id="tid",
        federated_issuer=issuer,
        federated_subject=subject,
        federated_name="github-prod",
    )

    graph = FakeGraph(
        {
            **base(),
            ("GET", "/applications/obj/federatedIdentityCredentials"): {"value": []},
            ("POST", "/applications/obj/federatedIdentityCredentials"): {},
        }
    )
    result = _run(graph, spec)
    cred = next(
        j
        for m, p, j in graph.writes()
        if p == "/applications/obj/federatedIdentityCredentials"
    )
    assert cred == {
        "name": "github-prod",
        "issuer": issuer,
        "subject": subject,
        "audiences": [entra.FEDERATED_AUDIENCE_DEFAULT],
        "description": "NAPT CI/CD (OIDC)",
    }
    assert any("federated" in c for c in result.changes)

    graph = FakeGraph(
        {
            **base(),
            ("GET", "/applications/obj/federatedIdentityCredentials"): {
                "value": [{"issuer": issuer, "subject": subject}]
            },
        }
    )
    result = _run(graph, spec)
    assert result.changes == []
    assert graph.writes() == []


# ---------------------------------------------------------------------------
# Provenance stamp and adoption
# ---------------------------------------------------------------------------


def _existing_tenant_responses(app: dict) -> dict:
    return {
        ("GET", "/servicePrincipals"): [
            _graph_sp_response(),
            {"value": [{"id": "sp"}]},
        ],
        ("GET", "/applications"): {"value": [app]},
        ("PATCH", "/applications/obj"): {},
        ("GET", "/servicePrincipals/sp/appRoleAssignments"): {
            "value": [
                {"appRoleId": "role-dm", "resourceId": GRAPH_SP_ID},
                {"appRoleId": "role-g", "resourceId": GRAPH_SP_ID},
            ]
        },
        ("GET", "/oauth2PermissionGrants"): {
            "value": [{"id": "g", "scope": " ".join(entra.DELEGATED_PERMISSIONS)}]
        },
    }


def test_stamp_round_trip_preserves_admin_notes() -> None:
    """Tests that the stamp line is replaced in place and other notes survive."""
    notes = (
        "Owned by Endpoint team\nnapt/v1 spec=0 version=0.9.0 provisioned=2026-01-01\n"
    )
    parsed = entra._parse_stamp(notes)
    assert parsed == {"spec": "0", "version": "0.9.0", "date": "2026-01-01"}

    updated = entra._with_stamp(notes)
    lines = updated.splitlines()
    assert lines[0].startswith(f"napt/v1 spec={entra.SPEC_VERSION} version=")
    assert lines[1:] == ["Owned by Endpoint team"]
    assert entra._parse_stamp(None) is None
    assert entra._parse_stamp("napt/v1 spec=x") is None


def test_setup_create_writes_stamp(user_dir, bootstrap) -> None:
    """Tests that a newly created registration carries the provenance stamp."""
    graph = FakeGraph(
        {
            ("GET", "/servicePrincipals"): [_graph_sp_response(), {"value": []}],
            ("GET", "/applications"): {"value": []},
            ("POST", "/applications"): {"id": "obj", "appId": "new"},
            ("PATCH", "/applications/obj"): {},
            ("POST", "/servicePrincipals"): {"id": "sp"},
            ("GET", "/servicePrincipals/sp/appRoleAssignments"): {"value": []},
            ("POST", "/servicePrincipals/sp/appRoleAssignments"): {},
            ("GET", "/oauth2PermissionGrants"): {"value": []},
            ("POST", "/oauth2PermissionGrants"): {},
        }
    )
    _run(graph, SetupSpec(tenant_id="tid"))
    create = next(
        j for m, p, j in graph.writes() if (m, p) == ("POST", "/applications")
    )
    assert create is not None
    assert entra._parse_stamp(create["notes"]) == {
        "spec": str(entra.SPEC_VERSION),
        "version": entra.__version__,
        "date": create["notes"].split("provisioned=")[1],
    }


def test_setup_refuses_unstamped_name_match_without_adopt(user_dir, bootstrap) -> None:
    """Tests that a portal-made registration of the same name is reported, not touched."""
    app = _complete_app()
    app["notes"] = "Created by hand"
    graph = FakeGraph(_existing_tenant_responses(app))

    result = _run(graph, SetupSpec(tenant_id="tid"))

    assert result.needs_adopt is True
    assert result.client_id == "cid"
    assert result.changes == []
    assert graph.writes() == []
    assert auth.load_auth_store().active is None  # nothing remembered either


def test_setup_adopts_unstamped_registration_with_flag(user_dir, bootstrap) -> None:
    """Tests that --adopt stamps the registration and keeps the admin's notes."""
    app = _complete_app()
    app["notes"] = "Created by hand"
    graph = FakeGraph(_existing_tenant_responses(app))

    result = _run(graph, SetupSpec(tenant_id="tid", adopt=True))

    assert result.adopted is True
    assert result.needs_adopt is False
    patch = next(
        j for m, p, j in graph.writes() if (m, p) == ("PATCH", "/applications/obj")
    )
    assert patch is not None
    assert list(patch) == ["notes"]  # nothing else needed changing
    assert patch["notes"].splitlines()[1] == "Created by hand"
    assert entra._parse_stamp(patch["notes"]) is not None
    assert result.changes == [
        f"Stamped internal notes: napt/v1 spec={entra.SPEC_VERSION} "
        f"version={entra.__version__}"
    ]
    assert auth.load_auth_store().active == "tid"


def test_setup_explicit_client_id_implies_adopt(user_dir, bootstrap) -> None:
    """Tests that naming the registration by --client-id needs no --adopt."""
    app = _complete_app()
    app["notes"] = None
    graph = FakeGraph(_existing_tenant_responses(app))

    result = _run(graph, SetupSpec(tenant_id="tid", client_id="cid"))

    assert result.needs_adopt is False
    assert result.adopted is True


def test_setup_restamps_outdated_spec(user_dir, bootstrap) -> None:
    """Tests that an older stamp is refreshed and reported as the previous spec."""
    app = _complete_app()
    app["notes"] = _stamp(spec=0, version="0.9.0")
    graph = FakeGraph(_existing_tenant_responses(app))

    result = _run(graph, SetupSpec(tenant_id="tid"))

    assert result.previous_spec == 0
    assert result.adopted is False
    patch = next(
        j for m, p, j in graph.writes() if (m, p) == ("PATCH", "/applications/obj")
    )
    assert patch is not None and list(patch) == ["notes"]
    assert f"spec={entra.SPEC_VERSION}" in patch["notes"]
