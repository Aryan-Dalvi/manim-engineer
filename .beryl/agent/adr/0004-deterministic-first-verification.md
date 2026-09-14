# ADR 0004: Deterministic gates block, vision critique advises

## Status

Accepted (2026-09-14)

## Context

Research (SGA, TheoremExplainAgent, ManimAgent) shows VLM judges are near-noise on layout and that symbolic geometric checks give larger quality gains at a fraction of the cost. A no-render probe of the mobject tree at animation boundaries takes about 0.3 s versus 19 s for a full render.

## Decision

Verification runs in tiers. Tier 0 (static: parse, sandbox lint, structure, API existence against the installed Manim, LaTeX precompile, duration bound) and Tier 1 (sandboxed no-render probe: overlap with semantic filter, out-of-frame, text pixel height, plan coverage/order/duration) produce blocking findings. Tier 2 (low-res render, per-beat frames, contact sheet, VLM rubric grounded in the Tier 1 box list) produces advisory scores used for ranking and for a bounded visual repair pass. Tier 3 is human review. Every finding carries gate, severity, location, observed value, and an admissible fix.

## Consequences

- **Benefit:** most defects are caught in under a second with actionable feedback; no render is spent on code that will fail geometry.
- **Tradeoff:** 3D and updater-driven scenes bypass Tier 1 geometry and go straight to Tier 2.
- **Follow-up:** calibrate overlap thresholds on the corpus before promoting non-text overlaps from warn to fatal.
