# ADR 0003: The typed AnimationPlan is the central artifact

## Status

Accepted (2026-09-14)

## Context

Prior art passes prose plans (or nothing) into code generation. Budgets, layout regions, equation provenance, and beat coverage can only be enforced before rendering when they are structured fields. Humans also need something short to review and edit.

## Decision

`core.AnimationPlan` (pydantic) carries concept, provenance spans and quotes, claim/evidence/takeaway, audience, archetype, budgets, layout regions, symbol ledger, beats (appears/transforms/disappears/emphasis/narration/duration), assets, style, and review criteria. Plans are written as JSON in `outputs/<run>/plans/` with a Markdown mirror. Beat ids are the Manim section names in generated code. Generation consumes only validated plans; revision edits the plan, not the code.

## Consequences

- **Benefit:** deterministic validation before generation, incremental re-render per plan, reviewable diffs.
- **Tradeoff:** schema evolution needs migration care; `schema_version` is mandatory.
- **Follow-up:** keep `plans/*.md` generated, never hand-edited.
