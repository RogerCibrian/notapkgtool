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

"""The `napt auth` command.

Manages the credential NAPT uses for Intune through the `login`,
`logout`, `status`, and `setup` subcommands.
"""

from __future__ import annotations

import argparse

from napt.auth.credentials import (
    AuthStatus,
    get_status as auth_status,
    load_auth_store,
    login as auth_login,
    logout as auth_logout,
)
from napt.auth.registration import (
    APPLICATION_PERMISSIONS,
    BROKER_REDIRECT_TEMPLATE,
    DELEGATED_PERMISSIONS,
    FEDERATED_AUDIENCE_DEFAULT,
    LOCALHOST_REDIRECT,
    SPEC_VERSION,
    SetupSpec,
    setup_app_registration,
)
from napt.exceptions import AuthError, ConfigError, NetworkError
from napt.logging import get_logger, set_global_logger


def _print_auth_status(status: AuthStatus) -> None:
    """Prints one credential's status block for 'napt auth status'/'login'."""
    print(f"Method:      {status.method}")
    print(f"Account:     {status.account or '(unknown)'}")
    print(f"Tenant:      {status.tenant_id or '(unknown)'}")
    print(f"Client ID:   {status.client_id or '(unknown)'}")
    if status.expires_at is not None:
        print(f"Expires:     {status.expires_at.isoformat(timespec='seconds')}")
    print(f"Permissions: {', '.join(status.permissions) or '(none)'}")
    if status.missing:
        print()
        print(f"[WARNING] Missing required permissions: {', '.join(status.missing)}")
        print(
            "          Add them to the app registration (application permissions "
            "for CI/CD,\n          delegated for interactive use) and grant admin "
            "consent."
        )


def _print_known_tenants() -> None:
    """Lists tenants remembered by 'napt auth login', marking the active one."""
    try:
        store = load_auth_store()
    except ConfigError:
        return
    if not store.tenants:
        return
    print()
    print("Known tenants:")
    for tenant_id, cfg in store.tenants.items():
        marker = "*" if tenant_id == store.active else " "
        print(f"  {marker} {cfg.label or '(name unknown)'}")
        print(f"      Account:   {cfg.username or '(signed out)'}")
        print(f"      Tenant ID: {tenant_id}")
        print(f"      Client ID: {cfg.client_id}")
    print("  (* = active; switch with 'napt auth login --tenant-id <id or domain>')")


def cmd_auth_login(args: argparse.Namespace) -> int:
    """Handler for 'napt auth login' command.

    Signs in interactively through the OS broker or the browser and caches
    the session so later commands authenticate silently.

    Args:
        args: Parsed command-line arguments containing optional client and
            tenant IDs and the --no-broker flag.

    Returns:
        Exit code (0 for success, 1 for failure).

    """
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    try:
        status = auth_login(
            client_id=args.client_id,
            tenant_id=args.tenant_id,
            use_broker=not args.no_broker,
        )
    except (AuthError, ConfigError) as err:
        print(f"Authentication error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    print()
    print(f"[OK] Signed in as {status.account or '(unknown account)'}")
    print()
    _print_auth_status(status)
    return 0


def cmd_auth_logout(args: argparse.Namespace) -> int:
    """Handler for 'napt auth logout' command.

    Removes the active tenant's cached session, or every tenant's with
    --all. Client and tenant IDs are kept for the next login.

    Args:
        args: Parsed command-line arguments containing the --all flag and
            debug flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    """
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    try:
        removed = auth_logout(all_tenants=args.all)
    except (AuthError, ConfigError) as err:
        print(f"Authentication error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    if removed:
        print(
            f"[OK] Signed out of {len(removed)} tenant(s): {', '.join(removed)}. "
            "Run 'napt auth login' to sign in again."
        )
    else:
        print("No interactive session to sign out of.")
    return 0


def cmd_auth_status(args: argparse.Namespace) -> int:
    """Handler for 'napt auth status' command.

    Shows which credential NAPT would use right now -- the same resolution
    'napt upload' performs -- and flags missing Graph permissions.

    Args:
        args: Parsed command-line arguments containing debug flags.

    Returns:
        Exit code (0 when a credential is available, 1 otherwise).

    """
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    try:
        status = auth_status()
    except (AuthError, ConfigError) as err:
        print(f"Authentication error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    if status is None:
        print("Not authenticated.")
        print()
        print("  Interactive:  run 'napt auth login'")
        print("  CI/CD:        set AZURE_CLIENT_ID, AZURE_TENANT_ID and either")
        print("                AZURE_CLIENT_SECRET / AZURE_CLIENT_CERTIFICATE_PATH,")
        print("                or sign in with 'az login' (e.g. azure/login in CI)")
        _print_known_tenants()
        return 1

    _print_auth_status(status)
    if status.method.startswith("interactive"):
        _print_known_tenants()
    return 0 if not status.missing else 1


def _print_setup_checklist(spec: SetupSpec) -> None:
    """Prints the portal steps equivalent to what 'napt auth setup' automates."""
    client_id = spec.client_id or "<Application (client) ID>"
    print(f"App registration checklist for tenant {spec.tenant_id}:")
    print()
    print("  1. Entra admin center -> App registrations -> New registration")
    print(f"     Name: {spec.display_name}; accounts in this directory only")
    print("  2. Authentication -> Add a platform -> Mobile and desktop applications")
    print(f"     - {LOCALHOST_REDIRECT}")
    print(f"     - {BROKER_REDIRECT_TEMPLATE.format(client_id=client_id)}")
    print("  3. API permissions -> Add a permission -> Microsoft Graph")
    print(f"     Application: {', '.join(APPLICATION_PERMISSIONS)}")
    print(f"     Delegated:   {', '.join(DELEGATED_PERMISSIONS)}")
    print("  4. Grant admin consent")
    if spec.federated_subject:
        print("  5. Certificates & secrets -> Federated credentials -> Add credential")
        print(f"     Name:     {spec.federated_credential_name}")
        print(f"     Issuer:   {spec.federated_issuer}")
        print(f"     Subject:  {spec.federated_subject}")
        print(f"     Audience: {spec.federated_audience}")
    print()
    print("Then: napt auth login --tenant-id <tenant id> --client-id <client id>")


def cmd_auth_setup(args: argparse.Namespace) -> int:
    """Handler for 'napt auth setup' command.

    Creates or completes the NAPT app registration in a tenant through
    Microsoft Graph, or with --print-only prints the equivalent portal
    checklist without signing in.

    Args:
        args: Parsed command-line arguments containing the tenant ID,
            optional name, client ID, federated credential settings, and flags.

    Returns:
        Exit code (0 for success, 1 for failure).

    """
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    try:
        spec = SetupSpec(
            tenant_id=args.tenant_id,
            display_name=args.name,
            client_id=args.client_id,
            federated_issuer=args.federated_issuer,
            federated_subject=args.federated_subject,
            federated_audience=args.federated_audience,
            federated_name=args.federated_name,
            adopt=args.adopt,
        )
    except ConfigError as err:
        print(f"Error: {err}")
        return 1

    if args.print_only:
        _print_setup_checklist(spec)
        return 0

    try:
        result = setup_app_registration(spec)
    except (AuthError, ConfigError, NetworkError) as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    print()
    if result.needs_adopt:
        print(
            f"[WARNING] Found existing registration '{result.display_name}' "
            f"({result.client_id}) that NAPT did not create."
        )
        print("          Re-run with --adopt to manage it. Adopting adds NAPT's")
        print("          redirect URIs, Microsoft Graph permissions, and admin")
        print("          consent, and stamps the registration's internal notes;")
        print("          it never removes existing settings.")
        print(
            "          To create a new registration instead, re-run with "
            f"--name <a name other than '{result.display_name}'>."
        )
        return 1

    if result.adopted:
        print(
            f"[OK] Adopted '{result.display_name}' ({result.client_id}) -- "
            f"stamped as napt/v1 spec={SPEC_VERSION}. Changes made:"
        )
    elif result.changes:
        print("[OK] App registration is ready. Changes made:")
    else:
        print(
            f"[OK] App registration '{result.display_name}' is at spec "
            f"{SPEC_VERSION}; nothing to change."
        )
    for change in result.changes:
        print(f"  - {change}")
    print()
    print(f"Name:       {result.display_name}")
    print(f"Tenant ID:  {result.tenant_id}")
    print(f"Client ID:  {result.client_id}")
    print()
    print("Next steps:")
    print("  Interactive: napt auth login")
    print("  CI/CD:       set AZURE_TENANT_ID and AZURE_CLIENT_ID to the values above")
    if spec.federated_subject:
        print("               and let your CI platform's OIDC login mint the token")
        print("               (e.g. azure/login on GitHub Actions) -- no secret needed")
    else:
        print("               plus AZURE_CLIENT_SECRET, or re-run with")
        print("               --federated-issuer/--federated-subject to add an OIDC")
        print("               federated credential instead")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'auth' command parser and its subcommands.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_auth = subparsers.add_parser(
        "auth",
        help="Sign in to Microsoft Graph and inspect credentials",
        description=(
            "Manage the credential NAPT uses for Intune.\n\n"
            "Examples:\n"
            "  napt auth setup --tenant-id <id>\n"
            "  napt auth login --tenant-id <id> --client-id <id>\n"
            "  napt auth login\n"
            "  napt auth status\n"
            "  napt auth logout\n\n"
            "See docs for app registration setup."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    auth_sub = parser_auth.add_subparsers(
        dest="subcommand",
        help="Auth subcommands",
        required=True,
    )

    parser_auth_login = auth_sub.add_parser(
        "login",
        help="Sign in interactively (browser or OS broker)",
        description=(
            "Sign in interactively and cache the session so later commands\n"
            "authenticate silently. Uses the Windows broker (WAM) when\n"
            "available, otherwise the system browser.\n\n"
            "The tenant, client ID, and account are remembered after the first\n"
            "login. Pass --tenant-id to switch between signed-in tenants (no\n"
            "prompt when that tenant's session is still valid)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_auth_login.add_argument(
        "--tenant-id",
        default=None,
        help=(
            "Directory (tenant) ID, or the default domain of a tenant you have "
            "signed in to before (defaults to the active tenant)"
        ),
    )
    parser_auth_login.add_argument(
        "--client-id",
        default=None,
        help=(
            "Application (client) ID of the NAPT app registration "
            "(needed the first time you sign in to a tenant)"
        ),
    )
    parser_auth_login.add_argument(
        "--no-broker",
        action="store_true",
        help="Use the browser even when the OS broker is available",
    )
    parser_auth_login.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_auth_login.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_auth_login.set_defaults(func=cmd_auth_login)

    parser_auth_logout = auth_sub.add_parser(
        "logout",
        help="Remove the cached interactive session",
        description=(
            "Sign out of the active tenant's cached session (or every "
            "tenant's with --all)."
        ),
    )
    parser_auth_logout.add_argument(
        "--all",
        action="store_true",
        help="Sign out of every remembered tenant",
    )
    parser_auth_logout.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_auth_logout.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_auth_logout.set_defaults(func=cmd_auth_logout)

    parser_auth_status = auth_sub.add_parser(
        "status",
        help="Show which credential NAPT would use and its permissions",
        description=(
            "Show the credential NAPT would use right now (the same resolution\n"
            "'napt upload' performs), the account and tenant it belongs to, and\n"
            "the Graph permissions it carries. Exits 1 when no credential is\n"
            "available or a required permission is missing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_auth_status.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_auth_status.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_auth_status.set_defaults(func=cmd_auth_status)

    parser_auth_setup = auth_sub.add_parser(
        "setup",
        help="Create or complete the NAPT app registration in a tenant",
        description=(
            "Create the NAPT app registration in Microsoft Entra ID, or bring an\n"
            "existing one up to spec: redirect URIs, Microsoft Graph permissions\n"
            "(application and delegated), service principal, and admin consent.\n"
            "Optionally adds a federated credential so a CI/CD platform can obtain\n"
            "tokens through OIDC without a client secret.\n\n"
            "Requires an account holding at least the Application Administrator\n"
            "role. NAPT does not store that account or its tokens (your browser\n"
            "may keep its own sign-in). Re-running is safe: NAPT compares the\n"
            "registration with what this version needs and adds what is missing,\n"
            "never removing anything.\n\n"
            "Examples:\n"
            "  napt auth setup --tenant-id <id>\n"
            "  napt auth setup --tenant-id <id> \\\n"
            "      --federated-issuer https://token.actions.githubusercontent.com \\\n"
            "      --federated-subject repo:contoso/intune-apps:ref:refs/heads/main\n"
            "  napt auth setup --tenant-id <id> --print-only"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_auth_setup.add_argument(
        "--tenant-id",
        required=True,
        help="Directory (tenant) ID to provision in",
    )
    parser_auth_setup.add_argument(
        "--name",
        default="NAPT",
        help="Display name of the app registration to find or create (default: NAPT)",
    )
    parser_auth_setup.add_argument(
        "--client-id",
        default=None,
        help="Bring this existing registration up to spec instead of matching by name",
    )
    parser_auth_setup.add_argument(
        "--federated-issuer",
        default=None,
        metavar="URL",
        help=(
            "OIDC issuer of a CI platform to trust, e.g. "
            "https://token.actions.githubusercontent.com (requires --federated-subject)"
        ),
    )
    parser_auth_setup.add_argument(
        "--federated-subject",
        default=None,
        metavar="SUBJECT",
        help=(
            "Subject claim the platform presents for the trusted workflow, in the "
            "platform's format, e.g. repo:owner/name:ref:refs/heads/main"
        ),
    )
    parser_auth_setup.add_argument(
        "--federated-audience",
        default=FEDERATED_AUDIENCE_DEFAULT,
        metavar="AUDIENCE",
        help=f"Audience claim (default: {FEDERATED_AUDIENCE_DEFAULT})",
    )
    parser_auth_setup.add_argument(
        "--federated-name",
        default=None,
        metavar="NAME",
        help="Name of the federated credential (default: derived from the subject)",
    )
    parser_auth_setup.add_argument(
        "--adopt",
        action="store_true",
        help=(
            "Manage a registration matched by name that NAPT did not create "
            "(adds what is missing, never removes anything)"
        ),
    )
    parser_auth_setup.add_argument(
        "--print-only",
        action="store_true",
        help="Print the portal checklist instead of changing anything",
    )
    parser_auth_setup.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_auth_setup.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_auth_setup.set_defaults(func=cmd_auth_setup)
