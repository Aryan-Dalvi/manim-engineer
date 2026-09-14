# manim-engineer: end-to-end plan

Status: ratified in advance by Ben's build prompt ("you are given autonomy to
decide what's best based on the EXTENSIVE research you have done in planning
phase"). Written 2026-09-14 after six parallel research scouts; their full
reports live in `docs/research/`. Every decision below cites the report that
motivated it.

## 0. The one-paragraph version

Presenters, lecturers and paper authors need short, correct, on-brand
animations of the *hard parts* of what they are saying, and they need them
without hand-writing Manim. Existing LLM-to-Manim tools take a single prompt
or theorem, generate code in one shot or with a text-only repair loop, verify
nothing about layout, and emit a standalone MP4. Nobody ingests a talk,
decides which moments deserve an animation, conditions on the presenter's own
material, gates output deterministically before spending render time, or hands
back slide-ready GIFs. manim-engineer is a Python library plus CLI that does
exactly that pipeline: **ingest → triage → plan → generate → verify → publish**,
with a typed, editable animation plan in the middle, a deterministic-first
quality gate, a pluggable LLM backend (the user's Claude Code login works with
zero configuration), and a browsable output gallery for human review and
targeted revision.

## 1. The three core ideas

### 1.1 What people need that this project fills

- **Talk-shaped input.** A 45-minute talk contains a handful of moments that
  benefit from animation and dozens that do not. The user needs the system to
  find those moments from whatever they have: a live or recorded transcript,
  a slide deck, a YouTube link, raw audio, or a manuscript.
- **Two visual registers under one backend.** Ben's framing: math and stats
  content wants equations and plots; ML systems content wants "box-like"
  architecture and rollout diagrams. Both must come out of Manim, because one
  render backend means one style contract, one verification stack and one
  output contract.
- **Trust before use.** A presenter will not drop an animation into a talk if
  it might overlap its own labels, run off-screen, or assert something they
  never said. Quality has to be checked, and the check has to be explainable.
- **Presenter-friendly delivery.** The deliverable is a GIF or a steppable
  clip for a specific slide, not a ten-minute YouTube video.
- **Cheap, targeted revision.** "Make the arrow blue and slow the last beat
  down" must not mean regenerating the whole thing from scratch.

### 1.2 What exists and where it falls short

The landscape report (`docs/research/landscape.md`) surveyed thirteen tools,
nine papers and five datasets. The consistent findings:

| Shortcoming | Evidence |
| --- | --- |
| Single prompt or theorem in, whole video out; no talk ingestion, no salience triage | Every surveyed tool. Manimator reads a PDF, nothing reads a deck, nothing reads a transcript. |
| Single-shot generation loses to planned generation by about 40 percent | Code2Video: 87.9 vs 37.8 aesthetic score for planned vs direct code generation. |
| Text-only repair loops fix tracebacks, never layouts | TheoremExplainAgent's own error analysis: misaligned and overlapping elements survive to output. |
| "Renders" is not "correct": roughly two in five executing programs are spatially broken | PRISM's execution-to-spatial gap of about 41 points. |
| VLM judges are nearly blind to geometry | SGA: deterministic geometric checks gave 6x the quality gain of a VLM critic at 6-18x lower cost; TheoremExplainAgent's text metrics correlate with humans at rho 0.14-0.16. |
| Hallucinated or wrong-version Manim API is the top crash cause | ManiBench catalogues 145 ManimGL-to-CE breaks; only a quarter of Bespoke-Manim snippets render. |
| No library API with a reviewable plan object | Research scripts, REST services, a closed desktop app, or bare `exec()` MCP servers. |
| Output is a standalone MP4 | Only Animo exports GIF, and only as a file option. Native Manim GIF export is broken (fixed 3:3:2 palette, 2.7x larger). |
| The best repo for our architecture, makefinks/manim-generator, is not wrappable | CWD-bound prompt loader, interactive confirms in the core, headless mode never renders, fixed review cycles with no early exit. |

The two knowledge packs (`docs/research/3brown1blue-skills.md`) are the
opposite: excellent, machine-checkable rules with no pipeline around them.

### 1.3 How this project fixes it

1. **Plan as the product's spine.** A typed `AnimationPlan` (pydantic) sits
   between ingestion and code. It carries provenance spans, the claim to
   convey, an archetype, per-beat appear/transform/disappear verbs, layout
   regions, a symbol ledger, budgets, and success criteria. It is JSON on
   disk, so it can be diffed, edited by hand, and re-rendered.
2. **Salience triage and bucketing.** Segments are embedded, bucketed by
   cohesion, classified cheaply per window, and a bucket is promoted to a
   plan only when a scored maturity predicate fires. The same code runs on a
   replayed recording and on a live stream.
3. **Archetype router with a deterministic kit.** Generated code imports
   `manim_engineer.kit`, which ships a style contract, safe text helpers, and
   deterministic layout builders for the archetypes LLMs place badly
   (box-and-arrow flows, timelines, tables, tensor grids). The LLM decides
   *what*; the kit decides *where*.
4. **Deterministic-first verification ladder.** Tier 0 static checks against
   the installed Manim's real symbol table plus LaTeX precompilation. Tier 1
   runs `construct()` with rendering disabled and checks bounding boxes for
   overlap, off-frame, and unreadable text in about a third of a second.
   Tier 2 renders low-res, extracts per-beat frames, and asks a vision model
   for advisory scores grounded in the Tier 1 box list. Tier 3 is the human.
   Every finding carries a location, the observed value, and an admissible
   fix, because that field is what moves repair success.
5. **Source fidelity gate.** Equations in generated code must come from the
   plan's provenance, and on-screen text is checked against the cited source
   span. Nobody else checks the animation against what the speaker said.
6. **Slide-ready output contract.** One render yields master MP4, per-beat
   MP4 sections, per-beat GIFs via a measured ffmpeg palette recipe, poster
   PNGs, a manifest, and optionally a reveal.js or PPTX deck via
   manim-slides.
7. **Harness, not just a tool.** LLM access is an adapter with three
   implementations: the Claude CLI (works with the user's existing login and
   no API key), the Anthropic SDK, and a scripted fake for deterministic
   tests. Users can plug in their own agent.
8. **Review and revise loop.** Every run writes a browsable gallery. A
   reviewer leaves a note on an animation; `revise` folds the note into the
   plan as a constraint and regenerates only that animation.

## 2. Architecture

### 2.1 Bounded contexts

| Context | Owns | Public entry point |
| --- | --- | --- |
| `core` | Domain models: `Segment`, `SourceSpan`, `Document`, `AnimationPlan`, `Beat`, `Finding`, `Candidate`, `ArtifactBundle` | `manim_engineer.core` |
| `llm` | `LLMBackend` protocol, `ClaudeCliBackend`, `AnthropicBackend`, `FakeBackend`, structured output, vision, call log | `manim_engineer.llm` |
| `ingest` | Adapters from each modality to `Document` | `manim_engineer.ingest.ingest()` |
| `planning` | Bucketing, triage, plan generation, plan validation | `manim_engineer.planning` |
| `generation` | Knowledge pack, prompts, archetype router, code generation, repair prompt shaping | `manim_engineer.generation` |
| `kit` | Runtime library imported by generated scenes: style contract, safe helpers, deterministic layout builders | `manim_engineer.kit` |
| `verification` | Tier 0, Tier 1, Tier 2 gates, finding schema, sandboxed runner | `manim_engineer.verification` |
| `output` | Render, ffmpeg derivatives, manifest, manim-slides bridge | `manim_engineer.output` |
| `pipeline` | Orchestrator, run directory, repair loop policy, gallery, review/revise, live replay, CLI | `manim_engineer.pipeline`, `manim_engineer.cli` |

Boundary rules follow `.beryl/agent/architecture.md`: a context imports only
another context's public entry point; Manim, ffmpeg, LLM providers, ASR, and
document parsers are reached only through adapters in `ingest`, `llm`,
`verification`, and `output`.

### 2.2 Data flow

```
input (path | URL | live source)
  └─ ingest ──► Document{segments[], assets[]}
       └─ planning.bucket ──► Bucket[] ──(mature)──► planning.plan ──► AnimationPlan (JSON)
            └─ generation.generate ──► Candidate{code, scene_class}
                 └─ verification.tier0 ─► tier1 ─► (repair ≤3) ─► tier2 ─► (repair ≤2)
                      └─ output.publish ──► ArtifactBundle{mp4, sections/, gif, png, manifest.json}
                           └─ pipeline.gallery ──► outputs/<run>/index.html
                                └─ human note ──► pipeline.revise ──► (plan constraint) ──► regenerate
```

### 2.3 Run directory layout

```
outputs/<case-or-run-name>/
  run.json                  # inputs, config, timings, backend, model ids
  document.json             # normalized Document
  plans/<concept_id>.json   # AnimationPlan, editable
  plans/<concept_id>.md     # human mirror
  candidates/<concept_id>/attempt_<n>.py + findings_<n>.json
  animations/<concept_id>/  # manifest.json, master.mp4, sections/*.mp4|gif|png, stills/
  review/notes.json         # reviewer feedback, consumed by `revise`
  index.html                # gallery
outputs/index.html          # gallery of galleries
```

## 3. Decisions and why

| # | Decision | Why | Source |
| --- | --- | --- | --- |
| D1 | Pin ManimCE 0.19.x on Python 3.11 | manim-slides 5.6.0 resolves only 0.19.x; the Tier 1 probe injects a renderer via a constructor kwarg that 0.21 removed; the API-existence check is version-exact by design | output-layer, quality-verification |
| D2 | Typed plan artifact rather than prose plan | Budgets, layout regions and equation provenance are enforceable only as structured fields; prose plans cannot be validated before a render is wasted | ingestion-planning §3 |
| D3 | Reimplement the manim-generator architecture rather than wrap or fork | Its prompt loader is CWD-bound, headless mode never renders, no early exit, no GIF; the reusable parts are about 400 lines which we borrow with attribution | manim-generator §6 |
| D4 | Vendor a curated subset of the 3brown1blue rules as the knowledge pack | MIT; spatial rules, timing table, gotchas and style contract are exactly what converts plausible Manim into non-overlapping Manim; API cheat sheets are redundant with frontier models | 3brown1blue-skills §5 |
| D5 | Deterministic gates block, VLM advises | SGA and TheoremExplainAgent show VLM layout judgement is near noise; geometry is checkable in 0.3 s without rendering | quality-verification §0, §4.4 |
| D6 | Every finding carries an admissible fix | The structured-feedback ablation attributes almost all of a 40-point repair gain to that field | quality-verification §7.1 |
| D7 | Repair budgets: 3 attempts on deterministic findings, 2 on visual, abort on repeated error category, then degrade to a template | Published budgets converge on 2-5; diminishing returns past 5 calls per scene | quality-verification §7.3 |
| D8 | Kit library with deterministic layout builders, required import | The execution-to-spatial gap concentrates in box-and-arrow and data-flow archetypes; deterministic `arrange`-based layout removes the failure class | ingestion-planning §4.13 |
| D9 | GIFs from MP4 via ffmpeg palettegen with `dither=none`, never `--format gif` | Native path forces `rgb8`, losing the palette and inflating size 2.7x; dithering hurts flat-colour content on size and quality | output-layer §2.2-2.3 |
| D10 | manim-slides is an optional final step | Insulates the core path (render, sections, GIF, stills) from manim-slides lagging Manim releases | output-layer §5 |
| D11 | Claude CLI as default LLM backend | Verified working headlessly with the user's login, supports JSON-schema structured output and image reading; no key present on this machine | environment probe |
| D12 | faster-whisper for audio, yt-dlp plus transcript API for YouTube, PyMuPDF and python-pptx for slides, PyMuPDF for PDFs | All verified working here; GPU available; YouTube transcript path is fragile so audio fallback is wired in | ingestion-planning §1 |
| D13 | Bucket maturity is a scored predicate, not a threshold | Mass, cohesion, boundary evidence, archetype confidence, concreteness, staleness and dedup each catch a distinct false-positive class | ingestion-planning §2.3 |
| D14 | Section names equal beat ids | Makes plan coverage, order and duration fit deterministic checks, and joins Manim's section index with manim-slides' slide index | quality-verification §6, output-layer §4.3 |
| D15 | Live mode is replay of a growing transcript | Same code path for recorded and live; append-only confirmed text with a watermark keeps per-tick cost constant | ingestion-planning §5 |

## 4. Test-case corpus

Inputs live in `cases/` (small files committed; large media fetched by
`scripts/fetch_corpus.py`). Outputs go to `outputs/<case>/` with a gallery.

| Tier | Case | Modality | What it exercises |
| --- | --- | --- | --- |
| easy | `e1_softmax_markdown` | markdown manuscript | equation derivation + plot archetype, single concept |
| easy | `e2_vectors_transcript` | YouTube transcript JSON (3b1b Vectors, first 90 s) | transcript adapter, geometric/vector archetype |
| easy | `e3_vectors_audio` | MP3 clip of the same 90 s | faster-whisper adapter; output should match e2 |
| hard | `h1_transformer_slides` | PDF lecture deck (CS224N transformers) | slide adapter, slide-index provenance, architecture diagram archetype |
| hard | `h2_attention_talk` | full 26-minute transcript (3b1b Attention) | bucketing and triage on long input, several plans, dedup |
| hard | `h3_specdec_paper` | arXiv PDF (Speculative Speculative Decoding) | manuscript adapter with equations; direct comparison with Shahu's sample video |
| challenging | `c1_live_replay` | 20-minute window of Karpathy "Let's build GPT", replayed as a live stream | live bucketing, latency, priority queue |
| challenging | `c2_multimodal_fusion` | transcript plus paper (3b1b Attention + Attention Is All You Need) | multi-span provenance, symbol ledger from paper equations |
| challenging | `c3_loss_landscape` | markdown with equations and plots | plot with ValueTracker, gradient descent trace, 3D gated off by default |
| hard | `s0_gpu_memory_basics` | researched markdown manuscript (prerequisites for the swizzling article) | memory_layout archetype with `cell_grid`, bank arithmetic, cache lines, coalescing; 7 concepts |
| challenging | `s1_swizzling_article` | web article "Swizzling explained properly" (scallion3008.github.io/swizzling), figures rewritten as prose, companion equation sheet | dense expository prose with proofs and bit diagrams; XOR permutations of labelled grids |
| challenging | `s1b_swizzling_article_part2` | second half of the same article | `base`/ldmatrix, the 32B/64B/128B modes, benchmark bar charts, loads-vs-stores accounting |
| challenging | `s2_swizzling_frontier` | researched manuscript beyond the article (CuTe composed layouts, TMA/WGMMA swizzle, Triton encodings, GF(2) view, AMD LDS) | expert-audience content mixing equations, tables and address-bit diagrams |

## 5. Build hierarchy

Dependency-ordered nodes; the tracked copy with status and evidence is
`.beryl/agent/hierarchy.md`.

1. **N0 scaffold**: pyproject, ruff, pytest, Beryl test config, package skeleton.
2. **N1 core models**: domain types with JSON round-trip tests.
3. **N2 llm adapter**: protocol, Claude CLI, Anthropic SDK, fake; structured output; vision; call log.
4. **N3 kit**: style contract, safe helpers, deterministic layout builders, rendered smoke test.
5. **N4 verification**: Tier 0, Tier 1, sandbox runner, findings with fixes, Tier 2 frame extraction and critique.
6. **N5 output**: render, ffmpeg derivatives, manifest, optional manim-slides.
7. **N6 ingest**: transcript, markdown, PDF, PPTX, audio, YouTube adapters.
8. **N7 planning**: bucketer, triage classifier, planner, validator, live replay.
9. **N8 generation**: knowledge pack, prompts, archetype router, codegen, repair shaping.
10. **N9 pipeline**: orchestrator, run dir, repair policy, gallery, review/revise, CLI.
11. **N10 corpus and runs**: cases, fetch script, run all nine cases, gallery of galleries.
12. **N11 promotion**: canonical docs, ADRs, hierarchy deletion.

## 6. Non-goals for this build

- Narration/TTS muxing. Beat narration is planned and stored; audio is not rendered.
- 3D scenes by default. Allowed by a plan budget flag; verification degrades to Tier 2 only.
- Training or fine-tuning models.
- A web server. The gallery is static HTML; live mode is a CLI loop over a file or stdin.
- Deck-style extraction (palette and fonts from a PPTX). Provenance to slides is in scope; visual identity extraction is a follow-up.

## 7. Risks

- **LLM latency through the CLI.** Each call spawns a process; planning plus
  codegen plus two repairs is several minutes per concept. Mitigated by
  cheap-model classification, deterministic gates before any render, and
  per-concept parallelism.
- **Overlap false positives.** The semantic filter cut 26 findings to 0 on a
  good scene in research; the gate ships with a calibration test set and
  overlap starts as warn-then-fatal per severity.
- **YouTube access.** Works from this machine today; fallback to audio is wired.
- **manim-slides drift.** Optional step, so drift degrades gracefully.
