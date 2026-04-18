---
name: roadmap
description: Add or update an entry in docs/roadmap.md. Enforces the standard structure (Status / Complexity / Value / Description / Benefits / Prerequisites / Dependencies / Related) and category placement.
disable-model-invocation: true
user-invocable: true
allowed-tools: Read Edit Write Glob Grep
argument-hint: "feature name and brief description"
---

You are adding or updating a roadmap entry in `docs/roadmap.md`. Follow the structure exactly.

## Step 1: Decide the action

- **Add new entry:** the user described a deferred feature ("add to roadmap", "let's do this later")
- **Update existing entry:** the user is changing status, complexity, or scope of something already in the roadmap

If unclear, read `docs/roadmap.md` first and ask.

## Step 2: Determine the category

Group entries by:
- **User-Facing Features** — things end users will notice
- **Code Quality & Validation** — internal correctness improvements
- **Technical Enhancements** — perf, infra, refactoring with technical payoff

If the feature doesn't clearly belong to any category, ask before assuming.

## Step 3: Write the entry

Use this exact format:

```markdown
#### Feature Name

**Status**: 💡 Idea
**Complexity**: Low (few hours to 1 day)
**Value**: High

**Description**: One-paragraph description of what the feature does and
why it matters. Wrap at 80 chars.

**Benefits**:

- Benefit 1
- Benefit 2

**Prerequisites**: (optional — external things that must exist before work starts)

- Item 1

**Dependencies**: (optional — NAPT features or technical blockers)

- Item 1

**Related**: Link or inline note (no bullet list)
```

## Field rules

- Use `####` (H4) headings — **no status emoji in the header**
- `**Status**`, `**Complexity**`, `**Value**` have no blank lines between them; blank line after the group
- Complexity always includes a time estimate for active/idea entries:
  - `Low (few hours to 1 day)`
  - `Medium (1-3 days)`
  - `High (3-5 days)`
  - `Very High (5-10 days)`
  - Omit the estimate for completed entries (e.g., just `High`)
- `**Benefits**:` always has a blank line before the bullet list
- `**Prerequisites**:` — things that must exist externally before starting (e.g., Azure CLI, stable schema)
- `**Dependencies**:` — technical blockers or other NAPT features that must be built first
- `**Related**:` — inline note or link, no bullet list
- For completed entries, use `**Changes**:` (what was done) or `**Notes**:` (implementation details) instead of Benefits

## Status progression

💡 Idea → 🔬 Investigating → 📋 Ready → 🚧 In Progress → ✅ Completed

## Don't add

- Bug reports (use GitHub issues)
- Small enhancements that could just be done now
- Vague ideas without a clear value statement

## Step 4: Insert in the right place

- New entries: place at the bottom of the appropriate category section
- Status changes: edit in place
- Completed entries: leave in their category but update Status, swap Benefits → Changes/Notes, drop the Complexity time estimate

## Step 5: Confirm

Tell the user: which category, what status, and the exact heading you used. Don't over-explain — a one-line summary is enough.
