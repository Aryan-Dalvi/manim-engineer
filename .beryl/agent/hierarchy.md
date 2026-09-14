# Initial Build Hierarchy

## Build Contract
- Scope: end-to-end manim-engineer library and CLI: ingest (transcript, markdown, PDF, PPTX, audio, YouTube) → bucket/triage → typed AnimationPlan → Manim code via kit → tiered verification with repair → GIF/MP4/PNG bundles → gallery; live replay; review/revise; nine-case corpus with outputs.
- Non-goals: TTS/narration audio, web server, model training, deck visual-identity extraction, 3D by default.
- Ratified on: 2026-09-14 (user pre-ratified via build prompt granting autonomy; see docs/PLAN.md)
- Last updated: 2026-09-14 (N0–N10 complete; N11 promotion in progress)
- Completion rule: every node and required check passes, durable context is promoted

## Nodes

### N0 — scaffold
- Parent: root
- Dependencies: none
- Deliverable: `pyproject.toml` (Python 3.11, manim 0.19.x, deps, extras), ruff config, pytest config, `.venv` synced, package skeleton with one `__init__.py` per context, Beryl `affected-tests.conf` wired to pytest, `.gitignore` for outputs/media.
- Acceptance checks:
  - `.venv/bin/python -c "import manim_engineer, manim; print(manim.__version__)"` prints 0.19.x
  - `.venv/bin/pytest -q` passes (smoke test)
  - `./.beryl/scripts/check.sh` passes
- Status: complete
- Canonical context targets:
  - `.beryl/agent/testing-policy.md`
- Evidence: `.venv/bin/python -c 'import manim' → 0.19.2`; `.venv/bin/pytest -q` passes

### N1 — core models
- Parent: root
- Dependencies: N0
- Deliverable: `core` pydantic models: SourceSpan, Segment, Document, AnimationPlan (+Beat, Budgets, Layout, SymbolEntry, ReviewCriterion), Finding, Candidate, ArtifactBundle, enums; JSON round trip; plan Markdown mirror.
- Acceptance checks:
  - `tests/test_core_models.py`: round trip, exactly-one-locator validation, beat id uniqueness, budget bounds
- Status: complete
- Canonical context targets:
  - `.beryl/agent/ubiquitous-language.md`
- Evidence: tests/test_core_models.py 9 passed

### N2 — llm adapter
- Parent: root
- Dependencies: N1
- Deliverable: `llm` protocol, `ClaudeCliBackend`, `AnthropicBackend`, `FakeBackend`, structured output via JSON schema, image inputs, call log, backend selection helper.
- Acceptance checks:
  - `tests/test_llm.py`: fake backend scripted replies; CLI backend argv construction and JSON parsing against a recorded fixture; error mapping
  - `pytest -m live_llm tests/test_llm_live.py` (opt-in) returns structured output through the real CLI
- Status: complete
- Canonical context targets:
  - `.beryl/agent/adr/0005-llm-backend-adapter.md`
- Evidence: tests/test_llm.py 6 passed (live test opt-in)

### N3 — kit
- Parent: root
- Dependencies: N0
- Deliverable: `kit`: style contract (palette, sizes, timing constants), safe text helpers, `flow_diagram`, `timeline`, `comparison_table`, `tensor_grid`, `labeled_box`, `caption`, `fade_all`, `dim`; every builder places within safe bounds by construction.
- Acceptance checks:
  - `tests/test_kit.py`: builders produce mobjects inside the safe frame; text helpers cap width; rendered `-ql` smoke of a kit demo scene (integration)
- Status: complete
- Canonical context targets:
  - `.beryl/agent/architecture.md`
- Evidence: tests/test_kit.py 11 passed

### N4 — verification
- Parent: root
- Dependencies: N1, N3
- Deliverable: Tier 0 static checks, Tier 1 probe + layout checks + sandbox runner, plan alignment checks (coverage/order/duration), Tier 2 frame extraction + contact sheet + critique request shaping; findings with fixes; condensed tracebacks.
- Acceptance checks:
  - `tests/test_static_checks.py`: hallucinated API, legacy API, forbidden import, bad LaTeX, duration bound
  - `tests/test_probe.py`: good scene yields zero findings; bad scene yields overlap, out_of_frame, text_too_small; timeout category
  - `tests/test_alignment.py`: missing beat, wrong order, duration mismatch
- Status: complete
- Canonical context targets:
  - `.beryl/agent/adr/0004-deterministic-first-verification.md`
- Evidence: tests/test_verification.py 8 passed (probe 0.3 s, sandbox child ok)

### N5 — output
- Parent: root
- Dependencies: N1, N3
- Deliverable: `output`: render at quality with sections, ffmpeg GIF/PNG/thumbnail/pptx-safe derivatives, manifest, optional manim-slides export.
- Acceptance checks:
  - `tests/test_output.py` (integration): publish a kit demo scene; manifest lists existing files; GIF frame count matches; section names equal beat ids
- Status: complete
- Canonical context targets:
  - `.beryl/agent/adr/0006-output-contract-and-gif-recipe.md`
- Evidence: tests/test_output.py integration passed: manifest, 3 section gifs, deck.pptx

### N6 — ingest
- Parent: root
- Dependencies: N1
- Deliverable: `ingest.ingest(path_or_url)` with adapters: transcript JSON/VTT/SRT/plain, markdown, PDF (slides and manuscripts), PPTX with notes, audio via faster-whisper, YouTube via captions with audio fallback; assets (page rasters) saved.
- Acceptance checks:
  - `tests/test_ingest.py`: fixtures for each text modality produce Segments with correct spans and kinds; PDF page index equals slide index; PPTX notes captured; audio and YouTube adapters tested through injected fakes
- Status: complete
- Canonical context targets:
  - `.beryl/agent/project-brief.md`
- Evidence: tests/test_ingest.py 8 passed (markdown, json/vtt/plain transcripts, pptx notes, pdf deck+paper, audio and youtube via injected fakes)

### N7 — planning
- Parent: root
- Dependencies: N1, N2, N6
- Deliverable: `planning`: segment windowing, TF-IDF cohesion bucketer, maturity predicate, triage classifier prompt (fast model), planner prompt (strong model) producing validated AnimationPlan, plan validator (budgets, equations from provenance, beat ids), live replay state with watermark.
- Acceptance checks:
  - `tests/test_bucketer.py`: boundary detection on synthetic two-topic transcript; staleness forces emission; dedup suppresses repeats
  - `tests/test_planner.py`: FakeBackend plan is validated; invalid plan is rejected with reasons; replay processes each segment once
- Status: complete
- Canonical context targets:
  - `.beryl/agent/adr/0003-animation-plan-is-the-central-artifact.md`
- Evidence: tests/test_planning.py 6 passed (two-topic split, heading/slide boundaries, staleness+dedup, planner normalization, live replay watermark)

### N8 — generation
- Parent: root
- Dependencies: N1, N2, N3
- Deliverable: `generation`: vendored knowledge pack (curated 3brown1blue rules with attribution), system prompt assembly per archetype, codegen prompt from plan, repair prompt from findings, archetype router, code extraction and normalization (kit import, section names).
- Acceptance checks:
  - `tests/test_generation.py`: prompt contains archetype rules and symbol ledger; generated code is normalized to import kit and name sections by beat id; repair prompt embeds findings with fixes
- Status: complete
- Canonical context targets:
  - `.beryl/agent/design-tree.md`
- Evidence: tests/test_generation.py 5 passed (archetype knowledge, prompts carry ledger+fixes, normalize, fake codegen/repair, fallback passes tiers)

### N9 — pipeline
- Parent: root
- Dependencies: N4, N5, N7, N8
- Deliverable: `pipeline`: orchestrator (ingest → plan → generate → verify/repair → publish), run directory, repair policy, gallery HTML, review notes, revise flow, live replay loop, CLI (`run`, `live`, `plan`, `render-plan`, `revise`, `gallery`, `run-cases`).
- Acceptance checks:
  - `tests/test_pipeline.py`: end-to-end with FakeBackend on a markdown fixture produces plan, candidate, findings, bundle, gallery; repair policy aborts on repeated category; revise regenerates one concept
  - `manim-engineer --help` lists commands
- Status: complete
- Canonical context targets:
  - `.beryl/agent/project-brief.md`
- Evidence: tests/test_pipeline.py 4 passed (end-to-end fake run + revise, repair loop fixes hallucinated API, live replay, CLI help)

### N10 — corpus and runs
- Parent: root
- Dependencies: N9
- Deliverable: `cases/` with nine inputs (easy/hard/challenging), `scripts/fetch_corpus.py`, `outputs/` populated by real runs with the Claude CLI backend, `outputs/index.html` gallery of galleries, `outputs/README.md` explaining how to review and revise.
- Acceptance checks:
  - every case has a run directory with `run.json` and gallery; at least one accepted animation per easy case; findings recorded for rejected ones
- Status: complete
- Canonical context targets:
  - `docs/PLAN.md`
- Evidence: outputs/<case>/run.json for all nine cases; 24/24 concepts accepted after calibration (h1 transformer re-rendered), galleries at outputs/index.html and the published review artifact

### N11 — promotion
- Parent: root
- Dependencies: N10
- Deliverable: canonical docs updated with settled decisions and pressure points; README; hierarchy deleted after all checks pass.
- Acceptance checks:
  - `./.beryl/scripts/check.sh` passes; `.venv/bin/pytest -q` passes; `git ls-files .beryl/agent/hierarchy.md` empty after deletion
- Status: in-progress (promotion done; deletion waits for the first authorized commit)
- Canonical context targets:
  - `.beryl/agent/design-tree.md`
  - `.beryl/agent/architecture.md`
- Evidence: design-tree pressure points and open decisions updated; README and outputs/README written; `./.beryl/scripts/check.sh` OK with 60 tests; hierarchy kept because no commit was authorized by the user
