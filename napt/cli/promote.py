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

"""The `napt promote` command.

Plans and applies ring-based promotion of published apps through the
`plan` and `apply` subcommands.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from napt.auth.credentials import get_access_token
from napt.exceptions import (
    AuthError,
    ConfigError,
    NAPTError,
    NetworkError,
    StateError,
)
from napt.graph.intune import list_mobile_apps
from napt.logging import get_logger, set_global_logger
from napt.promote import (
    apply_plan,
    detect_drift,
    load_recipe_configs,
    plan_promotions,
    plans_dir_for,
    reconcile_publications,
    resolve_state_dir,
    unresolvable_groups,
    write_plan_files,
)


def _describe_action(action: dict[str, Any]) -> str:
    """Formats one planned promotion action as a summary line.

    Reuses the action's ``summary`` — the same sentence written to the
    plan file — so console output and plan files never disagree.

    Args:
        action: A planned action dict from plan_promotions.

    Returns:
        A one-line ASCII description for console output.
    """
    return f"{action['app_id']}: {action['summary']}"


def _print_drift(drift: list[dict[str, Any]]) -> None:
    """Prints drift findings as a warnings section."""
    print()
    print("=" * 70)
    print("DRIFT CHECK")
    print("=" * 70)
    if drift:
        for finding in drift:
            print(f"  [WARNING] {finding['app_id']}: {finding['detail']}")
    else:
        print("  No drift detected.")
    print("=" * 70)


def _print_recovered(recovered: list[dict[str, Any]]) -> None:
    """Prints publication reconciliation findings as a section."""
    print()
    print("=" * 70)
    print("PUBLICATION RECONCILIATION")
    print("=" * 70)
    if recovered:
        for finding in recovered:
            marker = "[OK]" if finding["kind"] == "recovered" else "[WARNING]"
            print(f"  {marker} {finding['app_id']}: {finding['detail']}")
    else:
        print("  Nothing to recover.")
    print("=" * 70)


def cmd_promote_plan(args: argparse.Namespace) -> int:
    """Handler for 'napt promote plan' command.

    Computes promotion actions for all recipes (or one recipe) as a pure
    function of deployment state, configuration, and the clock, and
    writes one plan file per app with work. Read-only with respect to
    Intune, and — unless --reconcile recovers a lost publication
    writeback first — to deployment state; an app's stale plan file is
    removed when none of its actions remain eligible.

    Args:
        args: Parsed command-line arguments containing the recipes path,
            state directory, and flags.

    Returns:
        Exit code (0 for success — with or without planned actions,
        1 for failure).

    """
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipes = Path(args.recipes)

    print(f"Planning promotions for: {recipes}")
    print()

    try:
        state_dir = (
            Path(args.state_dir)
            if args.state_dir is not None
            else resolve_state_dir(recipes)
        )
        configs = load_recipe_configs(recipes)
        recovered: list[dict[str, Any]] = []
        drift: list[dict[str, Any]] = []
        if args.reconcile or args.check_drift:
            # One authenticated session serves reconciliation, plan
            # validation, and the drift check. Reconciliation runs
            # before planning so recovered releases are promotable this
            # run; drift runs after it so repaired state is compared.
            access_token = get_access_token()
            existing_apps = list_mobile_apps(access_token)
            group_id_cache: dict[str, str] = {}
            if args.reconcile:
                recovered = reconcile_publications(
                    access_token, configs, state_dir / "deployment", existing_apps
                )
            actions = plan_promotions(recipes, state_dir=state_dir / "deployment")
            # A plan with an unresolvable group must never become a
            # reviewable promotion PR: fail hard instead of writing it.
            problems = unresolvable_groups(access_token, actions, group_id_cache)
            if problems:
                raise ConfigError(
                    "Plan validation failed; no plan was written. "
                    "Unresolvable groups:\n  "
                    + "\n  ".join(problems)
                    + "\nFix the group configuration and re-run."
                )
            if args.check_drift:
                drift = detect_drift(
                    access_token,
                    configs,
                    state_dir / "deployment",
                    existing_apps,
                    group_id_cache=group_id_cache,
                )
        else:
            actions = plan_promotions(recipes, state_dir=state_dir / "deployment")
            if actions:
                logger.warning(
                    "PROMOTE",
                    "Plan groups not validated against Entra ID (offline "
                    "run); apply validates them before assigning.",
                )
        written = write_plan_files(actions, state_dir, configs)
    except AuthError as err:
        print(f"Authentication error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except (ConfigError, StateError) as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except NAPTError as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    print("=" * 70)
    print("PROMOTION PLAN")
    print("=" * 70)
    if actions:
        for action in actions:
            print(f"  {_describe_action(action)}")
        print("=" * 70)
        print()
        print(
            f"[OK] Plan written: {len(written)} file(s) in "
            f"{plans_dir_for(state_dir)} ({len(actions)} action(s))"
        )
    else:
        print("  No promotions eligible.")
        print("=" * 70)
        print()
        print("[OK] Nothing to promote. No plan files needed.")

    if args.reconcile:
        _print_recovered(recovered)
    if args.check_drift:
        _print_drift(drift)

    return 0


def cmd_promote_apply(args: argparse.Namespace) -> int:
    """Handler for 'napt promote apply' command.

    Executes promotion plans against Intune: assigns install entries,
    promotes releases through rings, displaces the older releases they
    replace, and retires them per the retention policy. Consumes each
    per-app plan file after its app applies fully; otherwise plans
    fresh and applies immediately. One app's failure keeps its plan
    file for retry and never blocks the others, and stale or
    already-applied actions are skipped with a warning, so re-running
    after a partial failure is safe.

    Args:
        args: Parsed command-line arguments containing the recipes path,
            state directory, plan file, and flags.

    Returns:
        Exit code (0 for success — including nothing to apply,
        1 for failure, including any app whose plan failed to apply).

    """
    logger = get_logger(verbose=args.verbose, debug=args.debug)
    set_global_logger(logger)

    recipes = Path(args.recipes)

    print(f"Applying promotions for: {recipes}")
    print()

    try:
        state_dir = (
            Path(args.state_dir)
            if args.state_dir is not None
            else resolve_state_dir(recipes)
        )
        summary = apply_plan(
            recipes,
            state_dir=state_dir,
            plan_file=args.plan_file,
        )
    except AuthError as err:
        print(f"Authentication error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except (ConfigError, NetworkError, StateError) as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1
    except NAPTError as err:
        print(f"Error: {err}")
        if args.verbose or args.debug:
            import traceback

            traceback.print_exc()
        return 1

    applied = summary["applied"]
    skipped = summary["skipped"]
    failed = summary["failed"]

    print("=" * 70)
    print("PROMOTION APPLY")
    print("=" * 70)
    if not applied and not skipped and not failed:
        print("  Nothing to apply.")
    for action in applied:
        print(f"  [OK] {_describe_action(action)}")
    for entry in skipped:
        print(f"  [SKIP] {_describe_action(entry['action'])} ({entry['reason']})")
    for entry in failed:
        print(f"  [FAIL] {entry['app_id']}: {entry['error']}")
    print("=" * 70)

    if summary.get("recovered"):
        _print_recovered(summary["recovered"])
    if summary.get("drift"):
        _print_drift(summary["drift"])

    print()
    if failed:
        print(
            f"[FAIL] Applied {len(applied)} action(s), skipped "
            f"{len(skipped)}; {len(failed)} app(s) failed and kept "
            "their plan files. Fix the errors and re-run."
        )
        return 1
    print(f"[SUCCESS] Applied {len(applied)} action(s), " f"skipped {len(skipped)}.")

    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registers the 'promote' command parser and its subcommands.

    Args:
        subparsers: The CLI's subparsers action to add the command to.
    """
    parser_promote = subparsers.add_parser(
        "promote",
        help="Plan and apply deployment ring promotion",
        description=(
            "Plan and apply ring-based promotion of published apps.\n\n"
            "Examples:\n"
            "  napt promote plan\n"
            "  napt promote apply\n"
            "  napt promote plan recipes/Google/chrome.yaml\n\n"
            "See docs for the promotion model and workflows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    promote_sub = parser_promote.add_subparsers(
        dest="subcommand",
        help="Promotion subcommands",
        required=True,
    )
    parser_promote_plan = promote_sub.add_parser(
        "plan",
        help="Compute eligible promotions and write per-app plan files",
        description=(
            "Compute which releases are ready to promote through deployment "
            "rings, and write one state/plans/<app>.json file per app with "
            "work. "
            "Never modifies Intune. Read-only for deployment state too, "
            "except that --reconcile writes it when recovering a lost "
            "publication writeback. With --check-drift or --reconcile, "
            "every group in the plan is validated against Entra ID and an "
            "unresolvable group fails the run without writing any plan. "
            "An app's stale plan file is removed when nothing is eligible "
            "for it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_promote_plan.add_argument(
        "recipes",
        nargs="?",
        default="recipes",
        help="Recipe file or directory to plan for (default: recipes/)",
    )
    parser_promote_plan.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=(
            "State directory holding deployment/ and plans/ "
            "(default: directories.state from config)"
        ),
    )
    parser_promote_plan.add_argument(
        "--check-drift",
        action="store_true",
        help=(
            "Also compare Intune assignments against deployment state "
            "(requires Graph credentials); findings are warnings only"
        ),
    )
    parser_promote_plan.add_argument(
        "--reconcile",
        action="store_true",
        help=(
            "Before planning, record publications that are committed in "
            "Intune but whose deployment state writeback was lost, so "
            "they are promotable in this run (requires Graph credentials; "
            "writes deployment state)"
        ),
    )
    parser_promote_plan.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_promote_plan.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_promote_plan.set_defaults(func=cmd_promote_plan)

    parser_promote_apply = promote_sub.add_parser(
        "apply",
        help="Execute promotion plans against Intune",
        description=(
            "Execute promotion actions: assign install entries, promote "
            "releases through rings, displace the older releases they "
            "replace, and retire them per deployment.retain_versions. "
            "Consumes each per-app plan "
            "file in state/plans/ when any exist; otherwise plans fresh "
            "and applies immediately. One app's failure keeps its plan "
            "file and never blocks the others, and stale or "
            "already-applied actions are skipped, so re-running is safe."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_promote_apply.add_argument(
        "recipes",
        nargs="?",
        default="recipes",
        help="Recipe file or directory to apply for (default: recipes/)",
    )
    parser_promote_apply.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=(
            "State directory holding deployment/ and plans/ "
            "(default: directories.state from config)"
        ),
    )
    parser_promote_apply.add_argument(
        "--plan-file",
        type=Path,
        default=None,
        help=(
            "Single plan file to execute (default: every file in "
            "<state-dir>/plans/ if any exist)"
        ),
    )
    parser_promote_apply.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show progress and high-level status updates",
    )
    parser_promote_apply.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show detailed debugging output (implies --verbose)",
    )
    parser_promote_apply.set_defaults(func=cmd_promote_apply)
