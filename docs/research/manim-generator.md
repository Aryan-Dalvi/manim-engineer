# Deep dive: makefinks/manim-generator

Source of truth: full clone at
`/tmp/claude-0/-root-aisoc-manim-engineer/6bb3163b-6c17-4d10-8cd5-4b79b2c9a27a/scratchpad/research/repos/manim-generator`
(HEAD `f56fffcd81ca97424f943ec83e12961b6c5acbe1`, 2026-09-04). Whole project is ~1,700 LOC of source + ~1,100 LOC of tests. It is small enough to read end to end, and I did.

---

## 1. What it does, and the exact pipeline stages

One-liner: takes a **free-text description of a video**, asks a "code model" for a single Manim Python script, renders each `Scene` subclass as a separate subprocess, feeds render logs + extracted frames to a "review model", asks the code model to rewrite the whole script, and repeats a fixed number of times. Then optionally renders a high-quality MP4 and concatenates scenes with ffmpeg.

Stages, with file/function names:

| # | Stage | Entry point |
|---|---|---|
| 0 | Arg parse + interactive settings confirmation + output dir naming | `src/manim_generator/utils/config.py` → `Config.parse_arguments()` → `_build_config()` (:196) |
| 1 | Load input text | `src/manim_generator/utils/file.py::load_video_data` (or `--video-data` string) |
| 2 | Workflow construction, cost-map registration | `src/manim_generator/workflow.py::ManimWorkflow.__init__` (:36), `utils/llm.py::check_and_register_models` (:209) |
| 3 | **Initial code generation** | `workflow.py::ManimWorkflow.generate_initial_code` (:82) — single user message from `prompts/init_prompt.txt` |
| 4 | **Execute / render** | `workflow.py::execute_code` (:132) → `utils/rendering.py::run_manim_multiscene` (:38) |
| 4a | Scene discovery via AST | `utils/parsing.py::extract_scene_class_names` (:25) — walks AST, picks `ClassDef` whose base name `endswith("Scene")` |
| 4b | Frame extraction from rendered mp4 | `utils/rendering.py::extract_frames_from_video` (:277) — OpenCV; `highest_density` (max non-black pixel ratio over ≤30 sampled frames) or `fixed_count` (N evenly spaced) |
| 5 | **Review** | `workflow.py::_generate_review` (:286) — picks `prompts/review_prompt.txt` or `prompts/review_prompt_enhanced.txt` based on scene success rate vs `--success-threshold` |
| 6 | **Revision** | `workflow.py::_generate_code_revision` (:384) — inline f-string prompt, full-script rewrite |
| 7 | Loop 5→6→4 for `--review-cycles` iterations | `workflow.py::review_and_update_code` (:221) |
| 8 | Finalize: save `video.py`, interactive confirm, high-quality render + ffmpeg concat + autoplay | `workflow.py::finalize_output` (:443) → `utils/video.py::render_and_concat` (:16) |
| 9 | Summary JSON + usage table | `artifacts.py::ArtifactManager.save_final_summary` (:64), `utils/usage.py::display_usage_summary` |

There is **no planning stage**. Input text goes straight into the code-generation prompt. There is no transcript/slide/audio/video ingestion, no scene-graph or storyboard intermediate representation, no narration/audio, no per-scene decomposition by the harness (the model decides scene splits implicitly by emitting multiple classes).

Diagram labels in `docs/excalidraw_flow.excalidraw` confirm the intended flow: `Any Input Data → Initial prompt → Manim Code → script execution → Execution Logs + images → Review Prompt → Review → Revise Prompt → (desired iterations reached?) → Final manim Code → Rendering`.

---

## 2. LLM invocation

**Provider abstraction: LiteLLM only.** `utils/llm.py` imports `from litellm import RateLimitError, completion, model_cost`. There is no internal provider interface — `completion()` is called directly at `utils/llm.py:326` (non-streaming) and `:426` (streaming). Model strings are raw LiteLLM ids; OpenRouter is the documented default path (`openrouter/x-ai/grok-code-fast-1` is the actual default in `utils/config.py:25-26`; the README still claims `openrouter/anthropic/claude-sonnet-4` — **doc drift**).

Notable LiteLLM handling in `LiteLLMParams.to_kwargs()` (`utils/llm.py:32-67`):
- `litellm.drop_params = True` is set **globally at import time** (`utils/llm.py:107`) — a process-wide mutation.
- For `openrouter/*`: reasoning config is passed as OpenRouter's native `extra_body["reasoning"]` object; provider pinning as `extra_body["provider"] = {"order": [provider]}`.
- For direct providers: `reasoning_effort` or Anthropic-style `thinking={"type":"enabled","budget_tokens":N}` with `allowed_openai_params=["thinking"]` to defeat `drop_params`.
- Cost: for `openrouter/*` it prefers provider-reported `usage.cost`, else falls back to `litellm.completion_cost` (`_calculate_cost`, :191).

**Prompt structure.** Three file templates in `prompts/` plus one inline prompt. Templating is naive `str.replace("{placeholder}", value)` in `utils/prompt.py::format_prompt` (:4) — no Jinja, no escaping, and **the path is hardcoded relative: `open(f"prompts/{prompt_name}.txt")`** (`utils/prompt.py:15`). This is the single biggest library-usability defect (see §3).

Message shapes:
- Initial: one `user` message with the rendered `init_prompt`.
- Review: one `user` message whose `content` is a list — `[{"type":"text",...}] + frames` (`workflow.py:351-359`).
- Revision: `[{"role":"system", "content": init_prompt}, {"role":"user", "content": revision_prompt}]` (`workflow.py:398-404`). **No conversation history is accumulated** — each revision is stateless apart from the current code and the single latest review. Prior reviews are only fed to the *reviewer*, XML-wrapped as `<review_0>…` by `utils/prompt.py::format_previous_reviews` (:23).

**Vision review of rendered frames: yes, but reviewer-only.** Frames are extracted from each successfully-rendered scene mp4, PNG-encoded, base64 data-URL'd (`utils/rendering.py:174-181`), and converted to LiteLLM `image_url` parts by `utils/prompt.py::convert_frames_to_message_format` (:42). Two quirks:
- Gating is `vision_enabled = main_vision_support and review_vision_support` (`utils/config.py:226`) — **the code model must also report vision support even though it never receives images**, so a non-vision codegen model silently disables visual review. `--force-vision` overrides both.
- `_generate_code_revision` accepts a `frames` parameter (`workflow.py:390`) and is passed `last_frames` (`workflow.py:273`) but **never uses it** — dead parameter, left over from commit `exclude frames from code model` (2025-10-21). The code model is text-only by design; it only sees the reviewer's prose.

**Revision iterations:** fixed, `--review-cycles`, default **4** in code (`utils/config.py:28`; README says 5). `review_and_update_code` is `for cycle in range(self.config["review_cycles"])` with **no early exit on success** (`workflow.py:244-284`). A script that renders perfectly on iteration 1 still burns all 4 review+revision rounds and 4 more full render passes. Total LLM calls per run = `1 + 2×cycles` (9 at default), each revision emitting the **entire script** again.

**Error feedback:** per-scene stdout/stderr are wrapped in pseudo-XML and concatenated (`utils/rendering.py:122-136`):
```
<SceneName>
    <STDOUT>
        ...
    </STDOUT>
    <STDERR>
        ...
    </STDERR>
</SceneName>
```
plus `<!> Scene X timed out after N seconds` on timeout. This blob goes to the **reviewer** as `{execution_logs}`, not to the code model. So a traceback reaches the fixer only after being paraphrased by a second LLM — a lossy, expensive indirection. Logs are **never truncated**; a verbose Manim failure across 10 scenes can dominate the review prompt. Syntax errors short-circuit before rendering and produce a synthetic log string (`utils/rendering.py:79`).

**Retries:** `MAX_RETRIES=5` with linear backoff `min(2×n, 30)` s, but **only `RateLimitError` retries**. Any other exception is swallowed and returns the literal string `"Review model failed to generate response."` as the completion content (`utils/llm.py:362-376`) — so an API 500 during codegen silently feeds that sentence into `parse_code_block`, which (because `parse_code_block` returns the raw text when no fence matches, `utils/parsing.py:22`) becomes the "code", which then fails to parse, and the loop continues. **Failures are not surfaced as failures.**

---

## 3. CLI interface and library usability

Console scripts (`pyproject.toml`):
- `manim-generate = manim_generator.main:main`
- `manim-render = manim_generator.manual_render:manual_render`

Full flag list: `--video-data`, `--video-data-file`, `--manim-model`, `--review-model`, `--review-cycles`, `--output-dir`, `--manim-logs`, `--streaming`, `--temperature`, `--no-temperature`, `--force-vision`, `--provider`, `--reasoning-effort {none,minimal,low,medium,high,xhigh,max}`, `--reasoning-max-tokens`, `--hide-reasoning`, `--success-threshold`, `--frame-extraction-mode {highest_density,fixed_count}`, `--frame-count`, `--scene-timeout`, `--headless`.

**Is the core importable?** Partially. The class is clean-ish; the environment around it is not. To bypass the CLI you would call:

```python
from manim_generator.workflow import ManimWorkflow
wf = ManimWorkflow(config_dict, rich_console)          # config is a plain dict, not a dataclass
code, _ = wf.generate_initial_code(video_data)
ok, frames, logs, scenes = wf.execute_code(code, "Initial")
code, working, logs = wf.review_and_update_code(code, logs, frames, video_data, scenes)
path = wf.finalize_output(working, code, logs)         # <-- interactive, see below
```

Required `config` keys (from `utils/config.py:252-269` / `tests/test_workflow.py:23-38`): `manim_model`, `review_model`, `review_cycles`, `output_dir`, `manim_logs`, `streaming`, `temperature`, `no_temperature`, `vision_enabled`, `reasoning`, `provider`, `success_threshold`, `frame_extraction_mode`, `frame_count`, `headless`, `scene_timeout`. There is no schema or validator — `Config._build_config` is the only producer, and it is welded to `argparse.Namespace`.

Lower-level pieces that *are* cleanly reusable: `utils/rendering.py::run_manim_multiscene`, `extract_frames_from_video`, `calculate_scene_success_rate`; `utils/parsing.py::extract_scene_class_names`, `parse_code_block`; `utils/video.py::render_and_concat`; `utils/llm.py::get_completion_with_retry`.

**Concrete wrapping obstacles:**

1. **CWD-dependent prompt loading.** `utils/prompt.py:15` does `open(f"prompts/{prompt_name}.txt")`. Prompts are *not* package data (not under `src/`, not in `[tool.hatch]` includes). Importing the library from any other working directory raises `FileNotFoundError`. There is no prompt-override hook at all — to change a prompt you must ship a `prompts/` directory next to your process CWD.
2. **Interactive `rich.prompt` calls inside the core.** `Confirm.ask` three times in `workflow.py::finalize_output` (:463, :468, :480); `Prompt.ask` in `utils/llm.py::check_and_register_models` (:235, :248) and `Config._confirm_settings` (:365). `--headless` suppresses these, but see #3.
3. **`--headless` never renders the final video.** In `finalize_output`, the entire render branch is nested inside `if not self.headless:` (`workflow.py:461-478`). Headless runs produce `video.py` and a summary JSON and **no MP4**. This is almost certainly unintended, and it means the one non-interactive mode is also the one that produces no video.
4. **Global state:** `litellm.drop_params = True` at import (`utils/llm.py:107`); `register_model()` mutates LiteLLM's global cost map; `os.environ` is the only API-key channel.
5. **`Console` injection is mandatory**, and `rich` markup is baked into log/return strings (e.g. `raise Exception("[bold red]Max retries exceeded.[/bold red]")`, `utils/llm.py:378`). Presentation leaks into the domain.
6. **`render_and_concat` autoplays the video** — `xdg-open` / `open` / `cmd /c start` (`utils/video.py:140-176`). In a server or CI context this is an unconditional side effect on the success path.
7. `manual_render._discover_latest_output_dirs` does `Path(".").rglob("workflow_summary.json")` — recursive scan of CWD.
8. Nothing is async; everything is blocking `subprocess.communicate` and synchronous `completion()`. Scenes render **serially** (`utils/rendering.py:89`).

---

## 4. Rendering, failure handling, artifacts

**Rendering (iteration loop)** — `utils/rendering.py:90-97`:
```python
command = ["manim", "-ql", "--media_dir", output_media_dir, filename, scene]
```
`subprocess.Popen` with piped stdout/stderr, `env=os.environ.copy()`, `communicate(timeout=scene_timeout)` (default 400 s, `0` disables), `process.kill()` on timeout. **One subprocess per scene, serial.** `-ql` = 480p15, hardcoded via `QUALITY_FOLDER_LOW = "480p15"` (:30). Video path is reconstructed by string convention: `<media_dir>/videos/<script_basename>/480p15/<Scene>.mp4` (:157) — brittle against any Manim layout change, and the reason `prompts/init_prompt.txt` forbids the model from touching `config.quality` / `config.output_file`.

Success = `returncode == 0` per scene; overall `rendering_success` is True only if **every** scene exits 0 (`:66`, `:144-151`). After frame extraction, successful scenes' mp4s are **deleted** so stale videos can't inflate the next iteration's counts (:218-242).

**Final render** — `utils/video.py::render_and_concat` (:31-38):
```python
["manim", "-qh", script_file, "--write_all", "--media_dir", output_media_dir]
```
`-qh` = 1080p60, `--write_all` renders every scene in one process, then ffmpeg concat demuxer with `-c copy` over a generated `ffmpeg_concat_list.txt`, ordered by AST class order. Then autoplay.

**Failure handling summary:** render failures → logs → reviewer → revision (no direct error→fixer path). Timeouts → killed, logged, counted as failure. Syntax errors → caught pre-render. LLM errors other than rate limits → silently converted to a sentinel string. **No fallback to last-known-good code inside the loop** — `working_code` only tracks the most recent fully-successful iteration and is used at finalize time, so the loop can and does regress (a later cycle's rewrite may break scenes that previously worked; `working_code` then retains the older good version, but the *reviewer* keeps reviewing the broken one).

**Artifacts** (`artifacts.py`), under `output/<model>_<first-4-words>_<timestamp>/`:
- `video.py` (last working code) and `steps/<step>/{code.py,prompt.txt,logs.txt,review.md,reasoning.txt}`
- `steps/<step>/frames/NN_<Scene>.png`
- `final_video.mp4` (only if interactively confirmed)
- `workflow_summary.json` — models, input, execution_stats incl. per-step `execution_history`, timing split (workflow vs LLM), full token/cost breakdown per step, video path, artifact index.

The artifact + summary layer is genuinely good and is the most directly stealable component.

**No GIF support anywhere.** `grep -rni "gif|--format|save_last_frame"` over the repo returns nothing. Output is MP4 only, 480p15 during iteration and 1080p60 at the end.

---

## 5. License, activity, issues

- **License: MIT** (`LICENSE`, © 2025 makefinks). No attribution burden beyond keeping the notice. Fork/vendor is legally trivial.
- **Activity:** created 2025-01-28; last push **2026-09-04** (~10 days before today). 117 stars, 24 forks, 5 watchers. Commit cadence: steady through Sep–Dec 2025, then sparse — 2026-02-15 (two commits), then nothing until 2026-09-04. **Effectively a single-maintainer project in low-maintenance mode.**
- **PRs: 0, ever.** No external contribution pipeline.
- **Issues: 3 total, 1 open.**
  - #2 (open, 2025-12-24): *"Can we add support to also auto generate audio; (narration)"* — confirms no TTS/narration path.
  - #1 (closed, 2025-07-03): *"How long does it take… it seem more than 15 minutes to render output video. Is it a normal behavior?"* — user-reported runtime confirms this is not near-real-time.
  - #3 (closed, 2026-05-02, Vietnamese): "this manim version is too old, can we upgrade" — the prompts hardcode "Manim Community v0.19.0" in three places and `pyproject.toml` pins `manim>=0.19.0`.
- CI (`.github/workflows/ci.yml`) is real: ruff lint + format, pytest on 3.10/3.11/3.12, coverage to Codecov. Tests are decent unit coverage (~1,100 lines) but the only E2E test is skipped without `OPENROUTER_API_KEY`.

---

## 6. Shortcomings for our use case, and recommendation

Our pipeline is: presentation input (transcript/slides/audio/video/manuscript) → **animation plan** → Manim generation → quality review → **GIF/slide output**. Mapped against this repo:

| Our requirement | Status in manim-generator |
|---|---|
| Multi-modal presentation ingestion | **Absent.** Input is one text string or one text file. No parsing, chunking, or slide alignment. |
| Explicit animation plan artifact | **Absent.** Text → code in one hop. No plan to review, edit, or version. |
| Per-slide / per-segment generation | **Absent.** One monolithic script; scene boundaries are whatever the model emitted. No way to regenerate slide 7 without regenerating everything. |
| GIF output | **Absent.** MP4 only; `-qh` final render + ffmpeg concat. Adding `--format=gif` is easy, but the whole path assumes `<Scene>.mp4`. |
| Live-ish latency | **Poor.** Serial scene subprocesses, 5 full render passes at default, 9 blocking LLM calls, whole-script rewrites. Maintainer's own issue thread reports >15 min. Nothing is parallel or incremental. |
| Quality guarantees | **Weak.** Success = exit code 0. The vision review is prose advice with no rubric, no score, no gate, no accept/reject. No early exit when good, no rollback when a revision regresses. |
| Determinism / reproducibility | **Weak.** `temperature=0.4` default, no seed, no response caching, no prompt/model pinning in a lockfile sense. Rerunning the same input gives a different script. The summary JSON does capture the exact config, which helps forensics but not reproduction. |
| Cost control | **Weak.** No budget cap, no token cap, no early exit. Cost scales as `1 + 2×cycles` full-script generations; a 600-line script rewritten 4× is ~4× output-token cost on top of growing review prompts with untruncated logs. Cost is *measured* well (`utils/usage.py`) but never *enforced*. |
| Error routing | **Weak.** Tracebacks are laundered through a reviewer LLM instead of going straight to a fixer. Non-rate-limit API errors become a sentinel string rather than an exception. |
| Library ergonomics | **Poor.** CWD-coupled prompt loading, interactive prompts inside the core, `--headless` produces no video, global LiteLLM mutation, autoplay side effect, `rich` markup in return values. |

### Recommendation: **borrow the architecture and reimplement.** Vendor two or three files; do not wrap, do not fork.

Reasoning:

- **Wrapping is blocked by the prompt loader alone.** `open(f"prompts/{prompt_name}.txt")` with no override hook means we would have to control the process CWD and ship their `prompts/` directory — and our whole value-add is *different prompts* (plan-aware, slide-scoped, GIF-targeted). We would be fighting the one function we most need to replace. Add the interactive `Confirm.ask` calls, the headless-renders-nothing bug, and the autoplay, and a wrapper becomes a pile of monkeypatches.
- **Forking is nearly as much work as reimplementing, for a worse result.** The parts we would have to rip out (fixed-cycle loop, prose-only review, single-string input, no plan stage, no GIF, argparse-shaped config dict, CLI coupling) are the *architecture*. The parts worth keeping are ~400 lines. A fork saddles us with `main.py`/`console.py`/`config.py`/`manual_render.py` — all pure CLI — plus a divergence burden against a repo with 0 PRs and a maintainer who pushes every few months. MIT means there is no licensing reason to prefer a fork over vendoring.
- **What to actually take**, near-verbatim, with attribution:
  1. `utils/rendering.py::run_manim_multiscene` — the per-scene-subprocess + timeout + exit-code-based success model is the correct design, and the `<media_dir>/videos/<basename>/<quality>/<Scene>.mp4` path convention plus the post-extraction mp4 cleanup are hard-won details. Change `-ql` to a parameter and add `--format=gif`.
  2. `utils/rendering.py::extract_frames_from_video` — the **highest-density heuristic** (sample ≤30 frames, pick max non-black pixel ratio, `BLACK_PIXEL_THRESHOLD=30`) is a genuinely clever cheap way to skip fade-in/fade-out blank frames and hand the vision reviewer a frame that actually shows something. Steal this outright.
  3. `utils/parsing.py::extract_scene_class_names` — AST walk with `base_id.endswith("Scene")`, returning the error as a value so the loop can degrade gracefully. Ten lines, correct.
  4. `artifacts.py` + `utils/usage.py` — the per-step artifact tree and the workflow summary schema are better than what we would design on a first pass. Adopt the shape.
  5. The **success-rate-gated prompt switch** (technical review below threshold, visual/creative review at/above) — this is the single best idea in the repo and generalizes directly to our quality-review stage.
- **What to design differently from day one:** a plan artifact between input and code; per-slice generation and per-slice regeneration; raw stderr routed *directly* to a fixer call (reviewer for aesthetics only, compiler errors for correctness); early exit when all scenes render and the reviewer returns no blocking findings; keep-best-and-rollback instead of blind forward rewrites; a structured review output (JSON with severity, not markdown prose) so "quality" is machine-checkable; a token/dollar budget that aborts; `temperature=0` plus prompt hashing for reproducibility; unified-diff or per-scene patch revisions instead of whole-script rewrites; GIF as a first-class render target.

Rough effort read: a reimplementation that reaches feature parity with their loop is 1–2 days, because the repo is 1,700 lines and we would be copying the 400 that matter. Making a wrapper behave in a server context is comparable effort with permanent drag.

---

## 7. Prompt-engineering tricks worth stealing verbatim

These are quoted exactly from `prompts/`.

**(a) The path-convention guard rails** — these exist because `run_manim_multiscene` reconstructs the output path by string convention, and any `config` mutation by the model breaks discovery. We need the identical constraints. From `prompts/init_prompt.txt`:

> - If you decide to use multiple scenes, each scene should be defined as a separate class inheriting from `Scene` (or an appropriate Manim scene class).
> - Do not create a class aggregating these scenes
> - Do NOT use external resources or dependencies like svg's, images, or other libraries.
> - Do not adjust the manim configuration inside the code. Config adjustments like `config.quality` or `config.output_file` are forbidden.

"Do not create a class aggregating these scenes" is the non-obvious one — without it models emit a `MainScene` that calls the others, and the AST scene-counter then double-renders everything.

**(b) Anti-repetition clause for iterative review.** Repeated identically in both review prompts, and it is what stops a reviewer from re-listing the same three findings for four cycles:

> IMPORTANT: Do not include things that were already mentioned in <previous_reviews>. Except for things that were not fixed.

**(c) Noise suppression in review.** From `prompts/review_prompt.txt`:

> Do not mention minor things like missing comments. Give feedback that is crucial to the functionality of the script.

**(d) Force the reviewer to actually look at every image.** Identical in both review prompts — without the explicit "every scene / image" instruction, vision models comment on one frame and generalize:

> There also may be images provided to you, if so, please make them a priority in your review: Provide visual feedback for every scene / image you receive.

**(e) Keep the reviewer out of the codegen lane.** Both review prompts:

> Do NOT propose to use external resources or dependencies like svg's, images, or other libraries.
> Do NOT propose config adjustments like `config.quality` in the review.
> Do NOT respond with the improved code. Instead describe the changes that should be made.

**(f) The success-rate-gated mode switch.** `prompts/review_prompt_enhanced.txt` opens by telling the reviewer its own success statistics and re-tasking it:

> You will be receiving the current iteration of code <video_code> for a manim video that has rendered successfully with {success_rate}% of scenes working ({scenes_rendered} of {total_scenes}). Since the code is functionally working well, focus on VISUAL IMPROVEMENTS and CREATIVE ENHANCEMENTS.

with the crucial escape hatch:

> If there are scenes that are not working yet, focus on fixing these critical issues first, while making only minor suggestions for the visual improvements.

**(g) Taste clamp on the creative reviewer** — one line that prevents the "add particles and glow to everything" failure mode:

> - Be tasteful, do not overdo it, keep the styling minimal but elegant, according to modern design principles

**(h) Full-rewrite instruction on revision.** Inline at `workflow.py:396`. The trailing sentence is what stops models emitting `# ... rest unchanged ...`:

> Please implement the suggestions and respond with the whole script. Do not leave anything out.

**(i) XML tagging of accumulated reviews.** `utils/prompt.py::format_previous_reviews` wraps each prior review as `<review_0>…</review_0>`, `<review_1>…`, and the render logs are wrapped per scene as `<SceneName><STDOUT>…</STDOUT><STDERR>…</STDERR></SceneName>`. Cheap, and it makes "which scene failed" unambiguous to the reviewer.

**(j) Output-purity instruction.** `prompts/init_prompt.txt` closes with:

> Start now by creating the code for the video, do not respond with anything else.

Paired with `parse_code_block`'s permissive fallback (returns raw text if no ``` fence is found, `utils/parsing.py:22`), which is a reasonable belt-and-braces pattern to copy.

Note two typos preserved in their files if we copy verbatim: "Execution Logs / Errros", "asthetically", "feautures", "libary". Fix on copy.
