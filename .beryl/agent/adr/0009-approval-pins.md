# ADR 0009: Approval pins hash a concept's plan and accepted code

## Status

Accepted (2026-09-17)

## Context

`run` re-plans and re-renders every concept, so repeating it after a reviewer
judged an animation good throws that judgment away and spends model calls and
renders again. The deck from ADR 0008 held every accepted or `needs_human`
concept, which is not the same as reviewed. A reviewer needs to mark a concept
as done, and that mark must stop holding the moment what they reviewed changes.

## Decision

- `manim-engineer approve RUN CONCEPT` writes an `ApprovalPin` to
  `review/approvals.json`: SHA-256 of the plan JSON in canonical form (sorted
  keys, no whitespace), SHA-256 of the accepted scene file, a combined pin, the
  code path relative to the run, a UTC timestamp, author and note. Writes are
  atomic.
- Approval needs an `accepted` or `needs_human` concept whose plan on disk
  equals the plan its animation was rendered from.
- A pin holds while both hashes and the code path match. Otherwise it is broken
  with one stated reason: plan changed, missing or unparseable; accepted
  animation replaced; accepted code changed or missing.
- `run` keeps a concept whose pin holds: its plan file and `run.json` entry
  carry over, nothing is generated or rendered, and the log says it was
  skipped. This holds even when the new planning pass returns no plan for it.
- `run` moves a broken pin to `revoked` with its reason, logs it, and
  re-renders the concept from the plan on disk.
- `unapprove` revokes by hand. `revise` and `render-plan` stay allowed and
  break the pin through the files they change. `live` refuses a run directory
  that has approvals.
- The run deck holds only concepts whose pin holds, in run order, without a
  "needs review" badge. This supersedes ADR 0008's deck-scope bullet. The
  gallery shows approved, stale and revoked states.

## Consequences

- **Benefit:** approved work survives a repeated run unchanged on disk, and an
  edited plan or scene cannot reach a deck without being reviewed again.
- **Tradeoff:** planning still runs for approved concepts because concept ids
  come from the planner: one plan call each per re-run, and a near-duplicate
  under a new id is rendered again.
- **Tradeoff:** a fresh run, including every corpus run, has no deck until a
  concept is approved.
- **Tradeoff:** reformatting plan JSON keeps a pin; any byte change to the
  scene file breaks it.
