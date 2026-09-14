# ADR 0002: ManimCE 0.19.x on Python 3.11 as the single render backend

## Status

Accepted (2026-09-14)

## Context

The product needs one animation backend covering equation-heavy and diagram-heavy content. manim-slides 5.6.0 resolves only ManimCE 0.19.x; the Tier 1 layout probe injects a no-op renderer through a `Scene(renderer=...)` kwarg that ManimCE 0.21 removed in its Manager refactor; the Tier 0 API-existence check introspects the installed module and is version-exact by design. ManimCE 0.19.2 requires Python 3.11.

## Decision

Pin `manim>=0.19.1,<0.20` and Python 3.11 in `pyproject.toml`. State the pinned version in every code-generation prompt. Treat manim-slides as an optional output step so the core path does not depend on it.

## Consequences

- **Benefit:** probe, API check, prompts, and slides bridge all agree on one API surface.
- **Tradeoff:** newer Manim features are unavailable until the probe and the slides bridge are re-validated.
- **Follow-up:** when bumping, re-run `tests/test_probe.py` and the slides smoke test first.
