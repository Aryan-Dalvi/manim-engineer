# LLM-to-Manim Landscape Survey

Scout report, 2026-09-14. Scope: every system that turns natural-language / document input into rendered Manim animations, plus the benchmarks that measure them. Written to position a pipeline of the form **presentation input (transcript / slides / audio / video / manuscript) → animation plan → LLM-generated Manim → quality review → GIF/slide output**.

Bottom line up front: the field has converged on *code-centric generation with a planner*, and the 2026 frontier is *how you verify the render*. Nobody ingests a talk. Nobody conditions on the presenter's own slides. Nobody ships the quality gate as a library.

---

## 1. Tool-by-tool

### 1.1 Math-To-Manim — HarleyCoops

- **URL**: https://github.com/HarleyCoops/Math-To-Manim
- **What it is**: "Ask a question. Get a visual explainer." A reasoning-chain-first CLI + MCP server + REST API that turns a math/physics question into a rendered explainer, keeping every intermediate reasoning artifact on disk.
- **Input modality**: text question only (README tagline mentions images; all documented paths are a prompt string). No transcript, slides, audio, or video.
- **Pipeline**: explicitly staged —
  `question → reverse prerequisites → curriculum → mathematics → camera plan → Manim scene → validation → render → inspect → repair`.
  Four *independent, non-interoperating* implementations of that chain ("silos"): **Mythos** (Claude CLI, six-agent charter chain), **Sol** (Codex CLI, durable resumable specialist stages), **Grok** (xAI Grok 4.6), **GLM** (Z.ai glm-5.3-flash). Run artifacts land in `runs/<silo>/<timestamp>/` with `mythos_scene.py`, `validation.json`, `manifest.json`.
- **Model/provider**: BYO logged-in CLI subscription per silo — Anthropic (Claude CLI), OpenAI (Codex CLI), xAI, Z.ai. No unified provider abstraction.
- **Quality control**: static only. In-process parse of `MathTex`/`Tex` fragments; optional `chktex`; optional deep LaTeX compile via `lualatex --halt-on-error` behind `M2M_LATEX_DEEP_CHECK`. Plus "enforce camera rules" structural validation. The `inspect → repair` step is human review of rendered evidence, not an automated visual critic.
- **Output**: Manim `.py` scene, MP4 (`--render -q l|m|h`), plus JSON reasoning artifacts. No GIF/slide-asset path documented.
- **License / activity**: MIT. 2,589 ★, created 2025-01-20, last push 2026-08-28. Active.
- **Interface**: `math-to-manim serve-mcp` (stdio or streamable-HTTP on :8643) exposing 7 tools (`m2m_create_animation`, `m2m_get_job`, `m2m_list_runs`, `m2m_get_run`, `m2m_get_artifact`, `m2m_get_scene_code`, `m2m_cinematic_charter`); `math-to-manim serve-api` REST.
- **Shortcomings**:
  1. **No visual verification.** Validation is LaTeX syntax + structural rules. Nothing checks the rendered frames for overlap, off-screen mobjects, or occlusion — the exact failure class the 2026 literature says dominates (see §3).
  2. **Four parallel forks of the same pipeline**, each locked to a different vendor's *interactive CLI subscription*. That is a hard coupling to a human-auth'd desktop tool, not an API — bad for CI, bad for batch, bad for reproducibility. The README itself flags that `serve-mcp` "internals currently dispatch through GrokService" while carrying Mythos tool names.
  3. **Math/physics prompts only**, with no ingestion of any document, deck, or recording.
  4. **No published evaluation.** No benchmark, no success-rate numbers, no comparison against TEB/MMMC — so the "validation" claim is unquantified.

### 1.2 Generative Manim + Animo — marcelo-earth (formerly 360macky)

- **URLs**: https://github.com/360macky/generative-manim (redirects to `marcelo-earth/generative-manim`) · demo https://generative-manim.vercel.app/ · product https://animo.video/ · skills https://github.com/marcelo-earth/manim-awesome-skills
- **What it is**: the oldest project in the space (2023). A suite: legacy Streamlit app, a hosted web demo, an "Animation Processing Interface" REST API, a training stack, and **Animo**, the commercial desktop product it evolved into.
- **Input modality**: plain-English prompt. Nothing else.
- **Pipeline**: essentially **single-shot prompt → Manim code → render**, with the differentiation living in a per-model custom system prompt rather than in planning. No planner agent, no storyboard, no critic. An `_generate_manim_preview` path renders stills.
- **Model/provider**: the widest matrix of anyone — GPT-5.6 Sol/Terra/Luna, GPT-4o, o1-mini, two fine-tuned GPT-3.5s (one physics-specific), Claude Sonnet 3 / 3.5 / 4.6 / 5, Opus 4.7 / 4.8, Haiku 4.5, Fable 5, Gemini 2.5 Flash/Pro, Gemini 3 Flash, Gemini 3.7 Flash, Kimi K3 / K2.7 Code, Featherless open-weight hosting, and a **LiteLLM passthrough** accepting any model string.
- **Quality control**: render-success only. Two genuinely interesting assets though:
  - a **training pipeline** SFT → DPO → GRPO over Qwen 2.5 Coder 7B / DeepSeek Coder V2 Lite / CodeLlama 7B (QLoRA 4-bit), whose stated thesis is that *"Manim is a deterministic verifier: code either renders or crashes"*, replacing a reward model;
  - an **executable benchmark** at `training/benchmarks` — frozen task suite (`core_v1.jsonl`), render-based scoring, Manim-specific structural checks, pass@k, reproducible JSONL/JSON reports, plus `benchmarks.compare` and `benchmarks.matrix`.
- **Output**: MP4 via API. Animo exports **MP4, GIF, and PNG sequences** in 16:9 / 9:16 / 1:1 — the only tool surveyed with a first-class GIF export.
- **License / activity**: Apache-2.0, 916 ★, created 2023-03-20, last push 2026-08-27. Active. **Animo is proprietary**: $49 one-time (from $149), Windows/Mac/Linux, <7 MB, BYO ChatGPT/Claude/OpenCode/Gemini-CLI subscription *or* $20/mo Animo credits; local rendering, voiceover, 3D preview, template library.
- **Shortcomings**:
  1. **No planning stage and no critique stage.** Prompt → code. Every 2026 result (Code2Video +40%, SGA +16.1% MVQS) says this is precisely the configuration that loses.
  2. **Model breadth substitutes for architecture.** 25 model entries, one prompt strategy. The README model table had already drifted out of sync with `api/routes/models.py` (issue [#94](https://github.com/marcelo-earth/generative-manim/issues/94)).
  3. **Security posture of the hosted path was weak**: command injection via `shell=True` with unsanitised `class_name` ([#92](https://github.com/marcelo-earth/generative-manim/issues/92)), path traversal via unsanitised `user_id/project_name/iteration` ([#91](https://github.com/marcelo-earth/generative-manim/issues/91)), unbounded image history for non-OpenAI engines ([#93](https://github.com/marcelo-earth/generative-manim/issues/93)). Fixed, but indicative of a thin execution sandbox.
  4. **The good part is going closed.** The evolution path is OSS repo → proprietary desktop app; Animo does not document code export from the app despite the marketing claim of "code ownership".

### 1.3 TheoremExplainAgent (TEA) + TheoremExplainBench (TEB) — TIGER-AI-Lab

- **URLs**: https://github.com/TIGER-AI-Lab/TheoremExplainAgent · https://arxiv.org/abs/2502.19400 · https://aclanthology.org/2025.acl-long.332/ · https://tiger-ai-lab.github.io/TheoremExplainAgent/ · bench https://huggingface.co/datasets/TIGER-Lab/TheoremExplainBench
- **What it is**: ACL 2025 **oral**. The paper that made "long-form Manim explainers" a research task, and the field's default baseline + evaluation harness.
- **Input modality**: a theorem statement (string). Nothing else.
- **Pipeline**: two agents. **Planner** produces a multi-scene video plan then refines per-scene visual elements / animations / transitions. **Coding agent** emits Manim per scene with **Kokoro TTS voiceover** (`kokoro-v0_19.onnx`) muxed in. **Multifaceted RAG over Manim docs**: first classifies whether the theorem warrants specific Manim *plugins* (manim-physics, manim-Chemistry, ManimML, manim-dsa are all credited), then issues retrieval queries at three distinct stages — storyboard generation, technical implementation, and error correction — with caching and relevance thresholds.
- **Repair loop**: yes. On render error the coding agent reviews the traceback and regenerates, **max 5 attempts**, then marks the generation failed.
- **Quality control**: none in-loop beyond compile/render success. All visual judgement is **post-hoc evaluation** via TEB.
- **TEB**: 240 theorems, 4 disciplines (CS, Chemistry, Math, Physics), 80 each at Easy (HS) / Medium (UG) / Hard (grad), sourced from OpenStax and LibreTexts. Five dimensions scored and combined by **geometric mean**: Accuracy & Depth (GPT-4o on transcript), Visual Relevance (GPT-4o on sampled frames), Logical Flow (GPT-4o on transcript), **Element Layout** (GPT-4o on frames, overlap/positioning), Visual Consistency (Gemini 2.0-Flash on video chunks). Human validation: 12 STEM annotators, 40 videos, Krippendorff's α. Evaluation requires a video + an SRT.
- **Headline numbers**: generation success rate — **o3-mini 93.8%**, GPT-4o 55.0%, Gemini 2.0-Flash 14.6%, **Claude 3.5 Sonnet 2.1%**. Overall quality — o3-mini and GPT-4o both ≈0.77–0.78, versus **0.77 for human-made Manim videos**. Agentic decomposition lifts video length from ~20 s (naive) to up to 10 min.
- **License / activity**: MIT, 1,500 ★, created 2025-02-16, **last push 2025-07-27 — ~14 months stale**.
- **Shortcomings**:
  1. **No visual critique inside the loop.** The VLM only ever judges the finished artifact. The repair loop repairs *tracebacks*, never *layouts* — which is why the paper's own error analysis reports "misaligned text elements, overlapping shapes, and inconsistent object sizes" surviving to the output, worsening at Medium/Hard.
  2. **Its own RAG hurts.** The paper states RAG "generally reduced success rates across models" while raising token cost and latency. A retrieval stage that makes things worse is a design smell, not a feature.
  3. **The benchmark's text metrics barely track humans**: Spearman ρ = **0.14** (Accuracy & Depth) and **0.16** (Logical Flow). So TEB scores at 0.77–0.85 across several systems are not discriminative on content.
  4. **Operationally brittle and abandoned.** Missing RAG artifacts on clone ([#30](https://github.com/TIGER-AI-Lab/TheoremExplainAgent/issues/30)), undocumented system deps ([#24](https://github.com/TIGER-AI-Lab/TheoremExplainAgent/issues/24)), render aborts on missing scenes ([#27](https://github.com/TIGER-AI-Lab/TheoremExplainAgent/issues/27)), repair loop livelock ([#21](https://github.com/TIGER-AI-Lab/TheoremExplainAgent/issues/21)), signature bug in `render_video_fix_code()` ([#26](https://github.com/TIGER-AI-Lab/TheoremExplainAgent/issues/26)). Evaluating anything requires *both* a GPT-4o and a Gemini key.
  5. **Theorem-shaped input only** — no way to feed it a talk, a deck, or a paper.

### 1.4 Code2Video — showlab (NUS), ICML 2026

- **URLs**: https://arxiv.org/abs/2510.01174 · https://github.com/showlab/Code2Video · https://showlab.github.io/Code2Video/
- **What it is**: the strongest published architecture. Three agents, and the first system to put a **VLM critic with an explicit spatial coordinate system** in the generation loop.
- **Input modality**: a topic string (e.g. "Fourier Transform"). No document, deck, or audio ingestion.
- **Pipeline**:
  - **Planner** — decomposes topic into an *outline* (per-section id, title, content summary, illustrative examples), expands to a *storyboard* (title, lecture lines, corresponding animations), and identifies required **external visual assets**, retrieved and cached in a persistent store so repeated concepts reuse identical imagery. Assets serve two roles: reference images that anchor complex concepts and suppress hallucination, and icons/logos that are hard to draw from scratch.
  - **Coder** — **parallel per-section synthesis** conditioned on the shared asset store, plus **ScopeRefine**, a three-tier debugging escalation: *line scope* (error line ±1 context, up to K₁ local fixes) → *block scope* (the lecture-line block, K₂ attempts) → *global scope* (regenerate the whole section, last resort).
  - **Critic** — a **Visual Anchor Prompt** that discretises the canvas into a **6×6 grid of anchor points mapped to fixed Manim coordinates**, plus an **occupancy table** tracking element placement so conflicts can be reallocated deterministically. It checks for: overlapping elements within a cell, lecture lines occluded by animations, and large unused regions.
- **Model/provider**: model-agnostic; evaluated with Claude Opus 4.1, GPT-4o, GPT-4.1, GPT-5, Gemini 2.5 Pro.
- **Benchmark — MMMC**: professionally produced 3Blue1Brown-style reference videos. **456 units** (117 full-length + 339 timestamped segments), 13 disciplines (Analysis, Calculus, CS, Differential Equations, Epidemics, Geometry, Group Theory, Linear Algebra, Neural Networks, Physics, Probability, Puzzles, Topology). Full videos ≈1,014 s; segments ≈201 s.
- **Metrics**: **AES**, five 20-point dimensions (Element Layout, Attractiveness, Logic Flow, Visual Consistency, Accuracy & Depth) via VLM-as-judge; code efficiency; and **TeachQuiz** — unlearn the concept from a VLM, measure quiz accuracy S₁, let it watch the generated video, measure S₂, score = S₂ − S₁. That is the best end-to-end pedagogical metric published.
- **Headline numbers**: Human 3B1B **99.7 AES / 97.1 TeachQuiz**; Code2Video+Claude **87.9 / 86.0**; Code2Video+GPT-4.1 **79.0 / 82.0**; direct code generation (Claude, no agents) **37.8 / 40.0**. "40% improvement over direct code generation."
- **Output**: silent MP4. No narration track.
- **License / activity**: MIT, **2,026 ★**, created 2025-09-29, last push 2026-08-24. Active.
- **Shortcomings** (several stated by the authors or by the SGA follow-up):
  1. **Its own critic is spatially blind.** The paper concedes LLMs/VLMs "often fail to provide actionable feedback due to limited spatial awareness" — they can *name* a problem but cannot say which direction or how far to move an element. SGA measured the consequence: the VLM critic buys **+2.5% MVQS**, against **+16.1%** for symbolic geometric checking.
  2. **Repair is unstable.** SGA reports Code2Video layouts "occasionally introduce new regressions, with frequency-domain bars displaced beyond the canvas boundary despite corrective feedback."
  3. **Expensive loop.** Every critic iteration requires a 30–90 s render pass before the VLM can look at anything.
  4. **Topic-string in, silent video out.** No audio, no narration timing, no source-document grounding, no presenter conditioning — and attractiveness / visual consistency remain the weakest AES dimensions.

### 1.5 Manimator — HyperCluster-Tech

- **URLs**: https://arxiv.org/abs/2507.14306 · https://github.com/HyperCluster-Tech/manimator · demo https://huggingface.co/spaces/HyperCluster/manimator · https://manimator.hypercluster.tech/
- **What it is**: the only system with genuine **document ingestion** as a first-class path. Killer UX detail: replace `arxiv.org` with `manimator.hypercluster.tech` in any arXiv PDF URL for an instant visualisation. 1,000+ uses in 24 h of launch, 5,000+ in a week, HF Space of the Week.
- **Input modality**: **natural-language prompt, PDF upload, or arXiv ID.** Best input coverage in the survey.
- **Pipeline**: strictly three stages, no loops. (1) Scene description — a **multimodal** model reads the PDF; output is a Markdown schema of *Topic / Key Points (with LaTeX) / Visual Elements / Style*. (2) Code generation — a code-specialised model converts the description to Manim. (3) Render.
- **Model/provider**: **Gemini 2.0 Flash** for PDF understanding, **Llama-3.3-70B** for text prompts, **DeepSeek-V3** for code (selected over Claude 3.5 Sonnet and o3 on price/performance). All swappable via **LiteLLM** env vars; prompts in `utils/system_prompts.py`, few-shots in `few_shot/few_shot_prompts.py`.
- **Quality control**: **none.** No retry loop, no critic, no static check.
- **Evaluation**: scored on TEB — Accuracy & Depth 0.77, Visual Relevance 0.899, Logical Flow 0.88, Element Layout 0.853, Visual Consistency 0.852, **Overall 0.845**; human study with engineering students gave 0.738.
- **Output**: MP4 via FastAPI (`:8000/docs` SwaggerUI) or Gradio (`:7860`); Dockerised.
- **License / activity**: MIT, 74 ★, created 2025-01-05, **last push 2025-02-14 — dead for 19 months**, despite the paper appearing five months after the last commit.
- **Shortcomings**:
  1. **Zero error recovery.** A single hallucinated method kills the run. Given that TEA measured hallucination as the majority failure mode and bespoke-manim measured a 75% invalid-render rate, a no-retry pipeline is a coin flip.
  2. **No planner beyond a flat Markdown schema** — no scene-level pacing, no narration, no dependency ordering between concepts.
  3. **Abandoned**, with the hosted Space as the only living surface — i.e. vendor dependence on a research group's free-tier hosting.
  4. **PDF-only document path.** Papers, not talks: no transcript, no slide deck, no timestamps.

### 1.6 SGA — Symbolic Geometric Agent (KAUST), 2026

- **URL**: https://arxiv.org/abs/2607.18116 (submitted 2026-07-20, revised 2026-09-10) — Jhon Lopez, Carlos Hinojosa, Bernard Ghanem
- **What it is**: the most directly useful piece of prior art for a quality-gate design. A **plug-and-play** module that intercepts LLM-generated Manim *before* rendering, instruments `construct()` with **per-statement try/except**, partially executes it (surviving runtime errors), and extracts a **symbolic scene graph** of semantic label, centroid (cx, cy), dimensions (w, h), and **source line number** — enabling **line-level edits** instead of whole-script regeneration.
- **Conflicts detected**: (1) **overlaps** — bbox intersection above ε; (2) **out-of-frame** — outside `[-W/2, W/2] × [-H/2, H/2]`; (3) **occlusions** — severity-ranked High (>30% coverage), Medium (>10%), Low, via asymmetric coverage ratios; (4) **crowding** — centroid separation relative to canvas diagonal.
- **Metric — MVQS**: Spatial Correctness (overlap penalty, canvas bounds, legibility, separation) + Composition (density/distribution over a 4×3 grid) + Pedagogy (labelling completeness, animation quality). **Deterministic, computed without rendering.**
- **Results**: plugged into Code2Video across GPT-5.1, GPT-5 mini, Claude 4.6 Sonnet, Gemini 3.0 Flash. Best **62.97 → 73.11 MVQS** (GPT-5.1), **+16.1% relative**, versus **+2.5%** for a VLM critic (62.97 → 64.54). Human raters preferred SGA **84.4%** vs baseline and **65.0%** vs the VLM critic. Symbolic detection runs in **<5 s** against a **30–90 s** render+VLM pass — **6×–18× per-iteration speedup**.
- **The finding that matters most**: **VLM-judge aesthetics scores are insensitive to geometric violations** — 10.5 points of compression across configurations where MVQS varied 14.4 points. Any pipeline whose only gate is "ask a VLM if it looks good" is measuring noise.
- **Shortcomings**: 2D Manim primitives only (3D needs camera-space projection); **no temporal checks** (a label appearing before its shape is invisible to it); MVQS itself is **not correlated against human expert annotations**; and it verifies geometry, never mathematical or pedagogical correctness — the authors warn a high MVQS "could induce automation bias."

### 1.7 ManimAgent — self-evolving multimodal agent, 2026

- **URL**: https://arxiv.org/abs/2606.30296 (2026-06-29), Wenjia Jiang et al.
- **What it is**: the memory angle. A **dual-channel Episodic Memory Bank** — **M⁺** stores successful reasoning patterns as *soft reference examples*, **M⁻** stores validated failure modes as *hard known pitfalls*. Learning happens with **no weight updates and no human seeds**.
- **Input modality**: **sections of scientific papers**.
- **Visual critique**: yes — a VLM **scores rendered keyframes**, and those signals are what populate both memory channels.
- **Evaluation**: fixed-probe protocol against three ablations — no-memory, matched-budget RAG, shuffled-memory. Metrics: **blind human Pass@1** and **reflection-round count**. Result: Pass@1 rises and reflection rounds fall as memory grows.
- **Shortcomings**: paper-section input only; code, memory snapshots, and task stream are **promised, not yet released**; the memory stores *code patterns*, not *visual identity* — it cannot learn "this presenter's diagrams look like X"; and it inherits the VLM-keyframe-scoring weakness SGA quantified.

### 1.8 ManiBench — visual-logic drift & syntactic hallucination benchmark, 2026

- **URLs**: https://arxiv.org/abs/2603.13251 (2026-02-24), Nabin Oli · dataset https://huggingface.co/datasets/nabin2004/ManiBench
- **What it is**: a failure *taxonomy* benchmark, grounded in an analysis of 3Blue1Brown's ManimGL corpus (**53,000 lines, 143 scene classes**). Four-tier evaluation: **Executability**, **Version-Conflict Error Rate**, **Alignment**, **Coverage**.
- **Two named failure modes**:
  - **Syntactic hallucinations** — valid Python referencing non-existent or deprecated Manim APIs: invented classes (`MCircle` for `Circle`), deprecated methods, wrong method signatures, and **mixing ManimGL and ManimCE syntax**.
  - **Visual-logic drift** — executable but semantically wrong: omitted critical animation steps, reversed sequential logic (results before derivations), misaligned timing breaking pedagogical flow, missing causal relationships.
- **Version catalogue**: **145 documented GL→CE incompatibilities** in 8 categories — import system, `CONFIG` dict → `__init__` params, scene type replacements (`InteractiveScene` → `Scene`), animation renames (**`ShowCreation` → `Create`**, and `ShowCreation` was subsequently *deleted*), PiCreature unavailability, 3D rendering limits, camera control differences, custom mobjects requiring reimplementation.
- **Results**: Claude-Sonnet-4 **66.7%** executability / alignment 1.00 / coverage 0.249; Kimi-K2.5 66.7% / 0.917 / 0.265; Gemini-2.5-Pro 33.3%; Qwen3.5+ 33.3%; Llama-3.1-8B 8.3%. **Mean pedagogical coverage across nine models: 0.17.** Qwen3-235B scored 25% against Sonnet-4's 67% — *scale does not help; domain data does*. No model solved the expert topology problem (Hairy Ball Theorem). Few-shot prompting was the only effective intervention (+11.1 pp on Gemma-3-27B); version-aware prompting gave perfect alignment but **no executability gain**.
- **Caveat**: the abstract claims 150–200 problems across five difficulty levels, but the results table is consistent with **12 hand-curated problems** (66.7% = 8/12). Treat the absolute numbers as indicative, the taxonomy as solid.

### 1.9 Training and Agentic Inference Strategies for LLM-based Manim Generation, 2026

- **URLs**: https://arxiv.org/abs/2604.18364 (2026-04, rev 2026-08) — Silva, Lotfi, Ihianle, Shahtahmassebi, Bird (Nottingham Trent) · code https://github.com/SuienS/manim-trainer · data https://huggingface.co/datasets/SuienR/ManimBench-v1
- **What it is**: the training-side answer. **SFT + GRPO** with a **unified reward fusing code-level and visual assessment**, plus two agentic inference strategies: **RITL** (renderer-in-the-loop self-correction) and **RITL-DOC** (RITL augmented with API documentation).
- **Scale**: **17 open-source models under 30B**, nine training × inference combinations, evaluated on ManimBench-v1 (417 description/code pairs drawn from the official ManimCE docs).
- **Results**: **Qwen 3 Coder 30B reaches 94% Render Success Rate and 85.7% Visual Similarity**, beating GPT-4.1 by 3 pp on visual similarity. SFT improves code quality; GRPO improves visual output.
- **The subtle finding**: the correlation between code metrics and visual metrics **weakens** once agentic inference is added — training and agentic strategies are **complementary, not synergistic**. i.e. a fine-tuned model still needs a separate visual gate.
- **Shortcomings**: ManimBench-v1 is doc-derived snippets, not pedagogical scenes — "visual similarity to a reference video" is a weak proxy for teaching quality; nothing about planning, narration, or multi-scene coherence.

### 1.10 PRISM — programmatic spatial-temporal reasoning benchmark, 2026

- **URL**: https://arxiv.org/abs/2605.19382 (2026-05-19), Qiran Zhang et al.
- **What it is**: the largest benchmark of the lot — **10,372 human-calibrated instruction-code pairs, 437 subject categories, English and Chinese, 20× larger than prior work**. Four metrics: Code-Level Reliability, Spatial Reasoning (layout correctness across the full sequence), Prompt-Aware Dynamic Visual Complexity (PADVC), and Temporal Density.
- **The number to quote**: the **Execution-Spatial Gap** — the average drop from execution success rate to spatial pass rate is **≈41%**. Roughly two in five programs that run produce spatially incoherent visuals.

### 1.11 Commercial / hosted products

| Product | URL | Model | Notes |
|---|---|---|---|
| **Animo** | https://animo.video/ | BYO Claude/ChatGPT/Gemini-CLI/OpenCode, or $20/mo credits | Desktop (Win/Mac/Linux), <7 MB, **$49 one-time**, local rendering, **MP4 + GIF + PNG sequence**, 16:9/9:16/1:1, voiceover, 3D preview, template library. Proprietary. The evolution of Generative Manim. |
| **Generative Manim (hosted)** | https://generative-manim.vercel.app/ | 25-model matrix | Free web demo of the OSS repo. Single-shot. Has been down historically ([#35](https://github.com/marcelo-earth/generative-manim/issues/35)). |
| **manimator (hosted)** | https://huggingface.co/spaces/HyperCluster/manimator, https://manimator.hypercluster.tech/ | Gemini 2.0 Flash + Llama-3.3-70B + DeepSeek-V3 | arXiv-URL-swap trick. Upstream repo dead since Feb 2025. |
| **AnimG** | https://animg.app/en | undisclosed | Browser-based generator + online editor; no install. |
| **ManimAI** | https://peerlist.io/itshp/project/manimai | undisclosed | Web, prompt → script → view. |
| **GateKeep AI** | — | undisclosed | STEM tutoring platform using animated explanations; animation is a means, not the product. |
| **MotionShark** | — | undisclosed | AI math/science visualisation generator. |
| **Manimate** | https://www.manimate.ai/ | Claude Code | Productised front for the `Yusuke710/manim-skill` workflow. |
| **Manim Video Generator** | https://github.com/rohitg00/manim-video-generator | OpenAI GPT | OSS web app, NL → Manim code → render. |

Common shortcomings across the commercial tier: **no planning stage exposed, no visual QC, no library API, no evaluation, prompt-only input, and no way to condition on a user's existing visual material.** Animo's local-render + BYO-subscription model is the best answer to cost/lock-in; its weakness is that it is a closed desktop GUI with no programmatic surface for a pipeline to call.

### 1.12 Agent skills

| Skill | URL | Notes |
|---|---|---|
| **Hermes `manim-video`** | https://github.com/NousResearch/hermes-agent/tree/main/skills/creative/manim-video | MIT. The most **style-opinionated** artifact in the space. Pipeline `PLAN → CODE → RENDER → STITCH → AUDIO → REVIEW`, writing `plan.md` (narrative arc, scene list, palette, voiceover script) before any code. Ships four named palettes (Classic 3B1B `#1C1C1C`/`#58C4DD`/`#83C167`/`#FFFF00`, Warm academic, Neon tech, Monochrome), a **run_time + `self.wait()` table per animation context** (e.g. "aha moment reveal" 2.5 s + 3.0 s wait), a typography scale (Title 48 / Heading 36 / Body 30 / Label 24 / Caption 20), an **opacity-layering rule** (primary 1.0, contextual 0.4, structural 0.15), a monospace-font rule because "Manim's Pango renderer produces broken kerning", and a **7-mode table** (concept explainer / equation derivation / algorithm visualization / data story / **architecture diagram** / paper explainer / 3D). Optional TTS via ElevenLabs or Qwen3-TTS. |
| **`Yusuke710/manim-skill`** | https://github.com/Yusuke710/manim-skill | MIT, 154 ★, pushed 2026-01-26. Claude Code plugin: Plan → Code → Render → **Iterate**, where iterate = open an HTML **video viewer** in the browser and paste human feedback back into Claude Code. Productised as manimate.ai. |
| **`awesome-skills/manim-skill`** | https://github.com/awesome-skills/manim-skill | v1.5.0, 6 ★. A ManimCE syntax/best-practice reference (v0.19+ uses pyav, no external ffmpeg; "always use ManimCE unless reproducing exact 3B1B videos"). |
| **`marcelo-earth/manim-awesome-skills`** | https://github.com/marcelo-earth/manim-awesome-skills | 2 ★, June 2026. Curated Manim agent skills. |
| **manim-composer** | https://awesomeskill.ai/skill/adithya-s-k-manim-skill-manim-composer | Turns vague video ideas into scene-by-scene plans *before* code; companion skills do ManimCE/ManimGL codegen. |

**Shortcomings of the skill tier**: Hermes explicitly declares *"First-render excellence is non-negotiable… without revision rounds"* — a style contract standing in for a verification loop. `REVIEW` means "render preview stills, verify against plan" by eye. None has an automated gate, a benchmark, a library API, or any input beyond a prompt. But the **style knowledge is the best in the field** and is exactly the kind of asset a multi-style system should compile rather than reinvent.

### 1.13 Manim MCP servers

| Repo | ★ | License | Last push | What it does |
|---|---|---|---|---|
| https://github.com/abhiemj/manim-mcp-server | 641 | MIT | 2025-05-19 | The de-facto standard. Executes submitted Manim code, returns the rendered video. Thin executor. 13 open issues. |
| https://github.com/wstcpyt/manim-mcp | 19 | Apache-2.0 | 2025-05-05 | Docker environment + CLI + web API + MCP. |
| https://github.com/qingpengchen2011/manim-mcp | 0 | none | 2025-10-22 | HTTP API server + stdio MCP for Claude Desktop / Dify. |
| https://github.com/ameymn/manim_mcp_server | 0 | none | 2026-01-23 | Exposes Manim capabilities as MCP tools. |
| https://github.com/gorav22/animated_video | — | — | — | Executes Manim code, returns video. |
| `math-to-manim serve-mcp` | (in 1.1) | MIT | 2026-08-28 | The only MCP server exposing a **reasoning pipeline** (7 tools incl. job progress, artifacts, cinematic charter) rather than a bare renderer. |

**Shortcomings**: every standalone Manim MCP server is a **remote `exec()`** — take code, run `manim`, return MP4. No planning, no validation, no repair, no sandbox hardening worth the name, no layout checking. They solve "the model can't run Manim", not "the model can't write good Manim". Most are ~1-year stale.

### 1.14 Datasets worth knowing

- **bespokelabs/bespoke-manim** — https://huggingface.co/datasets/bespokelabs/bespoke-manim — 1,000 synthetic (question, animation script, Manim code) triples generated with Claude-Sonnet-3.7 thinking via Curator. **"Around 25% of the Manim snippets generate valid videos, mostly due to incorrect code being generated for the given script, sometimes due to hallucination in function names and calls."** The single most citable number for the raw hallucination problem.
- **SuienR/ManimBench-v1** — 417 description↔code pairs from the ManimCE docs (basic/intermediate/advanced).
- **TIGER-Lab/TheoremExplainBench** — 240 theorems (see §1.3).
- **nabin2004/ManiBench** — plus a published prompt-engineering guide of version-conflict fixes.
- **BibbyResearch/3blue1brown-manim** — 3B1B source corpus.

### 1.15 Adjacent, non-Manim, but directly relevant to our input side

- **Speech-Synchronized Whiteboard Generation via VLM-Driven Structured Drawing Representations** — https://arxiv.org/abs/2603.25870 (2026-03-26). 24 paired Excalidraw demonstrations with narrated audio, every element carrying **millisecond-precision creation timestamps**, 8 STEM domains; Qwen2-VL-7B + LoRA predicts stroke sequences synchronised to speech. Finding: **timestamp conditioning significantly improves temporal alignment.** This is the only work that treats "the speech is the clock" as a learnable signal — and it does not use Manim.
- **Generative Lecture** — https://arxiv.org/abs/2512.21796. Analyses lecture slides *and* transcripts, identifies which transcript spans correspond to which content blocks, generates bounding boxes with the relevant excerpts. Slide+transcript alignment done properly — and then it makes an interactive document, **not an animation**.
- **PASS** — https://arxiv.org/abs/2501.06497 — presentation automation for slide generation and speech.
- **Tomar606/manim-video-solution-generator** — https://github.com/Tomar606/manim-video-solution-generator (1 ★, Aug 2026). Tiny, but the only repo found that implements the pattern we want: *"The presenter's recorded audio is fixed and cannot be changed, so **everything else conforms to it**. Word-level timings come out of the clip first, and every caption, every reveal and every animation cue is placed against them."* Whisper word timings → caption + animation cue placement → Manim render → **gate** → chroma-key composite with presenter. Also documents the real-world integration tax: Manim 0.18 pins old numpy, Whisper wants new numpy, so **three separate virtualenvs**.
- **VideoAgent: Self-Improving Video Generation** — https://arxiv.org/abs/2410.10076 — pixel-space, robotics, not Manim. ("Video-Gen-Agent" and "VideoAgentTrek" returned no matching work; the closest hits are this and VideoGen-Eval https://arxiv.org/abs/2503.23452.)
- **ManimCommunity/manim-voiceover** — https://github.com/ManimCommunity/manim-voiceover — official plugin; **per-word animation triggering against a recording using OpenAI Whisper**. The production-ready primitive for presenter-audio-conditioned timing.

---

## 2. A. Comparison table

| Tool | Input modalities | Planning stage | Iterative repair | Visual / VLM critique | Style knowledge (skills/RAG) | Output | Library API | Benchmark |
|---|---|---|---|---|---|---|---|---|
| **Math-To-Manim** | prompt | ✅ 6-stage reasoning chain (prereq tree → curriculum → math → camera plan) | ⚠️ human-in-loop "inspect → repair" | ❌ | ⚠️ "cinematic charter" per silo | MP4 + scene.py + JSON artifacts | ✅ CLI + **MCP (7 tools)** + REST | ❌ |
| **Generative Manim** | prompt | ❌ | ❌ | ❌ | ⚠️ per-model system prompts | MP4 (REST) | ✅ REST "API" | ✅ own `core_v1` render-scored, pass@k |
| **Animo** (commercial) | prompt | ⚠️ implicit | ❌ | ⚠️ live preview (human) | ✅ template library | **MP4 / GIF / PNG seq**, 3 aspect ratios | ❌ GUI only | ❌ |
| **TheoremExplainAgent** | theorem string | ✅ planner agent, multi-scene | ✅ traceback repair, max 5 | ❌ in-loop (post-hoc only) | ✅ **RAG over Manim docs + plugin routing** | MP4 + **Kokoro TTS voiceover** + SRT | ⚠️ research scripts | ✅ **TEB** (240 theorems, 5 dims) |
| **Code2Video** | topic string | ✅ outline → storyboard → asset retrieval | ✅ **ScopeRefine** line→block→global | ✅ **VLM + 6×6 anchor grid + occupancy table** | ✅ cached external asset store | silent MP4 | ⚠️ research scripts | ✅ **MMMC** (456 units) + AES + **TeachQuiz** |
| **Manimator** | **prompt / PDF / arXiv ID** | ✅ Markdown scene schema | ❌ | ❌ | ⚠️ few-shot prompts | MP4 (FastAPI + Gradio) | ✅ FastAPI + Docker | ✅ scored on TEB (0.845) |
| **SGA** | (plug-in) | n/a | ✅ **line-level symbolic edits** | ✅ **symbolic scene graph, no render needed** | ❌ | n/a | ⚠️ research plug-in | ✅ **MVQS** |
| **ManimAgent** | paper sections | ✅ | ✅ reflection rounds | ✅ VLM keyframe scoring | ✅ **episodic memory M⁺/M⁻** | MP4 | ❌ unreleased | ⚠️ fixed-probe, human Pass@1 |
| **Hermes `manim-video`** | prompt | ✅ `plan.md` narrative arc | ❌ (explicitly "no revision rounds") | ❌ (human stills review) | ✅✅ **palettes, timing tables, typography, opacity, 7 modes** | MP4 + optional TTS + ffmpeg stitch | ❌ skill file | ❌ |
| **`Yusuke710/manim-skill`** | prompt | ✅ Claude plan mode | ✅ renders until success | ⚠️ **human** via browser video viewer | ⚠️ | MP4 | ❌ skill/plugin | ❌ |
| **Manim MCP servers** | Manim code | ❌ | ❌ | ❌ | ❌ | MP4 | ✅ MCP (execute only) | ❌ |
| **manim-trainer (SFT+GRPO)** | prompt | ❌ | ✅ **RITL / RITL-DOC** | ✅ visual reward in GRPO | ✅ API docs in RITL-DOC | MP4 | ✅ training toolkit | ✅ ManimBench-v1 |
| **ManiBench / PRISM** | (benchmarks) | — | — | — | — | — | — | ✅ ManiBench 4-tier / PRISM 4-metric, 10,372 pairs |
| **← our target** | **transcript / slides / audio / video / manuscript** | ✅ + **salience triage** | ✅ scoped | ✅ **symbolic + VLM + source-grounded** | ✅ multi-style + presenter deck | **GIF + slide bundle** | ✅ typed Python API | ✅ talk-level bench |

Legend: ✅ present · ⚠️ partial/manual · ❌ absent.

---

## 3. B. Recurring failure modes of LLM-generated Manim

**1. Hallucinated Manim APIs (syntactic hallucination).** The dominant crash cause. TEA's error analysis puts it first: *"nonexistent functions, modules, object properties, or image assets, as well as incorrect function signatures with invalid parameter types and numbers."* ManiBench formalises it: invented classes (`MCircle` for `Circle`), deprecated methods, wrong signatures. Bespoke Labs measured the blast radius: **only ~25% of Claude-Sonnet-3.7-generated snippets render at all**, "mostly due to incorrect code… sometimes due to hallucination in function names and calls."
Sources: https://arxiv.org/html/2502.19400v1 · https://arxiv.org/html/2603.13251v1 · https://huggingface.co/datasets/bespokelabs/bespoke-manim

**2. ManimGL ↔ ManimCE version drift.** ManiBench catalogues **145 GL→CE incompatibilities** across 8 categories: imports, `CONFIG` dict → `__init__` params, `InteractiveScene` → `Scene`, **`ShowCreation` → `Create`** (subsequently *deleted*, so old code fails with `no attribute`), PiCreature unavailability, 3D limits, camera control, custom mobjects. Models trained on 3B1B's ManimGL corpus emit GL idioms into CE runtimes. Manim CE's own changelog confirms the deletion; installing manimgl overwrites the `manim` executable. Also hits parameters that never existed in the target version (`rounded_corners`/`corner_radius` on `Rectangle`).
Sources: https://arxiv.org/html/2603.13251v1 · https://docs.manim.community/en/latest/changelog/0.7.0-changelog.html · https://huggingface.co/datasets/nabin2004/ManiBench/blob/main/ManiBench_Prompt_Engineering_Guide.md

**3. LaTeX rendering errors.** TEA's second-ranked failure category: *"syntax mistakes and improper handling of special characters in mathematical expressions."* These fail at render time inside a subprocess, so the traceback is often opaque. Math-To-Manim is the only surveyed tool that pre-compiles LaTeX fragments (`chktex`, `lualatex --halt-on-error`) as a gate.
Sources: https://arxiv.org/html/2502.19400v1 · https://github.com/HarleyCoops/Math-To-Manim

**4. Element overlap and occlusion.** Universal, and it survives every text-only repair loop. TEA: *"misaligned text elements, overlapping shapes, and inconsistent object sizes,"* worsening at Medium/Hard difficulty. Code2Video's Critic exists specifically to catch *"overlapping elements within a cell, lecture lines occluded by animations."* SGA grades occlusion severity High (>30% coverage) / Medium (>10%) and reports raw Code2Video output showing *"label-equation collisions and occluded annotations."*
Sources: https://arxiv.org/html/2502.19400v1 · https://arxiv.org/pdf/2510.01174 · https://arxiv.org/html/2607.18116v1

**5. Objects placed off-screen / out of viewport.** SGA: elements outside `[-W/2, W/2] × [-H/2, H/2]`. Its analysis of Code2Video without feedback finds *"severe spatial failures including elements rendered outside the viewport,"* and — the damning part — *"resulting layouts remain unstable and occasionally introduce new regressions, with frequency-domain bars displaced beyond the canvas boundary **despite corrective feedback**."*
Sources: https://arxiv.org/html/2607.18116v1 · https://arxiv.org/pdf/2510.01174

**6. The execution–spatial gap: code that runs but is visually wrong.** PRISM quantifies it across 10,372 pairs: **the average drop from execution success rate to spatial pass rate is ≈41%.** Render success is not a quality signal — which invalidates the "Manim is a deterministic verifier, code either renders or crashes" reward design used in Generative Manim's GRPO stage as a *sufficient* signal.
Sources: https://arxiv.org/pdf/2605.19382 · https://github.com/marcelo-earth/generative-manim

**7. Pacing, timing, and visual-logic drift.** ManiBench's second named mode: *"omitting critical animation steps, reversing sequential logic (e.g., showing results before derivations), misaligned timing breaking pedagogical flow, missing causal relationships."* The Hermes skill's entire prescriptive timing table exists as a hand-written countermeasure: *"Every animation needs `self.wait()` after it… Never rush from one animation to the next. A 2-second pause after a key reveal is never wasted."* SGA explicitly declines to fix this class: it *"does not address synchronization issues (label timing relative to shape animations)."*
Sources: https://arxiv.org/html/2603.13251v1 · https://github.com/NousResearch/hermes-agent/tree/main/skills/creative/manim-video · https://arxiv.org/html/2607.18116v1

**8. Pedagogical shallowness — technically fine, teaches nothing.** ManiBench's **mean coverage across nine models is 0.17**; the authors conclude *"LLM-generated Manim code lacks pedagogical richness."* Code2Video's gap to humans is the same story quantified: **99.7 AES / 97.1 TeachQuiz for 3Blue1Brown vs 87.9 / 86.0** for the best agentic system, with professionals still ahead on *"storytelling, nuanced sequencing, and explanatory depth."*
Sources: https://arxiv.org/html/2603.13251v1 · https://arxiv.org/pdf/2510.01174

**9. (Meta-failure) The graders are broken.** Worth treating as a failure mode because it silently blesses the other eight. SGA: **VLM-judge aesthetics scores are insensitive to geometric violations** — 10.5 points of score compression where MVQS varied 14.4 points; a VLM critic buys +2.5% MVQS against SGA's +16.1%. Code2Video concedes VLMs *"struggle to provide actionable corrections or indicate the direction or distance needed to adjust elements."* TEB's text metrics correlate with humans at **ρ = 0.14 / 0.16**. ManiBench found alignment scores >0.90 *"despite low executability,"* i.e. keyword heuristics detect concept presence, not correctness. And SGA's own MVQS *"lacks correlation with human expert annotations."*
Sources: https://arxiv.org/html/2607.18116v1 · https://arxiv.org/pdf/2510.01174 · https://arxiv.org/html/2502.19400v1 · https://arxiv.org/html/2603.13251v1

---

## 4. C. Gaps — what nobody does yet

### G1. Nobody ingests a talk, and nobody decides *which* concepts deserve an animation

Every system in §1 takes a **single short unit of content**: a topic string (Code2Video, Generative Manim, Animo, all skills), a theorem (TEA), or a paper PDF/section (Manimator, ManimAgent). The unit *is* the video. There is no notion of a 45-minute recording containing, say, six moments worth animating and forty that are not.

Nothing implements **animation-worthiness triage**: scoring transcript spans for visual payoff (a mechanism to show vs a list to read), deduplicating concepts that recur, respecting a budget ("give me four 10-second GIFs"), and ordering by dependency. The closest artifacts are Generative Lecture (slide↔transcript span alignment, but outputs a document) and commercial explainer tools like Agent Opus that "identify key concepts and visual opportunities" from a script — neither produces Manim, neither works from a recording, neither exposes the triage decision for review.

**Our move**: make the *animation plan* a first-class, reviewable artifact — a ranked list of `(transcript span, concept, why it's visual, proposed style, estimated duration, confidence)` — produced before a single line of Manim exists, and editable by the presenter.

### G2. Nobody conditions on the presenter's own slides

Not one system reads the deck. Manimator reads a paper PDF for *content*; nothing reads a PPTX/PDF deck for **visual identity and notation**: the palette actually used, the font, the symbol conventions (is it `\mathbf{x}` or `\vec{x}`? is the loss `\mathcal{L}` or `L`?), axis labelling habits, the box-and-arrow topology already drawn on slide 14, the acronyms defined on slide 3.

Style knowledge today is *generic and hard-coded* — Hermes ships four fixed palettes; Code2Video caches retrieved stock assets; ManimAgent remembers *code patterns*, not visual identity. An animation that contradicts the deck it sits inside is worse than no animation.

**Our move**: compile the deck into a **style contract + notation glossary** (palette tokens, type scale, symbol table, existing diagram topology) and inject it as a constraint into both planning and codegen — and check compliance in the gate.

### G3. Single-style monoculture: everything is 3Blue1Brown

Every tool targets equation-heavy math aesthetics. Hermes lists "architecture diagram" as one of seven modes but gives it no distinct layout machinery. Code2Video's 6×6 anchor grid and SGA's 4×3 composition grid are **style-agnostic** — they measure "don't overlap, don't crowd," which is right for a math scene and badly wrong for a systems diagram, where the quality criteria are *edge crossings, orthogonal routing, label attachment, layer alignment, and legend consistency*.

Nobody has a **style router** with per-style layout solvers and per-style critics: equation derivation vs box-and-arrow architecture vs data story vs algorithm trace vs geometric construction. That matters enormously for conference talks, where most animation-worthy moments are *architectures and data flows*, not integrals.

**Our move**: styles as pluggable modules, each with (a) a scene grammar, (b) a layout constraint set, (c) its own gate checks. A DAG-layout pass (rank assignment, edge routing) for box-diagram style is a solved graph-drawing problem that no Manim agent has bothered to wire in.

### G4. Automated quality gates exist only as research plug-ins or post-hoc leaderboards

The verification landscape is bimodal and both halves are unusable as infrastructure:
- **Post-hoc benchmarks** — TEB, MMMC/AES/TeachQuiz, ManiBench, ManimBench-v1, PRISM/MVQS — measure systems, not individual artifacts, and require a video + SRT + two frontier API keys.
- **In-loop critics** — Code2Video's VLM critic (spatially blind, +2.5%), SGA (symbolic, +16.1%, but 2D-only, no temporal checks, no factual checks, single-paper plug-in).

Nobody ships a **layered gate as a library** with independent pass/fail thresholds and repair scoped to the failing layer:
1. **static** — AST lint against the *installed* Manim CE version's real symbol table (kills failure modes 1 and 2 for near-zero cost — and note ManiBench found version-aware *prompting* gave perfect alignment but **zero executability gain**, so this must be a *checker*, not a prompt);
2. **LaTeX precompile** — `chktex` + `lualatex --halt-on-error` per fragment (mode 3), the one thing Math-To-Manim already does right;
3. **symbolic geometry** — SGA-style partial execution → scene graph → overlap / out-of-frame / occlusion / crowding, **<5 s, no render** (modes 4, 5, 6);
4. **temporal** — the check SGA explicitly skips: does every label appear after its referent, is every reveal followed by a `wait`, does per-scene duration match the plan's budget (mode 7);
5. **render + VLM** — last and cheapest-to-skip, for aesthetics only, never as the sole gate;
6. **source-grounded factuality** — see G5.

And repair should be **line-scoped like SGA, escalating like ScopeRefine** — the two best repair ideas in the literature have never been combined.

### G5. Nobody checks the animation against what the speaker actually said

This is the biggest unclaimed safety/quality gap. TEB and AES judge pedagogy *in the abstract* — "is this a good explanation?" — never *fidelity to the source*. TEA's own limitations section warns that *"AI-generated explanations have the potential to mislead users if errors go undetected"* and could *"propagate misconceptions."* SGA is blunter: it guarantees geometric integrity but *"not mathematical or pedagogical accuracy — factual errors remain invisible,"* and warns that a high MVQS *"could induce automation bias."*

When the input is a *specific person's talk*, fidelity is checkable and is the whole ballgame: every claim, label, number, and symbol in the animation should be entailed by the cited transcript span. That is a tractable NLI/citation-check problem, and it is a gate nobody has.

**Our move**: every plan node carries a transcript citation; the gate verifies entailment of on-screen text against that span and flags unsupported additions for presenter review.

### G6. Presenter-friendly output is an afterthought

Output across the field is a standalone MP4 meant to *be* the video. Only Animo exports GIF/PNG sequences, and only as file-format options.

Nobody produces a **slide-ready asset bundle**: loopable GIF/WebM with the loop point chosen so it doesn't jar, transparent or deck-background-matched backdrop, sized and cropped to a specific slide placeholder, captionless (the speaker narrates live) with an optional captioned variant, a poster-frame PNG for print handouts, a `reveal.js`/PPTX/Keynote drop-in snippet, plus provenance metadata linking back to the source timestamp. Nobody offers *"here are the 6 GIFs for your deck, at slides 4, 9, 14, 21, 26, 33."*

Practical note from the one repo doing presenter-conditioned work (Tomar606): the presenter's recorded audio must be treated as **fixed — everything conforms to it**, using Whisper word-level timings. `manim-voiceover` already supports per-word animation triggering against a recording, and the whiteboard paper (2603.25870) shows timestamp conditioning measurably improves temporal alignment. The primitives exist; no pipeline assembles them.

### G7. No importable library API with a typed, reviewable plan object

TEA and Code2Video are research scripts with `PYTHONPATH` rituals. Generative Manim is a REST service. Animo is a GUI. The MCP servers are remote `exec()`. Math-To-Manim comes closest (CLI + MCP + REST + on-disk artifacts) but forks the whole pipeline four ways per vendor CLI.

Nobody offers `plan = engineer.plan(transcript, slides); plan.nodes[2].style = "box_diagram"; artifacts = engineer.render(plan)` — a typed plan object that can be *inspected, diffed, edited, approved, and re-rendered incrementally*. Without it, the human is either fully out of the loop (Hermes, Animo, Code2Video) or reduced to pasting feedback into a chat window (`Yusuke710/manim-skill`).

Related sub-gap: **no incremental re-render**. Code2Video regenerates whole sections on global-scope failure. Nothing caches per-plan-node keyed by a content hash, so editing one scene re-does the video.

### G8. No benchmark for the task we're actually doing

TEB = theorems. MMMC = topic strings vs 3B1B references. ManiBench / ManimBench-v1 / PRISM = code-level. There is **no benchmark of real recorded talks with human-marked animation-worthy moments** — no dataset, no metric for "did it pick the right six moments," no measure of deck-style compliance or source fidelity. Building even a small one (30 talks, expert-marked spans, presenter style contracts) would be a genuine contribution and would make our own gates measurable rather than asserted.

**Adjacent precedent to borrow from**: the whiteboard paper built a usable result from **24 demonstrations** with millisecond timestamps (https://arxiv.org/abs/2603.25870). This is not a 10,000-example problem.

---

## 5. Positioning summary

Three things the literature already settled, which we should take for free rather than rediscover:

1. **Code-centric generation with a planner beats single-shot**, by ~40% (Code2Video 87.9 vs 37.8 AES). Do not build a prompt→code tool.
2. **Symbolic geometric verification beats VLM critique**, by 6× on quality gain and 6–18× on speed (SGA +16.1% / <5 s vs VLM +2.5% / 30–90 s). The gate should be deterministic-first, VLM-last.
3. **Render success is not quality** — the execution–spatial gap is ≈41% (PRISM), and the best model still only renders 67% of curated tasks first-pass (ManiBench). Budget for repair as a normal path, not an exception.

And the defensible ground nobody occupies: **talk-in** (G1), **deck-conditioned style** (G2, G3), **layered gate with source-grounded fidelity** (G4, G5), **slide-ready GIF bundle** (G6), **as a library** (G7).

---

## Appendix: all sources

**Repos**
- https://github.com/HarleyCoops/Math-To-Manim (MIT, 2589★, pushed 2026-08-28)
- https://github.com/360macky/generative-manim → https://github.com/marcelo-earth/generative-manim (Apache-2.0, 916★, pushed 2026-08-27)
- https://github.com/TIGER-AI-Lab/TheoremExplainAgent (MIT, 1500★, pushed 2025-07-27)
- https://github.com/showlab/Code2Video (MIT, 2026★, pushed 2026-08-24)
- https://github.com/HyperCluster-Tech/manimator (MIT, 74★, pushed 2025-02-14)
- https://github.com/SuienS/manim-trainer (21★, pushed 2026-04-21)
- https://github.com/NousResearch/hermes-agent/tree/main/skills/creative/manim-video (MIT)
- https://github.com/Yusuke710/manim-skill (MIT, 154★, pushed 2026-01-26)
- https://github.com/awesome-skills/manim-skill · https://github.com/marcelo-earth/manim-awesome-skills
- https://github.com/abhiemj/manim-mcp-server (MIT, 641★) · https://github.com/wstcpyt/manim-mcp (Apache-2.0, 19★) · https://github.com/qingpengchen2011/manim-mcp · https://github.com/ameymn/manim_mcp_server · https://github.com/gorav22/animated_video
- https://github.com/ManojINaik/manimAnimationAgent (MIT, 12★) · https://github.com/rohitg00/manim-video-generator · https://github.com/Tomar606/manim-video-solution-generator
- https://github.com/ManimCommunity/manim-voiceover · https://github.com/MtCelesteMa/manim-speech · https://github.com/ManimCommunity/DiscordManimator

**Papers**
- TheoremExplainAgent — https://arxiv.org/abs/2502.19400 · https://arxiv.org/html/2502.19400v1 · https://aclanthology.org/2025.acl-long.332/
- Manimator — https://arxiv.org/abs/2507.14306 · https://arxiv.org/html/2507.14306v1
- Code2Video — https://arxiv.org/abs/2510.01174 · https://arxiv.org/pdf/2510.01174 · https://showlab.github.io/Code2Video/
- SGA — https://arxiv.org/abs/2607.18116 · https://arxiv.org/html/2607.18116v1
- ManimAgent — https://arxiv.org/abs/2606.30296
- ManiBench — https://arxiv.org/abs/2603.13251 · https://arxiv.org/html/2603.13251v1
- Training & Agentic Inference for Manim — https://arxiv.org/abs/2604.18364
- PRISM — https://arxiv.org/abs/2605.19382
- Speech-Synchronized Whiteboard — https://arxiv.org/abs/2603.25870
- Generative Lecture — https://arxiv.org/abs/2512.21796 · PASS — https://arxiv.org/abs/2501.06497
- VideoAgent — https://arxiv.org/abs/2410.10076 · VideoGen-Eval — https://arxiv.org/abs/2503.23452

**Datasets**
- https://huggingface.co/datasets/TIGER-Lab/TheoremExplainBench
- https://huggingface.co/datasets/bespokelabs/bespoke-manim
- https://huggingface.co/datasets/SuienR/ManimBench-v1
- https://huggingface.co/datasets/nabin2004/ManiBench
- https://huggingface.co/datasets/BibbyResearch/3blue1brown-manim

**Products**
- https://animo.video/ · https://animo.video/ai-manim-tools · https://generative-manim.vercel.app/ · https://animg.app/en · https://www.manimate.ai/ · https://huggingface.co/spaces/HyperCluster/manimator · https://manimator.hypercluster.tech/ · https://peerlist.io/itshp/project/manimai

**Docs**
- https://docs.manim.community/en/latest/changelog/0.7.0-changelog.html (ShowCreation deletion)
- https://docs.manim.community/en/stable/faq/general.html
- https://huggingface.co/datasets/nabin2004/ManiBench/blob/main/ManiBench_Prompt_Engineering_Guide.md
