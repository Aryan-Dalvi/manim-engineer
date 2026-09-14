# Research: `AmitSubhash/3brown1blue` as a Manim knowledge pack for an automated pipeline

Local clone for all path citations: `/tmp/claude-0/-root-aisoc-manim-engineer/6bb3163b-6c17-4d10-8cd5-4b79b2c9a27a/scratchpad/research/repos/3brown1blue`
(paths below are relative to that root unless absolute).

---

## 1. What the repo is

It is **both**: a pip-installable CLI app **and** a self-contained agent skill pack that the CLI installs into your coding agent.

- **PyPI package** `3brown1blue` v0.3.1 (`pyproject.toml`), entry point `three_b1b.cli:main`. Runtime deps: only `click`. LLM providers are optional extras (`anthropic`, `openai`, `slides`).
- **CLI commands** (`src/three_b1b/cli.py`): `generate`, `from-slides`, `voiceover`, `compose-voiceover`, `install`, `uninstall`, `update`, `status`, plus `audit` (`src/three_b1b/audit_video.py`), `edit-scene`, `remix-audience`, `split-project`.
- **The skill pack** lives entirely under `src/three_b1b/skill/` (616 KB). `3brown1blue install` copies it verbatim to:
  - Claude Code → `~/.claude/skills/manim/` (whole directory tree, `cli.py:85-91`)
  - Cursor → `.cursor/rules/manim-*.mdc`, one `.mdc` per rule file (`cli.py:105-138`)
  - Windsurf → `.windsurfrules` (all rules merged into one file, `_merge_skill_markdown()` at `cli.py:50`)
  - Copilot → `.github/copilot-instructions.md` (same merge)
- **`videos/`** is a corpus of 6 fully-worked example projects (attention, FGW, NeuronMM, TheHuzz, TribeV2, v030 showcase) — ~60 real `scene_*.py` files, `plan.md`/`storyboard.md`/`curriculum.md`/`audit_report.md`, each with its own `utils/style.py`. This is *not* shipped in the wheel (`tool.hatch.build.exclude`) but is the single best few-shot source in the repo.

### Skill pack structure and format

```
src/three_b1b/skill/
├── SKILL.md                 # 7.7 KB router — YAML frontmatter + gotcha list + rule index
├── rules/          27 files, 300 KB total
├── audiences/       4 files (high-school, undergrad, graduate, industry)
├── domains/         7 files (ML, math, physics, biology, security, neuro, algorithms)
├── templates/       3 files (style.py, equation_explainer.py, paper_explainer.py)
├── scripts/         4 files (safe_manim.py, render_scene.sh, audit_video.sh, concat_scenes.sh)
└── assets/designing-math/   README + demo scene + 3 reference PNGs
```

**`SKILL.md` frontmatter** (`src/three_b1b/skill/SKILL.md:1-8`):

```yaml
---
name: manim
description: Use when the user wants to create mathematical animations, research paper explainer
  videos, equation derivations, 3D visualizations, or any programmatic animation with Manim. Also
  trigger when the user mentions "3Blue1Brown style", "animate this equation", "explain this paper
  visually", or wants to render LaTeX equations as video.
metadata:
  tags: manim, animation, math, visualization, latex, 3blue1brown, video, research
---
```

Note `metadata.tags` is non-standard for the Anthropic skill spec (harmless; ignored). There is **one** skill, not many — `SKILL.md` is a router with 14 inline "Gotchas (read these first)" and a curated index of the 27 rule files under section headers (Core / Equations / Dynamic and 3D / Visual Design / Video Production / Reference). Progressive disclosure is explicit: *"Claude should read only what it needs, not all files at once."*

**Every rule file carries its own YAML frontmatter** (`name`, `description`, `tags`) — this is what the Cursor installer converts into `.mdc` rule files. So each rule file is independently addressable and self-describing, which makes them directly usable as retrieval documents.

**Prompt layer** (`src/three_b1b/prompts.py`, 9.6 KB): `SINGLE_SCENE`, `RESEARCH_AND_PLAN`, `GENERATE_FROM_PLAN`, plus slide variants. These are the "user turn" that assumes the rule files are already in the system prompt — the docstring says so explicitly: *"These prompts are the bridge between the user's intent and the full Manim skill loaded in the system prompt."*

---

## 2. Every skill/reference file, one line each

### `rules/` (27 files, ~300 KB)

| File | What knowledge it encodes |
|---|---|
| `rules/production-quality.md` (17.8 KB) | **The single most valuable file.** Safe bounds, buff minimums, container-fit rules, data-viz size/opacity floors, dim-vs-fadeout, 15-item pre-render + 10-item post-render checklists, 10 named "known failure patterns from production audits". |
| `rules/scene-planning.md` (18.5 KB) | 6 named layout templates (FULL_CENTER, DUAL_PANEL, TOP_PERSISTENT_BOTTOM_CONTENT, BUILD_UP, CHART_FOCUS, GRID_CARDS) with ASCII coordinate maps; scene-plan schema; 4 narrative arcs; the verbatim 18-rule agent prompt block; style.py contract; post-generation fix cycle. |
| `rules/visual-design-catalog.md` (24.2 KB) | 35 implementable visualization patterns with Manim code (probability sidebar, skip-connection arc, progressive grid fill, multi-scale zoom, question frame, heatmap grid, camera zoom detail, tip-to-tail vector walk, commutative-diagram grid, …). |
| `rules/visual-design-principles.md` (15.2 KB) | 17 numbered principles (geometry before algebra, opacity layering, persistent context, linked dual representations, question frames, annotations ON objects, color as semantic data, concrete values, density ramp, per-scene skeleton, caption zone, monospace). |
| `rules/troubleshooting.md` (13.7 KB) | Error→cause→fix catalog: LaTeX failures, Transform ghosts, updater freeze, late-binding closures, `LaggedStartMap(Write,…)`, `interpolate_color` hex crash, `.animate` in VGroup, silent-bug section, agent-generation-specific errors, ffmpeg concat path bug. |
| `rules/animations.md` (12.1 KB) | Animation-object model, Transform family semantics, `.animate`, rate functions, composition (`LaggedStart`, `Succession`, `AnimationGroup`). |
| `rules/equations.md` (12.0 KB) | MathTex vs Tex, submobject addressing (`{{ }}`, multi-arg, `substrings_to_isolate`), `tex_to_color_map`, `get_part_by_tex`, `TransformMatchingTex`. |
| `rules/graphs-plots.md` (12.3 KB) | `Axes`, `plot`, parametric curves, `BarChart`, Riemann sums, data viz. |
| `rules/equation-derivations.md` (5.8 KB) | Dim-and-reveal derivation choreography, annotation patterns, worked examples. |
| `rules/matrices-linalg.md` (8.0 KB) | `Matrix`, linear transformations, eigenvectors, vector spaces. |
| `rules/decorations.md` (7.5 KB) | `SurroundingRectangle`, `Brace`, arrow annotation patterns. |
| `rules/mobjects.md` (10.0 KB) | Mobject/VMobject/VGroup hierarchy, positioning, styling. |
| `rules/scene-lifecycle.md` (4.7 KB) | Scene subclasses, `construct()`, play/wait/add/remove, camera setup. |
| `rules/updaters-trackers.md` (10.5 KB) | `ValueTracker`, `add_updater`, `always_redraw`, `frozen_frame`. |
| `rules/three-d.md` (10.0 KB) | `ThreeDScene`, camera angles, `Surface`, 3D vector fields. |
| `rules/moving-camera.md` (8.1 KB) | `MovingCameraScene` zoom/pan/follow. |
| `rules/explanation-design.md` (10.7 KB) | *Content* design from Grant Sanderson's "Designing Math" (Config 2026): ask "what does it look like?", give every symbol a motivation, motivate with the most surprising application. |
| `rules/pedagogy-checklist.md` (10.1 KB) | 7-item "is the explanation done?" checklist from Sanderson's JMM 2023 lecture + SoME rubric (motivating example before definition, rediscoverable proofs, concrete before abstract, problem before instruction, raise the ceiling/lower the floor). |
| `rules/animation-design-thinking.md` (7.6 KB) | **Timing tables**, animate-vs-static decision tree, visual beats, narration sync ("see then hear", 0.3–0.5 s lead), speaking-rate math, equation decomposition order, 6 common design mistakes. |
| `rules/paper-explainer.md` (21.9 KB) | Full explainer-video structure and per-domain patterns for research papers. |
| `rules/project-organization.md` (9.0 KB) | Multi-scene project layout, shared `style.py`, batch render scripts, `manim>=0.18.0` requirement pin. |
| `rules/voiceover.md` (10.3 KB) | TTS backends (Kokoro/VibeVoice/Chatterbox), teaching-style text rewrites, `# NARRATION:` beat comment format, duration math, `manim-voiceover` plugin, audio-fit strategies. |
| `rules/config-rendering.md` (10.0 KB) | Quality presets table, CLI flag reference, `manim.cfg`, output dir layout, transparency (webm only), `next_section()` chaptering, custom `TexTemplate`, caching. |
| `rules/color-palettes.md` (9.4 KB) | Manim's ~170 color constants, 4 named palettes (academic/vibrant/…), accessibility notes, and the **3b1b entity-color binding** rule with exact hex values. |
| `rules/first-scene-tutorial.md` (6.0 KB) | Install → hello world → render commands. Beginner onboarding only. |
| `rules/manimgl-differences.md` (7.5 KB) | CE vs ManimGL comparison table, import/API/config deltas, migration notes both directions, interactive mode. |
| `rules/remotion-integration.md` (7.5 KB) | Rendering Manim clips (mp4 opaque / webm transparent) for compositing in a Remotion timeline. |

### `audiences/` (4 files, ~32 KB)
Each: assumed knowledge (explicit do/don't lists), curriculum structure with a 7-step scene template, **required misconception analysis** (Muller pattern), vocabulary/notation substitution lists, pacing and annotation depth, scene-count targets (high-school 5–7, undergrad 8–10, graduate 10–12, industry 6–8).

### `domains/` (7 files, ~58 KB)
Each: expected visual vocabulary for the field, a *concept → layout template* mapping table, **5 named domain patterns** (e.g. `ML-1 Layer-by-Layer Architecture Build`, `ML-3 Loss Landscape Surface`, `ML-4 Attention Weight Animation`) with color assignments and template recommendation, color semantics, notation conventions.

### `templates/`
- `templates/style.py` (7.4 KB) — the canonical style contract: semantic color dict `C`, font-size constants, `HOLD_SHORT/MEDIUM/LONG` timing constants, `labeled_box()`, `pipeline_arrow()`, `safe_text()`, `safe_multiline()`, `section_title()`, `bottom_note()`, `fade_all()`, `story_bridge()`, plus the 3b1b `ENTITY` color dict, `glow_dot()`, `role_annotation()`, `vector_walk()`.
- `templates/equation_explainer.py` (2.7 KB) — dim-and-reveal equation scene scaffold.
- `templates/paper_explainer.py` (3.1 KB) — 5-section paper explainer scaffold.

### `scripts/`
- `scripts/safe_manim.py` (2.6 KB) — drop-in wrappers for the 5 crash-prone APIs: `safe_arrow`, `safe_brace_label`, `safe_lagged_write`, `safe_get_part` (raises instead of returning `None`), `safe_replacement_transform`.
- `scripts/render_scene.sh` — single-scene render with quality flag + output locator.
- `scripts/audit_video.sh` (8.8 KB) — extracts 5 frames/scene at 10/25/50/75/90 % via ffmpeg + prints a 30-item visual inspection checklist.
- `scripts/concat_scenes.sh` (5.4 KB) — ffmpeg concat-demuxer join of scene MP4s, stream copy.

### `assets/designing-math/`
Three reference stills + `designing_math_demo.py` reproducing catalog patterns 27/28/29 from the Config 2026 talk; the README maps still→pattern→idea.

### Non-skill code worth stealing
- **`src/three_b1b/audit_video.py`** — a **10-check regex static linter** over generated scene source (see §5). This is the most directly reusable engineering artifact in the repo.
- `src/three_b1b/prompts.py` — the three prompt templates.
- `src/three_b1b/from_slides.py` — PPTX ingestion with auto-detection of whether vision extraction is needed (`_detect_mode(avg_text, pic_ratio, provider)`), directly relevant to your "presentation input" stage.
- `src/three_b1b/compose_voiceover.py`, `voiceover.py`, `kokoro_bridge.py` — beat-aligned TTS muxing.
- `src/three_b1b/remix_audience.py`, `edit_scene.py`, `split_project.py`, `mathcode_bridge.py`.

---

## 3. Manim flavor and version pins

**Targets ManimCE (Manim Community Edition).** `SKILL.md:17`:

> **Default to Manim Community Edition** (`pip install manim`) unless the user specifically needs ManimGL's interactive features.

- Every code sample uses `from manim import *`; CE-only APIs are used throughout (`ThreeDScene`, `add_fixed_in_frame_mobjects`, `BarChart`, `MovingCameraScene`, `config` object, `--format webm -t`).
- ManimGL appears only in **one** comparison/migration doc, `rules/manimgl-differences.md`, whose recommendation is *"Develop in Community Edition for final output."*
- **No hard version pin anywhere.** `pyproject.toml` does not depend on manim at all (the package only shells out). The only loose pins in the whole pack:
  - `rules/project-organization.md:290` → `manim>=0.18.0` (inside a sample `requirements.txt`)
  - `rules/config-rendering.md:128` → an output filename example `MyScene_ManimCE_v0.18.0.png`
  - `README.md` prerequisites → bare `pip install manim`
- **Implication for you:** you must pin manim yourself. The rules were written against ~0.18.x; on newer CE the `ManimColor` guidance is right, but verify `BarChart` / `set_fill_by_value` / `Brace.get_text` behaviours against your pinned version.

---

## 4. The most valuable rules, verbatim

From `src/three_b1b/skill/rules/scene-planning.md` (the mandatory agent-prompt block, abridged):

```
1. Layout: Use the specified template. Never use absolute x > 5.5 or y > 3.2
2. Density: Fill 50%+ of frame. Bars: fill_opacity >= 0.6, width >= 0.3
3. Edge overflow: If a box is at |x| > 2.5, place auxiliary labels BELOW (DOWN),
   never further toward the screen edge. Do NOT write x-clamp guards.
4. Text: Use safe_text() for single lines. Use safe_multiline() for centered
   multi-line text. NEVER use \n inside Text() for centered displays.
5. Bottom notes: Use bottom_note() helper. Animate with FadeIn(note, shift=UP*0.2),
   NOT Write(). Write() creates ugly partial-stroke frames on small text.
7. Containers: Child elements positioned relative to parent (next_to, move_to).
   Children inside a labeled_box() must be offset DOWN * 0.3 from center to avoid
   covering the label.
8. Lifecycle: FadeOut titles/headers COMPLETELY before new content appears in the
   top 25% of the frame. Dimming to 0.1 is NOT removal. FadeOut means FadeOut.
10. Transitions: Combine FadeOut of previous phase with Write/FadeIn of next
    phase title in a SINGLE self.play() call. Never leave a frame with only a
    title and > 60% empty space.
15. DIM_OPACITY = 0.1, never 0.3. On dark backgrounds, 0.3 still competes.
16. Arrows: Use pipeline_arrow() with buff=0.25. For arrows between boxes less
    than 1.5 units apart, increase buff to 0.3 or reduce tip size.
17. Chart legends: Place in the corner with LEAST data density. For rising
    curves, use lower-right. Never place where curves converge.
```

From `rules/production-quality.md` (spatial + anti-overlap + variety):

```
Frame: 14.2 wide x 8 tall, centered at ORIGIN.
Safe bounds: x: [-6.5, 6.5], y: [-3.5, 3.5].
Never use absolute coordinates > 5.5 in x or > 3.2 in y. shift(RIGHT * 6) = likely clipped.
Visible content should occupy >= 50% of frame area.

bar_width >= 0.3       # narrower bars invisible at 720p
fill_opacity >= 0.6    # data elements (bars, dots, areas)
dot_radius >= 0.06     # smaller dots vanish at 720p
axes_width >= 5.0      # chart axes >= 40% of frame width

Rule: Dim BESIDE, FadeOut UNDER
Manim has NO auto-wrap. Long text will overflow the screen silently.
Rule: Minimum font size 20pt for all on-screen text.
Rule: No two consecutive scenes should use the same visual technique.
Rule: At least one question frame per 3 scenes.
Rule: Frame complexity must increase across the video.
  Scene 1-2: 3-5 elements | Scene 3-5: 6-10 | Scene 6-7: 10-15 | Final: 3-5
The test: "Would a first-time viewer understand this visual within 3 seconds of seeing it?"
```

From `rules/animation-design-thinking.md` (timing — the table LLMs most often get wrong):

```
| Action                        | run_time    | wait after |
| Show equation for first time  | Write: 1-2s | 2-3s       |
| Highlight/annotate one term   | 0.5s        | 1s         |
| Transform equation step       | 1.5-2s      | 1.5-2s     |
| FadeIn new element            | 0.5-1s      | 0.5s       |
| Build pipeline stage          | 0.5s        | 0.3s       |
| Camera zoom/pan               | 1.5s        | 1s         |
| Major reveal (final result)   | 1-2s        | 3s         |

After every 3-4 animations, add self.wait(1-2).
The animation should START slightly BEFORE the narrator describes it (about 0.3-0.5s lead time).
Average speaking rate: 150 words per minute = 2.5 words per second
Too many simultaneous animations: Viewers can track 1-2 moving things.
```

From `SKILL.md` gotchas + `rules/troubleshooting.md` (LaTeX / API pitfalls):

```
1. Create(Text(...)) looks wrong -- use Write() for text. Create() traces outlines.
4. MathTex(r"$E=mc^2$") crashes -- MathTex is already math mode. Drop the $. Use Tex for mixed text+math.
5. Transform(A, B) then animating B does nothing -- B was never added. Use ReplacementTransform.
7. LaggedStartMap(Write, group) crashes -- use LaggedStart(*[Write(m) for m in group]).
8. Updaters freeze during self.wait() -- add frozen_frame=False.
10. get_part_by_tex("missing") returns None silently.
13. VGroup.add(mob.animate.move_to(...)) crashes -- .animate returns an _AnimationBuilder.
14. Group.save_state() crashes -- Group does not support save_state()/restore().

MathTex(r"50%")  # BAD: percent sign starts a LaTeX comment, eats rest of line
MathTex("\frac{1}{2}")  # BAD: forgot raw string - Python interprets \f as form-feed
interpolate_color(CHIP_BLUE, ...)  # BAD: 'str' object has no attribute 'interpolate'
                                   # py_compile does NOT catch this -- wrap in ManimColor()
for obj in objects:                # BAD: late-binding closure
    label.add_updater(lambda m: m.next_to(obj, UP))
Lint check: After generating scene code, grep for `\.add\(.*\.animate`
mp4 does NOT support alpha channels. Use webm: manim -qh --format webm -t
```

---

## 5. How to ingest this into an automated pipeline

Your stages: **presentation input → animation plan → LLM Manim generation → quality review → GIF/slide output.** Four distinct ingestion modes apply, and the pack is unusually well-suited because it was *built* for a headless `plan → generate → audit` loop (that is literally what `three_b1b.cli` does).

### (a) System-prompt context (always-loaded core)
Budget ~35–45 KB. Load these verbatim into the **code-generation** agent's system prompt:
- `rules/production-quality.md` §1–5, §8–9, §17 (drop the render-workflow prose)
- `rules/scene-planning.md` "Layout Templates" + the 18-rule "Section 2: Rules" block
- `SKILL.md` "Gotchas" (14 items)
- `rules/animation-design-thinking.md` timing table
- `templates/style.py` (as an actual importable file in the generated project, not just prose)

The 18-rule block at `rules/scene-planning.md` "Section 2: Rules (copy-paste, same for ALL agents)" is **pre-formatted for exactly this** — paste it unmodified.

### (b) Retrieval documents (load-on-demand)
Every rule file has YAML frontmatter with `name`/`description`/`tags`, so they chunk and embed cleanly with no preprocessing. Route on the plan's own metadata rather than on embeddings where you can:
- plan declares `Template: CHART_FOCUS` → retrieve `rules/graphs-plots.md`
- plan declares `domain: machine-learning` → retrieve `domains/machine-learning.md`
- plan declares `audience: high-school` → retrieve `audiences/high-school.md`
- scene uses 3D / camera / updaters → retrieve `rules/three-d.md` / `moving-camera.md` / `updaters-trackers.md`

The 6 layout templates and 35 catalog patterns are **enumerable IDs**, which is the real win: make the planner emit `Template: DUAL_PANEL, Patterns: [15, 24]` and the generator retrieve only those sections. That converts prose guidance into a constrained decision space an LLM can't drift out of.

### (c) Linting rules (pre-render gate) — highest ROI
`src/three_b1b/audit_video.py` already implements a 10-check regex linter over generated source. Lift `run_checks()` and `ALL_CHECKS` directly (MIT):

| Check fn | Catches |
|---|---|
| `_check_newline_in_text` | `Text(...\n...)` (left-align bug) |
| `_check_bottom_note_animation` | `Write(bottom_note)` instead of `FadeIn` |
| `_check_dollar_in_mathtex` | `MathTex(r"$...$")` LaTeX crash |
| `_check_layout_bounds` | `RIGHT*6` / `UP*4` off-frame coords |
| `_check_title_lifecycle` | `section_title()` created, never faded |
| `_check_end_cleanup` | scene doesn't end with `fade_all`/`FadeOut` |
| `_check_dim_opacity` | `set_opacity(0.3)` instead of `0.1` |
| `_check_interpolate_color` | hex string into `interpolate_color()` (render-time `AttributeError`) |
| `_check_style_import` | scene not importing the shared style contract |
| `_check_empty_waits` | `self.wait()` with no preceding animation |

Cheap additions the docs justify but the linter misses: `grep '\.add\(.*\.animate'`; `Transform(` without `Replacement`; `font_size=` below 20; `MathTex` containing a bare `%`; non-raw strings containing `\f`/`\n` inside `MathTex`; `Group(...).save_state()`; `self.wait(` with active updaters but no `frozen_frame=False`.

Then the two-phase gate from `rules/production-quality.md` §7: `python -m py_compile` on every scene (~1 s), then `manim -ql` on every scene (~30–60 s for 15 scenes) *before* any `-qh` render. This is the difference between catching runtime color/layout errors in 60 s and in 40 min.

### (d) Post-generation checkers (visual review stage)
- `scripts/audit_video.sh` extracts 5 frames per scene at 10/25/50/75/90 % — feed those JPEGs plus the 30-item checklist it prints straight into a vision-model review turn. That is your "quality review" stage, already built.
- The checklist in `audit_video.sh` and the "Verification Phase" in `rules/scene-planning.md` are both written as binary `[ ]` items → convert to a structured JSON rubric and have the reviewer return per-item pass/fail + the failing scene, so the repair loop is targeted rather than "make it better".
- Programmatic checks the vision model shouldn't have to do: bounding-box overlap between mobject groups can be computed in-process by instantiating the scene and inspecting `mob.get_bounding_box()`/`.width`, so overlap and off-frame checks can be deterministic.
- For your GIF/slide output: `rules/config-rendering.md` gives `--format gif`, `-s` (last frame as PNG for slides), and `next_section(...)` + `--save_sections` for per-beat clips.

### Usefulness ratings — for **automated** generation (not interactive use)

| File / group | Rating | Why |
|---|---|---|
| `rules/production-quality.md` | **High** | Mechanically checkable numeric thresholds; is the spec for both the linter and the vision reviewer. |
| `rules/scene-planning.md` | **High** | Enumerable templates + a ready-made copy-paste rule block + the scene-plan schema your planner should emit. |
| `src/three_b1b/audit_video.py` | **High** | Working code, not prose. Steal it. |
| `SKILL.md` gotchas + `rules/troubleshooting.md` | **High** | Directly convertible to lint rules and repair-loop hints keyed off error strings. |
| `rules/animation-design-thinking.md` (timing table) | **High** | LLMs systematically under-`wait()`; a numeric table fixes this in one paste. |
| `templates/style.py` + `scripts/safe_manim.py` | **High** | Ship as real project files; forces a stable API surface and removes whole error classes. |
| `rules/visual-design-principles.md` (17) | **Med-High** | Great as a numbered menu the planner cites by ID; too abstract to lint. |
| `rules/visual-design-catalog.md` (35 patterns) | **Med-High** | Strong retrieval corpus once the planner emits pattern IDs; 24 KB is too big for always-on. |
| `domains/*` (7) | **Med** | Good retrieval, one file per run. Content is opinionated-but-generic; audit against your own domains. |
| `audiences/*` (4) | **Med** | Useful only if your pipeline parameterises audience; the misconception-engine framing is the valuable part. |
| `rules/equations.md`, `animations.md`, `mobjects.md`, `graphs-plots.md`, `updaters-trackers.md`, `three-d.md`, `moving-camera.md`, `decorations.md`, `matrices-linalg.md` | **Med** | Competent API cheat sheets, but frontier models already know most of this; retrieval-only, and unpinned to a manim version. |
| `rules/explanation-design.md`, `pedagogy-checklist.md` | **Med** | Excellent *planner* input (they shape what to explain); useless to the code generator. |
| `rules/voiceover.md` | **Med** | High value only if you add narration; the `# NARRATION:` beat comment convention + duration math is directly reusable. |
| `rules/config-rendering.md` | **Med** | Your renderer will hardcode flags once; useful for GIF/section/transparency specifics. |
| `rules/paper-explainer.md`, `project-organization.md` | **Low-Med** | Long-form workflow prose aimed at a human driving an agent. |
| `rules/first-scene-tutorial.md` | **Low** | Beginner onboarding; strip it. |
| `rules/manimgl-differences.md` | **Low** | You will pin one flavor. Keep one line: "CE only, `from manim import *`". |
| `rules/remotion-integration.md` | **Low** | Only if you composite in Remotion. |
| `videos/**` (6 worked projects, ~60 scenes) | **High (underrated)** | The best few-shot corpus here. Retrieve the scene whose `Template:`/domain matches the one being generated. Not in the wheel — take it from the git repo. |

**Suggested concrete ingestion**: fork/vendor `src/three_b1b/skill/` into your repo, delete `first-scene-tutorial.md` / `remotion-integration.md` / `manimgl-differences.md`, pin a manim version and re-verify the API claims against it, lift `audit_video.py`'s `run_checks()` as your lint stage, ship `templates/style.py` + `scripts/safe_manim.py` into every generated project, and make the planner emit `Template:` + pattern IDs so retrieval is keyed rather than embedded.

---

## 6. License and activity

- **License:** MIT, `Copyright (c) 2026 Amit T Subhash` (`LICENSE`). `pyproject.toml` declares `license = "MIT"` with `license-files = ["LICENSE"]`. **Vendoring and modification are unrestricted** with attribution; the rule text, templates, and `audit_video.py` are all covered.
- **Activity:** 34 stars, 2 forks, 0 open issues, 1 watcher. Created 2026-03-17, last push 2026-06-27 (HEAD `fd9bf9c`, *"feat: pedagogy checklist for math exposition (Grant Sanderson, JMM 2023)"*). Not archived. Effectively a **solo project, actively developed through mid-2026, quiet since.**
- **Staleness note:** `README.md` claims "24 rule files" and "22 general patterns"; actual counts are **27 rule files** and **35 catalog patterns**. Minor, but a signal that docs drift ahead/behind the content — verify counts yourself rather than trusting the README.
- **Risk:** single maintainer, low adoption, no CI/tests for the rule content, no manim version pin. Treat it as a **document corpus to vendor**, not a dependency to install.

---

## 7. Alternatives surveyed

### `adithya-s-k/manim_skill` — **1,106 ★, 93 forks, MIT, created 2026-01-22, last push 2026-01-23**
Three skills in a proper Claude Code plugin layout (`.claude-plugin/` absent here but `skills/<name>/SKILL.md`):
- `skills/manimce-best-practices/` — 24 API rule files + 7 tested example scripts + 3 scene templates
- `skills/manimgl-best-practices/` — 19 rule files + **~70 runnable ManimGL example scenes** (attention, MLP, eigenvectors, quantum, wave optics, Lorenz…) + 8 reference walkthroughs + 4 templates
- `skills/manim-composer/` — a *planning* skill that emits a `scenes.md` scene-by-scene plan before any code
- `tests/manimce/` and `tests/manimgl/` — actual test harnesses that render the examples

Its `SKILL.md` frontmatter is notably better-engineered for auto-invocation than 3brown1blue's, with explicit trigger conditions and a negative trigger:
> `Trigger when: (1) User mentions "manim"… (2) Code contains 'from manim import *'… NOT for ManimGL/3b1b version (which uses manimlib imports and manimgl CLI).`

**Verdict: better for API correctness and few-shot examples; worse for production discipline.** It is an API reference with examples. It has **no** spatial-bounds system, no anti-overlap rules, no data-viz minimums, no density/variety audits, no post-render checklist, and no linter. Those are precisely the failure modes of LLM-written Manim.

### `Yusuke710/manim-skill` — **154 ★, 9 forks, MIT, created 2026-01-14, last push 2026-01-26**
One `SKILL.md` (5.7 KB) driving a Plan → Code → Render → Iterate loop, plus a `tools/video_viewer.py` + `ui.html` browser review UI. ManimCE only. Requires subcaptions on every scene (`add_subcaption()`) and `-ql` by default. **Verdict: thin.** The viewer tool is the only novel piece, and a headless pipeline doesn't need it. Not competitive as a knowledge source.

### `marcelo-earth/generative-manim`
A full GPT→video web app/API, not a skill pack. Interesting as prior art for the end-to-end product, not as a rules corpus.

### Also noted
There is published research on exactly this problem — *"Training and Agentic Inference Strategies for LLM-based Manim Animation Generation"* (arXiv 2604.18364) — worth reading for eval methodology if you want to measure whether these rules actually improve output. ManimML is a domain library (neural-net mobjects), not a prompt pack; its docs are only useful if you generate ML architecture diagrams and want a higher-level API than raw shapes.

### Recommendation
**Use both, for different stages.**
- `3brown1blue` for the **generation constraints and the review stage**: the spatial system, the 18-rule block, the production/post-render checklists, the timing table, `style.py`/`safe_manim.py`, and `audit_video.py`. Nothing else surveyed has these, and they are what convert plausible-looking Manim into non-overlapping, non-clipped, well-paced Manim.
- `adithya-s-k/manim_skill` for the **API reference and few-shot corpus**: its ManimCE rule files are tighter per-topic than 3brown1blue's, and its ~70 ManimGL + 7 ManimCE runnable examples are a much larger retrieval pool than 3brown1blue's 6 video projects (mind the flavor split — only use the `manimce-best-practices` half unless you target ManimGL).
- Take `manim-composer`'s `scenes.md` schema and 3brown1blue's `## Scene N` scene-plan format and pick whichever fits your planner; 3brown1blue's is stricter (declares `Template:`, `Cleanup:`, `Equations:`, `Data:`) and therefore better for machine consumption.

**Sources:**
- [AmitSubhash/3brown1blue](https://github.com/AmitSubhash/3brown1blue)
- [adithya-s-k/manim_skill](https://github.com/adithya-s-k/manim_skill)
- [Yusuke710/manim-skill](https://github.com/Yusuke710/manim-skill)
- [marcelo-earth/generative-manim](https://github.com/marcelo-earth/generative-manim)
- [Training and Agentic Inference Strategies for LLM-based Manim Animation Generation](https://awesomepapers.io/ai-agents/papers/2604.18364)
