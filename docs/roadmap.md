# NAPT roadmap

## Philosophy

Entries here are ideas, not commitments. Priorities shift with user feedback, technical findings, and contributions.

**Status Legend:**

- 💡 **Idea**: Unformed thought, needs refinement
- 🔬 **Investigating**: Researching feasibility/approach
- 📋 **Ready**: Well-defined, ready for implementation
- 🚧 **In Progress**: Actively being developed
- ✅ **Completed**: Implemented and released

---

## Quick reference

| Feature | Status | Category | Complexity | Value |
|---------|--------|----------|------------|-------|
| `napt auth setup` Command | ✅ Completed | User-Facing | Medium | High |
| Pre/Post Install/Uninstall Script Support | 💡 Idea | User-Facing | Low | Medium |
| Enhanced CLI Help Menu | 💡 Idea | User-Facing | Low | Medium |
| Intune App Categorization & Scope Tags | 💡 Idea | User-Facing | Medium | Medium |
| Configurable Install-Entry Cutover Ring | 💡 Idea | User-Facing | Medium | Medium |
| PowerShell Validation | 💡 Idea | Code Quality | High | High |
| Recipe Linting & Best Practices | 💡 Idea | Code Quality | High | Medium |
| Prerelease Version Ranking in Detection Scripts | 💡 Idea | Code Quality | Medium | Low |
| Typed Config with Dataclasses | 💡 Idea | Code Quality | Medium | Medium |
| EXE Version Extraction | 💡 Idea | Technical | High | Medium |
| Parallel Package Building | 💡 Idea | Technical | Medium | Medium |
| Minify Scripts at Intune Upload | 💡 Idea | Technical | Medium | Medium |

**Summary:**

- ✅ **Completed** (since the last release): 1
- 💡 **Ideas**: 11
- **Total**: 12 features

---

## Active work

_Nothing currently in progress._

---

## Future ideas (by category)

> **User-facing features** are things recipe authors notice.
> **Code quality & validation** covers recipe checking and linting.
> **Technical enhancements** are internal performance and infrastructure work.

### User-facing features

#### Intune app categorization & scope tags

**Status**: 💡 Idea
**Complexity**: Medium (1-3 days)
**Value**: Medium

**Description**: Add `intune.category` and `intune.role_scope_tag_ids` as
recipe fields.
Both require a Graph API lookup before the app POST: category names must be
resolved to IDs via `GET /deviceAppManagement/mobileAppCategories`, and scope
tag names must be resolved via `GET /deviceManagement/roleScopeTags`.

**Benefits**:

- Categorized apps are easier to find in the Intune portal and Company Portal
- Scope tags enable RBAC so only authorized admins can see/manage an app

**Dependencies**:

- Requires two additional Graph API calls per upload (one per lookup type)
- Error handling needed when a name doesn't match any tenant entry

#### Pre/Post install/uninstall script support

**Status**: 💡 Idea
**Complexity**: Low (few hours to 1 day)
**Value**: Medium

**Description**: Add support for pre-install, post-install, pre-uninstall, and
post-uninstall script blocks in recipes, allowing separate script sections for
each deployment phase.

**Benefits**:

- Matches PSADT's existing deployment phases, so prep, install, and cleanup
  scripts don't have to share one block

#### Enhanced CLI help menu

**Status**: 💡 Idea
**Complexity**: Low (few hours to 1 day)
**Value**: Medium

**Description**: Improve the `napt -h` help output: group commands by
category (discovery, building, packaging, deployment), add examples for
common workflows, and point at `--verbose` and `--debug` for troubleshooting.

**Benefits**:

- Cuts how often users have to leave the terminal for the docs

#### Configurable install-entry cutover ring

**Status**: 💡 Idea
**Complexity**: Medium (1-3 days)
**Value**: Medium

**Description**: Today the same promotion plan that starts a release's
rollout in the first ring also points new installs at it (the `assign`
action), so net-new devices receive the release before it has baked.
Add an optional `deployment.install` setting (e.g.
`after_ring: <ring-name>`) so the install assignment follows the release
only once it has entered that ring: the planner gates the `assign`
action on ring state instead of planning it on publish.
Default stays immediate cutover.

**Benefits**:

- Net-new devices keep receiving the proven release while the new one
  bakes through early rings
- A release held or rolled back before the cutover ring never reaches
  new installs at all
- Org-policy knob in `defaults/org.yaml`, per-recipe overridable like
  the rest of `deployment`

**Dependencies**:

- New recipe field: run `/add-recipe-field` for validation and
  recipe-reference updates

**Related**: Deferring the cutover opens a small churn window: a new
device in a ring group that already carries the new release installs
the old one and updates right away.
Bounded by the bake time of rings before the cutover point, so small
with a pilot-sized first ring.

### Code quality & validation

#### PowerShell validation

**Status**: 💡 Idea
**Complexity**: High (3-5 days)
**Value**: High

**Description**: Validate PowerShell syntax in recipe install/uninstall blocks
to catch errors before deployment.

**Benefits**:

- Fewer failed deployments caused by a typo in an install script

**Related**: Overlaps with Recipe Linting & Best Practices below; syntax
checking is the narrower first step.

#### Recipe linting & best practices

**Status**: 💡 Idea
**Complexity**: High (3-5 days)
**Value**: Medium

**Description**: Advanced recipe validation beyond syntax checking, including
PSADT function validation, deprecation warnings, anti-pattern detection, and
style guide enforcement.

**Benefits**:

- Higher quality, more consistent recipes, and a teaching aid for new users

#### Prerelease version ranking in detection scripts

**Status**: 💡 Idea
**Complexity**: Medium (1-3 days)
**Value**: Low

**Description**: Rank prerelease identifiers (beta, alpha, rc) when comparing
versions in detection and requirements scripts.
`Compare-VersionString` in `_shared_functions.ps1` strips non-numeric
decoration, so `1.2.3-beta` currently compares equal to `1.2.3`.
Semver-style ordering would treat prereleases as older than the release.

**Benefits**:

- Correct upgrade behavior when a prerelease of the target version is
    installed (currently treated as already up to date)
- More accurate version logging in CMTrace output

**Prerequisites**:

- Evidence that deployed apps actually publish prerelease `DisplayVersion`
    strings (Windows uninstall metadata rarely follows semver)

**Related**: First iteration shipped with non-numeric segments counted as 0
and a CMTrace warning when decoration is stripped

#### Typed config with dataclasses

**Status**: 💡 Idea
**Complexity**: Medium (1-3 days)
**Value**: Medium

**Description**: Convert the dict-based default configuration to typed
dataclasses once the schema and naming are finalized.
Provides IDE autocomplete, type checking, and catches config key typos at
development time.

**Benefits**:

- Self-documenting structure with type hints
- Better refactoring support

**Prerequisites**:

- Schema should be stable (post-1.0 or when churn slows)
- Current dict approach works well for rapid iteration

### Technical enhancements

#### EXE version extraction

**Status**: 💡 Idea
**Complexity**: High (3-5 days)
**Value**: Medium

**Description**: Extract version information from PE (Portable Executable)
headers for .exe installers.

**Benefits**:

- Enables version discovery for applications distributed as EXE
- Useful for vendors who don't provide version in URL or API

**Related**: `url_download` only extracts versions from MSI and MSIX installers
today and raises `ConfigError` for other extensions when no version is
discoverable.

#### Parallel package building

**Status**: 💡 Idea
**Complexity**: Medium (1-3 days)
**Value**: Medium

**Description**: Build multiple PSADT packages in parallel for faster
multi-app workflows.

**Benefits**:

- Faster builds for orgs with 50+ apps, especially monthly update cycles

#### Minify scripts at Intune upload

**Status**: 💡 Idea
**Complexity**: Medium (1-3 days)
**Value**: Medium

**Description**: Minify detection and requirements scripts in memory when
preparing them for Intune upload, so the payload sent to Intune is smaller
while on-disk build output stays readable.
Conservative approach: strip comment-only lines, blank lines, and trailing
whitespace (no AST).
Optional: PowerShell-invoked AST-based minifier for greater reduction.

**Benefits**:

- Reduces per-app script size in the Intune policy payload
- Helps organizations approaching the Intune 4 MB policy limit

**Dependencies**:

- Hooks into the existing `napt upload` path where detection and
  requirements scripts are read from `packages/` and embedded in the
  Graph payload

**Related**: Intune default policy limit is 4 MB total; NAPT detection +
requirements scripts are ~40 KB per app (~70-100 apps depending on code
signing)

---

## Declined / won't implement

---

## Recently completed

#### `napt auth setup` command

**Status**: ✅ Completed
**Complexity**: Medium
**Value**: High

**Description**: `napt auth setup --tenant-id <id>` creates the NAPT app
registration in Microsoft Entra ID directly through Microsoft Graph (no
Azure CLI dependency), or brings an existing one up to spec: redirect URIs,
application and delegated Graph permissions, service principal, and admin
consent.
Shipped alongside `napt auth login`, `status`, and `logout`.

**Notes**:

- Re-running is safe: compares the registration with what the installed
  NAPT version needs and adds only what is missing, never removing anything
- `--federated-issuer` / `--federated-subject` add a federated credential
  so CI/CD can authenticate through OIDC without a client secret
- Registrations are stamped with a provenance note; an unstamped name
  match is left untouched unless `--adopt` is given
- `--print-only` prints the equivalent portal checklist for tenants where
  the automated path is not allowed

**Related**: See [User Guide - App Registration Setup](user-guide.md#app-registration-setup).

---

Everything shipped in earlier releases is in the [changelog](changelog.md).
