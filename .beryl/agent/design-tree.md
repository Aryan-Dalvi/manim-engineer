# Design Tree

## Current Design Concept

A typed `AnimationPlan` is the spine of the system. Ingestion adapters
normalize every input modality into `Segment`s with provenance; planning
promotes mature concept buckets into plans; generation turns a plan into Manim
code that imports a deterministic layout kit; verification gates the code with
deterministic checks first and vision critique second; output publishes a
slide-ready bundle; the pipeline records everything in a run directory with a
gallery, and revisions flow back through the plan.

## Open Decisions

| Decision | Options | Current Lean | Why |
| --- | --- | --- | --- |
| Embedding model for bucketing | local MiniLM-class model, LLM-embedded, lexical TF-IDF | TF-IDF cosine first, embeddings later | No embedding dependency yet; TF-IDF is deterministic and adequate for boundary signal on one talk |
| Overlap severity promotion | overlap always fatal, text-on-text fatal only, warn first | text-on-text fatal, other overlaps warn | Calibrate false positives on the corpus before promoting |
| Fully deterministic archetype templates vs LLM code using kit builders | JSON-only templates for box diagrams, LLM code with kit | LLM code with mandatory kit builders | Keeps one generation path while still removing absolute-coordinate placement; the h1 transformer diagram shows the model still hand-places boxes sometimes |
| Effort per tier | low everywhere, medium for codegen, high for planning | low everywhere | Plans and code were judged good at low effort in the first runs; medium costs 3-4x latency |
| Deck visual identity extraction | in scope, follow-up | follow-up | Provenance to slides is enough for the first build |

## Settled Decisions

| Decision | Choice | Date | ADR |
| --- | --- | --- | --- |
| Render backend and version | ManimCE 0.19.x on Python 3.11 | 2026-09-14 | 0002 |
| Central artifact | Typed `AnimationPlan` JSON with provenance, beats, budgets, layout, review criteria | 2026-09-14 | 0003 |
| Verification order | Deterministic Tier 0/1 block; Tier 2 VLM advises and ranks; Tier 3 human | 2026-09-14 | 0004 |
| LLM access | `LLMBackend` adapter; Claude CLI default, Anthropic SDK when keyed, Fake for tests | 2026-09-14 | 0005 |
| GIF production | ffmpeg palettegen/paletteuse from MP4, `dither=none`; never Manim `--format gif` | 2026-09-14 | 0006 |
| Prior-art reuse | Reimplement manim-generator's loop; vendor curated 3brown1blue rules | 2026-09-14 | n/a (docs/PLAN.md D3, D4) |
| Section naming | Manim section name equals plan beat id | 2026-09-14 | 0003 |
| Source fidelity severity | Blocks when the plan carries verbatim source equations; advisory otherwise | 2026-09-17 | 0007 |
| Paper equations | Read from LaTeX source into an equation ledger; never re-typed by a model | 2026-09-17 | 0007 |
| Presenter deck | Reveal.js 6.0.2 vendored, one slide per beat clip, narration as notes; no manim-slides | 2026-09-17 | 0008 |
| Deck scope | Concepts whose approval pin holds; no "needs review" badge | 2026-09-17 | 0009 |
| Approval pins | SHA-256 of canonical plan JSON and accepted scene code in `review/approvals.json`; `run` keeps held pins and revokes broken ones with a reason | 2026-09-17 | 0009 |
| Tier 0 LaTeX precompile | Compiles exactly what Manim compiles: its `TexTemplate`, per-class environment, joined string and parts, its own string clean-up and compile command | 2026-10-03 | 0010 |
| Source preamble | Allowlisted packages and the macro definitions a scene uses, in a generated `use_source_preamble(...)` header that the kit applies at import and Tier 0 reads | 2026-10-03 | 0010 |
| TeX package allowlist | `amsfonts`, `bm`, `dsfont`, `mathrsfs`, `mathtools`, `physics`, `xcolor`, `xspace`; a package joins only with a passing compile test | 2026-10-03 | 0010 |

## Pressure Points

- Claude CLI latency: extended thinking is on by default and MCP tool definitions inflate context. The backend passes `--effort low` per tier and `--strict-mcp-config` with no servers; measured codegen dropped from a 900 s timeout to 39 s on Opus. Raise effort per tier only when quality demands it.
- Overlap false positives: hollow shapes (curves, axes, rectangles, arrows) have large empty bounding boxes, so text is only checked against text and solid marks (tips, dots). Invisible mobjects (ValueTracker) are skipped. Calibrated on the e1–h1 runs.
- Text-size threshold is defined at 1080p delivery (24 px) and scaled to the probe resolution; short axis tick labels are warnings, never fatal.
- Labelled grids (memory layouts, banks, tiles, permutations) were not expressible without hand-placed squares; the kit gained `cell_grid` (≤ 8×32 labelled cells, `permute`, `highlight`) and the plan schema a `memory_layout` archetype for the swizzling corpus (2026-09-14). Labels stay ≥ 29 px at 1080p up to 32 columns.
- Architecture diagrams with many hand-placed boxes shrink labels below the floor; the generator is told to use `flow_diagram`, and the fallback template catches the rest. Follow-up: a kit rule that splits wide diagrams into two rows.
- LaTeX cache races between parallel workers: the probe uses a per-process media directory.
- Adjacent buckets that triage to the same concept name are merged before planning (e1 produced duplicates before this).
- The critic must not see the faded-out last frame of a section; frames are the most informative of three candidates per beat.
- YouTube access is fragile; audio fallback exists.
- Decks are built from section clips rather than manim-slides (generated scenes subclass `Scene`, not `Slide`): python-pptx for PPTX and vendored Reveal.js for HTML. Upgrading Reveal.js means replacing all vendored files together.
- The fidelity gate's resemblance threshold (0.82) separates "altered source equation" (fatal) from "not in the source" (warn). It is uncalibrated: no corpus run has exercised it yet, and a paper whose prose restates a formula in a slightly different form is the likely first false positive.
- The TeX package allowlist is a judgment call. Too narrow, and a paper's equations still fail, now with a clear Tier 0 finding. Too wide, and a package could break dvisvgm output. `bbm`, `cancel`, `siunitx`, `braket` and others are left out until they are installed and pass the compile test.
- A paper definition that fails in TeX is terminal for any source equation that uses it: the fidelity gate requires the equation verbatim, and the header cannot be repaired by the model.
- `eqnarray` equations are typeset in `align*`, so `&=&` gets a column gap the paper does not have.
- Verbatim source equations still reach `MathTex` without the source preamble's deny-list; a hostile paper could put `\input` in an equation.
- Tier 0 reuses Manim's private `SingleStringMathTex._get_modified_expression` so it cleans strings exactly as Manim does. ManimCE is pinned to 0.19, and the parity test fails if an upgrade changes it.
- Approved concepts are still re-planned on every `run` because concept ids come from the planner: one plan call each per re-run, and a near-duplicate under a new id is rendered again. Follow-up: pass approved concept names into triage so planning can skip them.
- `revise_run` bumps and saves the plan even when the revision fails, so `approve` refuses the animation it kept until that concept is re-rendered.

## Recording Rule (Design Tree vs ADR)

Add or update this file when:

- A decision is still evolving.
- You are comparing options before implementation.
- The choice may still change after one or two implementation iterations.

Create an ADR when:

- The decision changes module boundaries, persistence shape, adapter contracts, security model, naming conventions used across contexts, or test strategy.
- Future contributors are likely to revisit the choice without clear repo history.
