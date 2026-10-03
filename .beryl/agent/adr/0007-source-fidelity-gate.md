# ADR 0007: Source fidelity blocks only when the source has an equation ledger

## Status

Accepted (2026-09-17)

## Context

ADR 0004 makes deterministic gates block and the vision critic advise. Equation
fidelity was the exception: `check_equation_provenance` emitted `INFO` in every
case, so nothing stopped a scene from showing a formula the source never
contained, and it compared the plan against the code in one direction only.

The reason it could not simply be promoted is that not every input has
equations to be faithful to. A transcript, an audio file or a slide deck yields
no equation markup, so the plan's equations are whatever the model wrote. Making
those fatal would reject correct animations for inputs that never had a source
formula in the first place.

The arXiv adapter changed that asymmetry: a LaTeX source yields a real equation
ledger, and `Equation.verbatim` now records which equations came from it.

## Decision

`verification.alignment.check_equation_provenance` selects its severity from
provenance rather than applying one rule everywhere:

- A `verbatim` equation missing from the code is **fatal**.
- A `Tex`/`MathTex` literal that resembles a `verbatim` equation
  (`SequenceMatcher` ratio >= 0.82) without matching it is **fatal**: an altered
  source formula is the failure this gate exists to catch.
- A literal with no counterpart in provenance is a **warning**, because an
  intermediate derivation step is legitimate and must not be rejected.
- A plan with no `verbatim` equation keeps `INFO` and skips the unsourced sweep,
  so transcript, audio and slide runs behave exactly as before.

The reverse direction reuses `verification.static.collect_tex_literals` instead
of a second LaTeX extractor.

## Consequences

- **Benefit:** the "no assertion beyond the source" review criterion becomes a
  machine check for paper input instead of a human one, and it fails before any
  render time is spent.
- **Tradeoff:** the 0.82 resemblance threshold is a calibration constant. Too
  low and honest rewrites are called alterations; too high and a corrupted
  formula reads as merely unsourced. It is recorded as a pressure point and
  should be re-checked against the corpus before the threshold is trusted.
- **Tradeoff:** generated code that splits one equation across `MathTex` parts is
  matched by prefix, so a split equation is accepted on partial evidence.
- **Follow-up:** the paper macros now carried in `Provenance.macros` are not yet
  injected into the render's `TexTemplate`, so a source equation that depends on
  a paper-defined macro can still fail to compile.
