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

## Pressure Points

- Claude CLI latency: extended thinking is on by default and MCP tool definitions inflate context. The backend passes `--effort low` per tier and `--strict-mcp-config` with no servers; measured codegen dropped from a 900 s timeout to 39 s on Opus. Raise effort per tier only when quality demands it.
- Overlap false positives: hollow shapes (curves, axes, rectangles, arrows) have large empty bounding boxes, so text is only checked against text and solid marks (tips, dots). Invisible mobjects (ValueTracker) are skipped. Calibrated on the e1–h1 runs.
- Text-size threshold is defined at 1080p delivery (24 px) and scaled to the probe resolution; short axis tick labels are warnings, never fatal.
- Labelled grids (memory layouts, banks, tiles, permutations) were not expressible without hand-placed squares; the kit gained `cell_grid` (≤ 8×32 labelled cells, `permute`, `highlight`) and the plan schema a `memory_layout` archetype for the swizzling corpus (2026-09-14). Labels stay ≥ 29 px at 1080p up to 32 columns.
- Architecture diagrams with many hand-placed boxes shrink labels below the floor; the generator is told to use `flow_diagram`, and the fallback template catches the rest. Follow-up: a kit rule that splits wide diagrams into two rows.
- LaTeX cache races between parallel workers: the probe uses a per-process media directory.
- Adjacent buckets that triage to the same concept name are merged before planning (e1 produced duplicates before this).
- The critic must not see the faded-out last frame of a section; frames are the most informative of three candidates per beat.
- YouTube access is fragile; audio fallback exists. manim-slides lags Manim releases; the deck is built with python-pptx instead.

## Recording Rule (Design Tree vs ADR)

Add or update this file when:

- A decision is still evolving.
- You are comparing options before implementation.
- The choice may still change after one or two implementation iterations.

Create an ADR when:

- The decision changes module boundaries, persistence shape, adapter contracts, security model, naming conventions used across contexts, or test strategy.
- Future contributors are likely to revisit the choice without clear repo history.
