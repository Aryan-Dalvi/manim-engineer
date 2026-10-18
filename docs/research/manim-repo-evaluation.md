# Manim Generator — Repository Evaluation

> **Context:** written before this project existed in its current form. The project later adopted an existing pipeline instead of building on manim-generator, and pins ManimCE 0.19 on Python 3.11 (see [ADR 0002](../../.beryl/agent/adr/0002-manimce-0-19-render-backend.md)). The findings on paper ingestion and source fidelity shaped the arXiv adapter and equation-fidelity gate (ADR 0007).

*2026-09-15 · Scope: read a research paper → split it into concept buckets (one concept each) → generate Manim for each concept. Script-timeline alignment and slides are out of scope here.*

**Method.** All five repositories were shallow-cloned at the commits listed under Sources. I read the code for generation, validation, rendering, review and human review. Activity, contributor and star counts come from the GitHub REST API (2026-09-15). Two of 3brown1blue's Manim API claims were checked against current Manim Community source.

**Not done.** No generator was run end-to-end and no test suite was executed. This machine has Python 3.9.6 and no Manim, LaTeX or LLM API keys. Render success rates and output quality are therefore **unmeasured**; see Open questions.

---

## TL;DR

- **Nothing covers your core step.** None of the five repos reads a paper, splits it into concepts, or checks output against the paper. That part is yours to build.
- **Build the loop on makefinks/manim-generator.** Its generate → render → vision-review loop is the skeleton.
- **Port selected modules from HarleyCoops/Math-To-Manim:** concept-map schema, LaTeX-aware static checks, repair policy, structured visual verdict, stage caching.
- **Use AmitSubhash/3brown1blue for knowledge and review UX:** its rulebook, planning format and human-review patterns.
- **Use marcelo-earth/generative-manim only for evaluation tooling.**
- **Take no code from 3b1b/manim.** Every generator here targets Manim Community Edition, a separate and incompatible dialect.

---

## Background

| Repo | What it actually is | Manim dialect | License | Commits Jun 15–Sep 15 2026 | Contributors | Stars | Tests |
|---|---|---|---|---|---|---|---|
| 3b1b/manim | The ManimGL animation **engine**, not a generator | ManimGL (`manimlib`) | MIT | 109 | 100+ | 93.9k | — |
| HarleyCoops/Math-To-Manim | Multi-stage LLM chain: question → prerequisite tree → curriculum → math → shot list → scene spec → code → render/repair. **Four parallel pipelines**, one per vendor: Mythos (Claude CLI), Sol (Codex CLI), Grok, GLM | Manim CE | MIT | 97 | 13 | 2.6k | 179 test functions |
| AmitSubhash/3brown1blue | A Claude Code / Cursor **skill** (24 rule files, templates, safe wrappers) plus a CLI: plan → human approve → generate, edit, audit, voiceover | Manim CE | MIT | 2 | 1 | 34 | none |
| makefinks/manim-generator | CLI loop: writer LLM → render each scene → reviewer LLM with rendered frames → revise ×N. Harness behind the Manim Bench leaderboard | Manim CE (prompts pin 0.19.0) | MIT | 1 | 1 | 117 | 57 tests, CI on Py 3.10–3.12 |
| marcelo-earth/generative-manim | Flask API + LLM providers for prompt → a single `GenScene` → MP4, plus an SFT/DPO/GRPO fine-tuning pipeline and a small benchmark | Manim CE (0.21.0) | Apache-2.0 | 38 | 7 | 917 | 193 test functions |

Manim Community Edition is at **0.21.0** (released 2026-08-10, **requires Python ≥ 3.11**). Your system Python is 3.9.6, so you'll need a newer interpreter. You'll also need a LaTeX distribution and ffmpeg.

---

## Key findings

1. **No paper ingestion exists anywhere.**
   - 3brown1blue has its agent read papers with the `browser-use` CLI (instructions in `paper-explainer.md`); its only document parser handles PPTX (`from_slides.py`).
   - Math-To-Manim's one paper project is an archived, hand-run bundle, not code.
   - manim-generator and generative-manim accept only free-text prompts.

2. **"One concept per unit" is independently enforced by two repos.** Math-To-Manim's curriculum charter allows one new idea per act. 3brown1blue's paper-explainer gate requires each scene to carry a single key insight. This matches your bucket definition.

3. **Math-To-Manim has the best machine-readable decomposition schema.**
   - Cartographer charter: concept nodes with `why_needed`, `depth`, `assumed` (audience already knows it) and `visual_seed`, plus `edges` and an ordered `spine`.
   - Math-director charter: every formula as ordered `latex_parts` (so each term can be addressed), a per-term `term_glossary`, and a `common_misreading`.
   - `validate_stage_artifact` rejects degenerate stage output and retries once. It was added after a real failure where the math stage returned an empty 48-byte dossier.

4. **The best accuracy practice is in Math-To-Manim's archived paper bundle, but it is manual.** In `archive/paper_visualizations/prl-130-041601-casimir-sie/`:
   - Equations were taken from the **arXiv LaTeX source**, each recorded with its source label and line numbers.
   - Each equation has a plain-language meaning, a visual mapping and a caveat tag (`research/equation_ledger.md`).
   - Every model approximation is listed (`research/assumptions.md`).
   - Episodes carry learning objectives and acceptance criteria (`storyboards/beat_sheet.md`).

5. **3brown1blue has the best rules written specifically for paper explainers.**
   - Pre-code gates: narration script → curriculum → style contract.
   - A hook / problem / background / method / results / takeaway structure.
   - A test for when to animate versus show a static figure (animate when the order of appearance matters).
   - A dim → highlight → colour equation walkthrough.
   - Six layout templates with coordinate regions, and a fixed per-scene plan format: Template, Content, Visual anchors, Cleanup, Equations, Data.
   - A pacing table, and five worked paper projects under `videos/`.

6. **3brown1blue's runtime is weak.**
   - `generate` writes all scenes in one LLM call capped at 16,384 output tokens.
   - There is no render-error repair loop.
   - `--render` renders only the **last** Scene class (`matches[-1]` in `_render_scene`).
   - Errors exit the process.
   - Every call's system prompt concatenates all rule files, templates and wrappers: about 339 KB, roughly 80–85k tokens per call. `generate` makes two such calls, although its own `SKILL.md` says to load only the rules a task needs.

7. **3brown1blue's rules need verification before you trust them.**
   - **Confirmed correct:** `Brace.get_text(..., font_size=...)` crashes. CE's `get_text` forwards extra keyword arguments through `put_at_tip` to `next_to()`, and `next_to()` has no `font_size` parameter.
   - **But the repo breaks its own rule:** the flagship example in `rules/paper-explainer.md` (line 183) and `rules/decorations.md` (line 190) both make exactly that call.
   - **Not supported by current source:** the claim that `Group.save_state()` crashes. `save_state` is defined on the base `Mobject`, which `Group` inherits.

8. **manim-generator has the cleanest reusable generation loop (≈2,750 lines of source).**
   - `run_manim_multiscene` finds Scene classes via the AST and renders each in its own subprocess with a timeout and tagged stdout/stderr.
   - It computes a per-scene success rate and extracts frames for the reviewer: `highest_density` picks the frame with the most non-black pixels; `fixed_count` takes evenly spaced frames.
   - The reviewer switches from a technical prompt to a visual-polish prompt once the scene success rate crosses a threshold.
   - LiteLLM covers any provider, with rate-limit retries, reasoning-effort control and token/cost tracking.
   - Prompts, reasoning, reviews, code, logs and frames are saved for every step.

9. **manim-generator's weaknesses:**
   - The review loop always runs the full `--review-cycles` count (default 5), with no early stop.
   - Each revision rewrites the whole script, and the saved result is the *last* version that rendered, not the best one.
   - The reviser never sees the frames: `_generate_code_revision` accepts `frames` but does not use them.
   - Human involvement is limited to end-of-run confirmations.
   - Prompts are generic and pinned to CE 0.19.0.

10. **Math-To-Manim has the most mature repair and review policy.**
    - **Static gate before any render:** `py_compile` → `validate_manim_code_report`. That covers AST scene discovery and a LaTeX tokenizer/parser over every `Tex`/`MathTex` fragment, with optional `chktex`, and a `lualatex` compile when `M2M_LATEX_DEEP_CHECK` is set.
    - **Bounded repair:** the prompt asks for a surgical fix that keeps the structure, and a render timeout ends the loop instead of consuming repair attempts.
    - **Structured visual review (Sol):** after rendering, frames and a contact sheet (ffmpeg `fps=1/12, tile=3x2`) go to a reviewer. The reviewer must return JSON with `status: approved | needs_repair`, frame/timestamp-linked `defects`, and `evidence`. Defects are sent back to the stage that owns the scene spec.
    - **Stage caching:** each stage is keyed by a SHA-256 of its inputs and upstream artifact hashes, and `resume(run_id, from_stage)` re-runs only downstream stages.
    - **Caveat:** if you hand-edit a stage's artifact, the cache treats it as stale and regenerates it. Human edits need a "pinned / approved" flag to persist.

11. **Math-To-Manim has serious reliability problems.**
    - **Churn:** 97 commits in three months and three generations in about 20 months (`legacy/` Jan 2025 → `archive/codex-pipeline/` v1.0 → Mythos/Sol v1.1).
    - **Duplication:** the four vendor pipelines duplicate modules; `mythos/scene_checks.py` and `sol/scene_checks.py` differ by only 33 diff lines.
    - **Self-contradictory README:** it documents a GLM pipeline and a `math-to-manim-glm` command (also registered in `pyproject.toml`). A later section says neither exists, yet `glm/` is in the repo.
    - **Vendor lock:** Mythos and Sol call the `claude` / `codex` CLIs rather than APIs.
    - **Style lock:** output is one stylised "film" per run (always `ThreeDScene`, fixed dark palette, a mandated dramatic zoom), with constraints pinned to CE 0.19.
    - **Clone friction:** a full clone needs git-lfs for media.

12. **generative-manim is prompt → one scene, with thin prompts.**
    - The system prompt is about 20 lines, mostly "name the class `GenScene`".
    - Anthropic calls use `max_tokens=1000` in both `/v1/code/generation` and the chat tool loop, which truncates non-trivial scenes.
    - Rendering is a subprocess plus Azure Blob upload.
    - Command-injection and path-traversal fixes landed in July 2026: a reminder that rendering LLM-written code needs isolation.
    - Its genuinely reusable parts are evaluation tools: `training/rendering/manim_verifier.py` (error taxonomy: syntax / import / runtime / class-not-found / timeout; animation counting; parallel batch verification) and `training/benchmarks/` (frozen tasks, required/disallowed regex checks, minimum animation count, pass@k, comparison reports).
    - The shipped task suite has only 11 generic tasks.

13. **3b1b/manim is excellent, but the wrong target.**
    - Its README warns that ManimGL and Manim Community are different projects with incompatible installs.
    - Its best human-in-the-loop feature (`-e/--embed LINE` into IPython with `InteractiveScene` and `checkpoint_paste`) only works on ManimGL code.
    - All four generators emit `from manim import *` (Community), and LLMs have far more Community-style training data.

14. **Human-in-the-loop features that actually exist:**
    - **3brown1blue:**
      - Plan approval with yes / edit in `$EDITOR` / quit (`confirm_plan`).
      - Per-scene natural-language edit → re-render → re-concatenate (`3brown1blue edit 3 "use bigger font" --render --concat`).
      - An audit report with 10 static lint checks and extracted frames for a person to inspect (`audit_video.py`).
    - **Math-To-Manim:** inspectable JSON per stage, resume from any stage, and an MCP server for browsing artifacts.
    - **manim-generator:** a per-cycle artifact trail and end-of-run confirmations.
    - **generative-manim:** nothing in this repo. Its UI is the separate Animo product; `animo/` is only a client SDK for `api.animo.video`.

15. **Nobody checks faithfulness to the source.** Sol's reviewer checks mathematical fidelity against the user's *request*, not a paper. Math-To-Manim's math director is only told to mentally double-check its LaTeX, which is a self-check, not verification.

---

## Recommendation

### Use

**1. makefinks/manim-generator: the code skeleton for generate → render → review**
- **Keep:**
  - [`workflow.py`](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/src/manim_generator/workflow.py): the orchestration (initial code → execute → review → revise) and `working_code` tracking.
  - [`utils/rendering.py`](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/src/manim_generator/utils/rendering.py): `run_manim_multiscene` and `extract_frames_from_video`.
  - [`utils/llm.py`](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/src/manim_generator/utils/llm.py) + [`utils/usage.py`](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/src/manim_generator/utils/usage.py): LiteLLM wrapper, retries, reasoning effort, cost tracking.
  - [`artifacts.py`](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/src/manim_generator/artifacts.py): per-step audit trail for human review.
  - [`utils/parsing.py`](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/src/manim_generator/utils/parsing.py): code-block extraction and AST scene discovery.
  - [`prompts/review_prompt.txt`](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/prompts/review_prompt.txt) / [`review_prompt_enhanced.txt`](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/prompts/review_prompt_enhanced.txt): keep the technical → visual switching mechanism, rewrite the content.
  - [`tests/`](https://github.com/makefinks/manim-generator/tree/f56fffcd81ca97424f943ec83e12961b6c5acbe1/tests) and [CI](https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/.github/workflows/ci.yml) for the modules you keep.
- **Change:**
  - Stop early when the reviewer approves.
  - Give the reviser the frames.
  - Revise one scene at a time rather than the whole file.
  - Pin the prompt to the CE version you actually install.

**2. HarleyCoops/Math-To-Manim: selective ports (one copy of each module)**
- **Concept-map schemas:** [`mythos/agents/mythos-cartographer.md`](https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/mythos/agents/mythos-cartographer.md), [`mythos-curriculum.md`](https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/mythos/agents/mythos-curriculum.md), [`mythos-math-director.md`](https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/mythos/agents/mythos-math-director.md). These give you the prerequisite nodes with `assumed` and `spine`, one-idea-per-unit ordering, and per-term equation breakdowns. Re-point them from "a single question" to "a paper's contributions".
- **Harness policies:** [`mythos/harness.py`](https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/mythos/harness.py): `validate_stage_artifact` (degenerate-output guard + one retry), the `_repair` prompt, and the rule that timeouts don't consume repairs. Optionally, the `--offline` stub pattern for testing pipeline plumbing without model calls.
- **Static gate:** [`mythos/scene_checks.py`](https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/mythos/scene_checks.py), the pre-render AST + LaTeX checks. This is probably the single most valuable reliability file across all five repos.
- **Prerequisite cache:** [`mythos/prereq_cache.py`](https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/mythos/prereq_cache.py) caches prerequisite maps between runs (30-day TTL). Adapt it so concepts from one paper share prerequisite nodes.
- **Stage caching and review verdict:** [`sol/staged.py`](https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/sol/staged.py): `stage_input_hash`, the cached-stage check, `_downstream_names`, and the `review_render` verdict schema. Reimplement without the Codex CLI session plumbing, and add a human-approved pin.
- **Review evidence:** [`sol/rendering.py`](https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/sol/rendering.py): `extract_review_frames` contact sheet, and `apply_resource_limits` (best-effort CPU and memory caps; its own docstring says this is not a full sandbox).
- **Bucket and provenance template:** [`archive/paper_visualizations/prl-130-041601-casimir-sie/`](https://github.com/HarleyCoops/Math-To-Manim/tree/0df6aa9d92b18d76862776a0425fda4d9f5cc023/archive/paper_visualizations/prl-130-041601-casimir-sie). Copy the **artifact design** (equation ledger with source lines, assumptions list, beat sheet with acceptance criteria), not code.

**3. AmitSubhash/3brown1blue: knowledge base, planning format, human-review UX**
- **Rules** (load per stage, never all at once): [`skill/rules/`](https://github.com/AmitSubhash/3brown1blue/tree/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/skill/rules)
  - `paper-explainer.md`
  - `scene-planning.md`
  - `production-quality.md`
  - `explanation-design.md`
  - `pedagogy-checklist.md`
  - `visual-design-principles.md`
  - `visual-design-catalog.md`
  - `troubleshooting.md`
  - [`skill/domains/machine-learning.md`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/skill/domains/machine-learning.md) and any other domain files you need
- **Gotchas and safe wrappers** (after verifying each against your CE version; see finding 7): [`skill/SKILL.md`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/skill/SKILL.md) and [`skill/scripts/safe_manim.py`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/skill/scripts/safe_manim.py).
- **Style and layout:** [`skill/templates/style.py`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/skill/templates/style.py) and the six layout templates in `scene-planning.md`: a 2D, slide-friendly helper library and layout contract.
- **Prompts:** [`prompts.py`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/prompts.py): `RESEARCH_AND_PLAN` (misconception analysis, scene-plan format, narration script) and `GENERATE_FROM_PLAN` (18 rules, including a `# NARRATION:` comment above each `self.play()` block).
- **Human-review and project-structure patterns:**
  - [`_shared.py`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/_shared.py) (`confirm_plan`)
  - [`edit_scene.py`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/edit_scene.py)
  - [`audit_video.py`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/audit_video.py)
  - [`split_project.py`](https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/split_project.py)
- **Few-shot references:** [`videos/attention_is_all_you_need/`](https://github.com/AmitSubhash/3brown1blue/tree/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/videos/attention_is_all_you_need) and [`videos/neuronmm/`](https://github.com/AmitSubhash/3brown1blue/tree/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/videos/neuronmm) (research → curriculum → storyboard → per-scene files → audit report).

**4. marcelo-earth/generative-manim: evaluation only**
- [`training/rendering/manim_verifier.py`](https://github.com/marcelo-earth/generative-manim/blob/cc24ede7cc0c51af9217c09a0cba359739eb661e/training/rendering/manim_verifier.py) + `sandbox.py`, and [`training/benchmarks/`](https://github.com/marcelo-earth/generative-manim/tree/cc24ede7cc0c51af9217c09a0cba359739eb661e/training/benchmarks) (`checks.py`, `pass_k.py`, `run.py`, `compare.py`). Use them to build a regression suite from *your own* frozen concept buckets and track render pass@k per model and prompt version.
- **License obligations (Apache-2.0):** include its license text and mark your modifications.

### Ignore

- **3b1b/manim, as a code source.** Install `manim` (Community) instead, and never install both in one environment. Watch 3Blue1Brown videos for visual ideas only.
- **Math-To-Manim:**
  - Duplicates and retired material: `grok/` and `glm/` (vendor duplicates), `legacy/` (Jan 2025 one-shot prompts, Gemini3, KimiK2.5Swarm), `archive/codex-pipeline/` (retired v1.0), `archive/hermes/`.
  - Showcase films, not reusable: `examples/`, `docs/showcase/`.
  - The cinematic style layer: `mythos/cinematography.py`, `CINEMATIC_CHARTER` in `mythos/charter.py`, and the intent / cinematographer / scene-composer film grammar (3D, fixed palette, always `ThreeDScene`).
  - `mythos/backends.py` (CLI subscription plumbing).
  - `mythos/mcp_server.py` and `mythos/api.py`, for now.
- **3brown1blue:**
  - The runtime paths `generate.py`, `from_slides.py` and `remix_audience.py`: one-shot generation, no repair, last-scene-only render, ~85k-token prompts.
  - `mathcode_bridge.py` and `rules/remotion-integration.md`.
  - Out of scope for now, revisit in the timeline phase: `voiceover.py`, `kokoro_bridge.py`, `compose_voiceover.py`.
- **manim-generator:** `prompts/init_prompt.txt` (generic; replace with bucket-driven prompts), `bench_prompts/`, and the optional streaming/headless console extras.
- **generative-manim:**
  - `api/`: Flask routes, the minimal prompt, `max_tokens=1000`, Azure upload.
  - `streamlit/`, `animo/`, `experiments/`.
  - `datasets/`: short, single-`GenScene` samples.
  - The SFT/DPO/GRPO pipeline, unless you later self-host a small model.
  - `training/benchmarks/tasks/core_v1.jsonl` (11 generic tasks).

---

## Redundancy map

| Capability | Where it exists | Keep | Drop |
|---|---|---|---|
| Multi-provider LLM calls | manim-generator (LiteLLM); generative-manim (per-SDK + LiteLLM); 3brown1blue (Anthropic / OpenAI-compatible / `claude -p`); Math-To-Manim (CLI backends) | manim-generator `utils/llm.py` | all others |
| Planning / decomposition | Math-To-Manim charters; 3brown1blue `RESEARCH_AND_PLAN` + rules | Math-To-Manim schema for structure; 3brown1blue rules for paper content | Math-To-Manim intent + cinematographer film stages |
| Static checks | Math-To-Manim `scene_checks.py` (LaTeX-aware); 3brown1blue `audit_video.py` (style lints); manim-generator (scene names only); generative-manim (regex) | Math-To-Manim + selected 3brown1blue lints | rest |
| Render + repair loop | manim-generator; Math-To-Manim Mythos and Sol; generative-manim chat preview loop | manim-generator loop + Math-To-Manim repair *policy* | generative-manim chat loop; Math-To-Manim harness code |
| Frame evidence for review | manim-generator extractor; Sol contact sheet; 3brown1blue fixed-% frames; generative-manim middle frame | manim-generator extractor + Sol contact sheet | others |
| Review output format | manim-generator free text; Sol JSON verdict | Sol verdict schema inside manim-generator's loop | free-text-only review |
| Helper / style library | 3brown1blue `style.py` + `safe_manim.py`; Math-To-Manim `cinematography.py` | 3brown1blue (2D, slide-friendly) | Math-To-Manim cinematic helpers |
| Render verification for evals | generative-manim `manim_verifier.py` | yes (evaluation only) | — |

---

## How the parts fit your pipeline

```
Paper (arXiv LaTeX source preferred; PDF text as fallback)
 1. Ingest ................. YOU BUILD — template: Math-To-Manim archived paper bundle
                             (page-bounded text, equation ledger with source lines, assumptions)
 2. Sieve → concept buckets  Math-To-Manim cartographer / curriculum / math-director schemas
                             + 3brown1blue paper-explainer rules (one insight each, animate-vs-static)
    ⏸ HUMAN GATE 1 — approve / edit / merge / split / drop buckets; check each against its
                     source refs (3brown1blue confirm_plan pattern). Main accuracy checkpoint.
 3. Per-bucket scene plan .. 3brown1blue scene-plan format + layout templates + style.py contract
 4. Codegen ................ one Scene per bucket, one file each:
                             manim-generator writer + 3brown1blue GENERATE_FROM_PLAN rules + verified gotchas
 5. Static gate ............ Math-To-Manim scene_checks.py (+ selected 3brown1blue audit lints)
 6. Render + repair ........ manim-generator run_manim_multiscene
                             + Math-To-Manim repair policy (surgical fix, no retry on timeout, bounded)
 7. Vision review .......... manim-generator frames + Sol contact sheet → Sol-style JSON verdict;
                             stop as soon as it is approved
    ⏸ HUMAN GATE 2 — watch each concept clip + audit report; natural-language edit of a single
                     scene and re-render (3brown1blue edit pattern)
 8. Caching / resume ....... Sol stage_input_hash pattern + a "human-approved" pin so edits persist
 9. Regression eval ........ generative-manim verifier + benchmark harness on your frozen buckets
```

### Suggested concept-bucket fields (and where each idea comes from)

- `id`, `title`, `claim`: the one insight (3brown1blue curriculum; Math-To-Manim act payoff)
- `source_refs`: section, page, equation label and verbatim excerpt (Math-To-Manim archived equation ledger)
- `prerequisites`: each with an `assumed` flag (Math-To-Manim cartographer)
- `equations`: verbatim LaTeX from the arXiv source split into `latex_parts`, with `term_glossary` and `common_misreading` (Math-To-Manim math director)
- `visual_seed`, `animate_or_static`, `layout_template` (Math-To-Manim cartographer; 3brown1blue paper-explainer / scene-planning)
- `caveats`: model assumptions and approximations (Math-To-Manim `assumptions.md`)
- `narration_hook`, `est_seconds`: keeps the later script-timeline phase easy (3brown1blue `# NARRATION:` hooks)

---

## Analysis

- **Why manim-generator is the skeleton even though Math-To-Manim has more features.** manim-generator is small, provider-agnostic, tested in CI and stable, and it has clear seams for adding stages. Math-To-Manim's ideas are better but spread across four churning, vendor-bound, near-duplicate pipelines with a film-specific style contract. Forking it means inheriting all of that; porting 5–6 files gets the ideas without the baggage.
- **Why 3brown1blue is knowledge, not code.** It is the only repo with material written for research-paper explainers and slide-style 2D layouts, which is exactly your domain. But its engine has no repair loop and no tests, and its rules are a strong but unverified draft (its own examples contradict one of its gotchas).
- **The unsolved problem is accuracy, not rendering.** Three repos already solve "make it render"; none solves "make it faithful to the paper". Your novel work is:
  - paper ingestion
  - provenance on every bucket
  - equations copied verbatim from the arXiv source, not regenerated by the LLM
  - a reviewer that sees the source excerpt
  - human gate 1
- **Cost trap.** 3brown1blue's load-everything prompt (~85k tokens per call), times manim-generator's fixed 5 review cycles, times 10–20 concepts per paper, gets expensive quickly. Load rules per stage and stop on approval.
- **Version trap.** Prompts pinned to CE 0.19 (manim-generator, the Math-To-Manim composer) will produce plausible-but-wrong API calls against an installed 0.21. Pin one CE version and state it in every prompt.
- **Plan for the next phase now.** Have each concept scene mark beat boundaries (`self.next_section()` or, if you adopt manim-slides later, `self.next_slide()`) and carry `# NARRATION:` hooks. The script-timeline and slides stage can then cut and align clips without regenerating code. manim-slides is outside your list; version 5.7.0 was released 2026-09-14.

---

## Open questions / not verified

- **Measured performance.** Render success rates, repair-cycle counts and output quality were not measured. Before committing, run a bake-off: take ~5 concept buckets from one paper through (a) the manim-generator loop, (b) Math-To-Manim Mythos and (c) 3brown1blue `generate`. Compare first-render pass rate, repair cycles, human-rated accuracy and cost.
- **Model choice.** I did not review Manim Bench's leaderboard results; use them to choose writer and reviewer models.
- **Motion defects.** Single frames or 12-second contact-sheet sampling likely miss mid-animation overlaps and timing problems. Consider sampling extra frames around `self.play()` boundaries.
- **Remaining gotchas.** Only two of 3brown1blue's 14 gotchas were checked against CE source. The rest are unverified.
- **Style assumption.** This report assumes a light 2D, slide-support style. If you want cinematic 3D, Math-To-Manim's style layer becomes relevant again.

---

## Sources

Repositories, at the commits reviewed (2026-09-15):
- 3b1b/manim — https://github.com/3b1b/manim/tree/fafa083a4fb274bba9cabde0b6e2f50ba6da0622
- HarleyCoops/Math-To-Manim — https://github.com/HarleyCoops/Math-To-Manim/tree/0df6aa9d92b18d76862776a0425fda4d9f5cc023
- AmitSubhash/3brown1blue — https://github.com/AmitSubhash/3brown1blue/tree/fd9bf9c69ac33519acc00dc7faa21bd14b241e54
- makefinks/manim-generator — https://github.com/makefinks/manim-generator/tree/f56fffcd81ca97424f943ec83e12961b6c5acbe1
- marcelo-earth/generative-manim — https://github.com/marcelo-earth/generative-manim/tree/cc24ede7cc0c51af9217c09a0cba359739eb661e

Specific evidence:
- 3brown1blue last-scene-only render: `src/three_b1b/generate.py` `_render_scene` — https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/generate.py#L226-L239
- 3brown1blue contradicting example: https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/skill/rules/paper-explainer.md?plain=1#L183 and https://github.com/AmitSubhash/3brown1blue/blob/fd9bf9c69ac33519acc00dc7faa21bd14b241e54/src/three_b1b/skill/rules/decorations.md?plain=1#L190
- manim-generator fixed review cycles and unused frames: https://github.com/makefinks/manim-generator/blob/f56fffcd81ca97424f943ec83e12961b6c5acbe1/src/manim_generator/workflow.py#L244-L284 and #L384-L404
- generative-manim `max_tokens=1000`: https://github.com/marcelo-earth/generative-manim/blob/cc24ede7cc0c51af9217c09a0cba359739eb661e/api/routes/code_generation.py#L108-L115
- Math-To-Manim README GLM contradiction: https://github.com/HarleyCoops/Math-To-Manim/blob/0df6aa9d92b18d76862776a0425fda4d9f5cc023/README.md?plain=1#L352-L362 vs #L472-L479
- Manim Community source checked (main, 2026-09-15): `manim/mobject/svg/brace.py` (`get_text`, `put_at_tip`) and `manim/mobject/mobject.py` (`next_to`, `save_state`, `class Group`) — https://github.com/ManimCommunity/manim
- PyPI (2026-09-15): manim 0.21.0, released 2026-08-10, requires Python ≥3.11 — https://pypi.org/project/manim/ ; manim-slides 5.7.0, released 2026-09-14 — https://pypi.org/project/manim-slides/
- GitHub REST API (2026-09-15): stars, contributors, and commits since 2026-06-15 for each repo.
