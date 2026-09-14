# Ingestion & Animation Planning — Research Report

Scope: the front half of the pipeline (INPUT → concept extraction → ANIMATION PLAN). Everything below is
sourced; where a claim is inference or design proposal rather than a cited finding, it is marked
**[design]**. Date of research: 2026-09-14.

---

## 0. Executive summary (the 10 things that actually matter)

1. **Use one normalized internal document model for every modality.** Every adapter must emit the same
   `Segment` record with a `SourceSpan` (modality + timestamps *or* slide index *or* paragraph id). Without
   this, per-slide/per-timestamp attribution of an animation is impossible to retrofit.
2. **faster-whisper is the default ASR** (MIT, CTranslate2, `word_timestamps=True`, built-in Silero VAD,
   ~4× reference Whisper, large-v2 fp16 on GPU ≈ 1m03s for 13 min audio vs 2m23s for openai-whisper).
   For live mode, wrap it in the **LocalAgreement-2** policy from `ufal/whisper_streaming` (≈3.3 s average
   latency on an A40).
3. **YouTube is the most operationally fragile input in 2026.** `youtube-transcript-api` soft-caps around
   100–200 requests/hour/IP and datacenter IPs get blocked (including via Webshare proxies).
   `yt-dlp --write-auto-subs --sub-format vtt` is more robust; avoid `json3`/`srv*`/`ttml` (documented
   `_UnsafeExtensionError` bugs). Always have "download audio → local ASR" as the fallback path.
4. **PPTX beats PDF for slides** because `python-pptx` gives you slide index, shape tree, and speaker
   notes natively. PDF slides lose all of that; `PyMuPDF` `page.get_text("dict")` + `page.get_pixmap(dpi=)`
   recovers text-with-bbox and a page raster, and page number *is* the slide index (1:1 for slide exports).
5. **For papers: marker for equation-bearing PDFs, pymupdf4llm for speed, LaTeX source whenever it exists.**
   arXiv e-print LaTeX is strictly best — it *is* the ground-truth equation. Nougat converts every formula
   to LaTeX but is arXiv-overfit and ~10× slower than marker.
6. **The prior art converges on a two-level plan**: a coarse *outline/storyboard* (one node per concept/scene)
   and a fine *implementation plan* (per-beat: what appears, what transforms, where, narration line).
   TheoremExplainAgent, Code2Video, Manimator, and ManimAgent all independently landed on this shape.
7. **The dominant failure mode is spatial, not syntactic.** PRISM measures an average **41 percentage-point
   drop** from "code executes" to "layout is valid across all frames". Your plan schema must therefore carry
   *explicit layout intent* (region anchors), not just semantic intent.
8. **Complexity is the strongest predictor of failure.** PRISM: samples in the top quintile of text expansion
   drop to **36.6%** spatial pass; high dynamic-complexity samples fail spatially **68%** of the time. So the
   plan schema needs hard budgets (`on_screen_text_budget`, `max_concurrent_mobjects`, `duration_s`) that the
   planner is *required* to respect.
9. **Bucket maturity** (the owner's idea) is sound and has close prior art: TreeSeg-style divisive clustering
   over embeddings gives you the boundary signal; the "enough content" trigger is a scored predicate over
   (mass, cohesion, boundary evidence, archetype-evidence, staleness). See §5.
10. **Sub-3-minute concept→GIF is achievable only with archetype templates + a warm render pool.** Free-form
    LLM Manim code at PRISM-level reliability will blow the budget on repair loops. Parameterized templates
    for the 12 archetypes convert most of the problem from code generation into JSON filling.

---

## 1. Ingestion adapters

### 1.0 The normalized model (design, but load-bearing)

**[design]** Every adapter emits:

```python
@dataclass
class SourceSpan:
    modality: Literal["audio","video","slides","manuscript","live"]
    doc_id: str                      # stable hash of the artifact
    # exactly one of these groups is populated:
    t_start_s: float | None = None   # audio/video/live
    t_end_s: float | None = None
    slide_index: int | None = None   # slides (1-based, == PDF page for slide exports)
    shape_ids: list[str] | None = None
    para_id: str | None = None       # manuscript: "sec2.p4" / "eq:3"
    char_start: int | None = None
    char_end: int | None = None

@dataclass
class Segment:
    seg_id: str
    text: str
    span: SourceSpan
    speaker: str | None
    kind: Literal["speech","slide_text","slide_notes","body","equation","caption","code"]
    confidence: float
    assets: list[str]                # paths to page rasters / crops / figure images
```

Rationale: the animation plan later needs to say *"this animation explains slide 14 / 08:32–09:10"*.
If attribution is not captured at ingestion, it cannot be recovered — MaViLS shows post-hoc
video↔slide alignment tops out around **0.82** accuracy even with a multimodal (speech+OCR+image)
algorithm, versus 0.56 for SIFT-only ([arXiv:2409.16765](https://arxiv.org/html/2409.16765)). Capture it
up front; only fall back to alignment when you truly have unsynchronized sources.

### 1.1 Audio → timestamped transcript

| Option | Offline | GPU | Key | Word timestamps | Notes |
|---|---|---|---|---|---|
| **faster-whisper** | yes | optional (CUDA 12 + cuDNN 9; int8 on CPU) | no | `word_timestamps=True` | CTranslate2 backend, MIT. Bundles Silero VAD (`vad_filter=True`), `BatchedInferencePipeline`. PyAV bundles FFmpeg so no system ffmpeg needed. Python ≥3.9. **No Apple Metal** — CPU-only on Mac. |
| **whisper.cpp** | yes | Apple Metal / CPU (GGML) | no | yes (attention-derived) | The right choice on Apple silicon and for tiny-footprint edge boxes; slower than faster-whisper on NVIDIA. |
| **WhisperX** | yes | yes | HF token only if diarizing | yes, forced-aligned | VAD → cut&merge into ~30 s chunks on low-energy boundaries → batched Whisper → wav2vec2 phoneme forced alignment. Up to **70× realtime**; word-timing precision **93.2%** vs Whisper's 85.4%. Use this for *batch* when timestamps must be tight. |
| **OpenAI `/audio/transcriptions`** | no | n/a | yes | **only `whisper-1`** | 25 MB file cap (size, not duration). `gpt-4o-transcribe` is more accurate (~4.1% WER vs 5.3%) at $0.006/min but **does not support `timestamp_granularities[]`** or verbose_json/SRT/VTT. So: `whisper-1` when you need word timings from the API. |
| **Deepgram** (Nova-3 / Flux) | no | n/a | yes | yes | Streaming WebSocket. `interim_results=true`, `endpointing` (default 10 ms of silence), `utterance_end_ms=1000` (requires `interim_results=true`). Batch ≈ $0.0043/min. Best end-of-speech latency class. |
| **AssemblyAI** (Universal-3/3.5 Pro Streaming) | no | n/a | yes | yes | `wss://streaming.assemblyai.com/v3/ws`, `Turn` objects with `end_of_turn` flag, neural end-of-turn ≈300 ms; presets `max_accuracy` / `min_latency` / `balanced`. ~$0.45/hr streaming; streaming diarization +$0.12/hr. |
| **pyannote 3.1** (diarization only) | yes | 6–8 GB VRAM is plenty | HF gated token | n/a | 16 kHz mono, auto-resample/downmix. Only needed for panel/Q&A talks. |

**Recommendation.** Batch: `faster-whisper large-v3` (or WhisperX if you want phoneme-accurate word times for
narration bookmarking). Live: a hosted streaming API (Deepgram or AssemblyAI) if latency dominates, else
`whisper_streaming` + faster-whisper.

**Live chunked pattern.** Don't roll your own emission policy. `ufal/whisper_streaming`
([arXiv:2307.14743](https://arxiv.org/html/2307.14743)) uses **LocalAgreement-n**: run Whisper on an overlapping
growing buffer, and *confirm* only the longest common prefix that agrees across `n` consecutive updates
(n=2 in practice). This gives stable, append-only confirmed text — which is exactly what an incremental
bucketing system needs, because confirmed tokens never get rewritten under you. Reported ≈**3.3 s** average
latency for English on an A40. Buffer is trimmed at confirmed sentence boundaries to bound cost.

**[design] Contract for live ASR output:** the adapter must emit `(confirmed_text_delta, t_start, t_end)` and
separately an unstable `hypothesis_tail`. The planner only ever consumes `confirmed` text; the UI may show the tail.

### 1.2 YouTube

Two paths, both needed:

**Path A — captions (cheap, fragile).**
- `youtube-transcript-api`: simplest, gives `{text, start, duration}` per cue. Empirically soft-limited
  around **100–200 requests/hour/IP**; datacenter IPs get hard-blocked. Issue
  [jdepoix/youtube-transcript-api#511](https://github.com/jdepoix/youtube-transcript-api/issues/511) documents
  "YouTube is blocking requests from your IP" *even with Webshare residential proxies*. Treat it as
  best-effort, never as a dependency.
- `yt-dlp --write-subs --write-auto-subs --sub-langs en --sub-format vtt --skip-download`: more robust
  (handles cookies, proxies, client rotation). **Use `vtt` or `--convert-subs srt`.** `json3`, `ttml`,
  `srv1/2/3` have documented `_UnsafeExtensionError` bugs and should not be used in production.
  Known gotchas: HTTP 429 on subtitle downloads ([yt-dlp#13831](https://github.com/yt-dlp/yt-dlp/issues/13831));
  spurious `>>` markers in auto-captions ([yt-dlp#14530](https://github.com/yt-dlp/yt-dlp/issues/14530)) —
  strip them. Empty subtitle output with no error is almost always upstream rate limiting, not a bug.
- 2025–26 landscape: YouTube is forcing **SABR** streaming and increasingly requires **PO tokens**; even valid
  premium cookies don't always get you formats ([yt-dlp#14390](https://github.com/yt-dlp/yt-dlp/issues/14390)).
  Cookies from a real signed-in session help *marginally* and eventually invalidate.

**Path B — audio + local ASR (expensive, reliable).**
`yt-dlp -f bestaudio -x --audio-format wav` → faster-whisper. This is the fallback whenever Path A returns
nothing, returns <N cues, or 429s. Also the *only* path that gives you a transcript for talks with no captions.

**[design] Operational rules:** per-IP token bucket; exponential backoff on 429; cache every transcript by
video id forever (they don't change); keep `yt-dlp` pinned but auto-upgradeable (extractors break weekly);
never parallelize more than ~2 requests per egress IP.

**Caption timestamps are cue-level, not word-level**, and auto-captions have no punctuation-reliable sentence
boundaries. If your segmenter needs sentences, run a punctuation/sentence restorer or prefer Path B.

### 1.3 Slides

**PPTX — `python-pptx` (best).** Gives you, per slide:
- `presentation.slides` — index is the slide number (0-based; add 1 for display).
- `slide.shapes` — shape tree; `shape.has_text_frame`, `shape.text_frame.paragraphs`, tables
  (`shape.has_table`), pictures (`shape.image.blob`), and `shape.shape_id` for stable per-shape ids.
- `slide.notes_slide.notes_text_frame.text` — **speaker notes**. This is the single highest-value signal in
  the whole slide modality: it is the author's own narration, in prose, already scoped to one slide.
- Ordering: `shape.top`/`shape.left` give reading order for free.

**PDF — `PyMuPDF` (pymupdf).**
- `page.get_text("dict")` → nested `blocks → lines → spans`, each with `bbox`, font, size, color. Blocks are
  either image or text-paragraph. Font size is a usable heuristic for title vs body on slides.
- `page.get_pixmap(dpi=150)` → the page raster you hand to a VLM for figure/diagram understanding.
- `page.number + 1` **is** the slide index for a slide export. Store both.
- `pdfplumber` is an alternative for text-only with good word/char geometry; slower, no image rendering.
- What's lost vs PPTX: notes, shape semantics, animation build steps. A "slide" with builds becomes N pages.

**Google Slides.** Two options: (a) Drive `files.export` to `application/pdf` or
`application/vnd.openxmlformats-officedocument.presentationml.presentation` (PPTX) — then use the PPTX path,
which preserves notes; (b) Slides API `presentations.get` for structured `slides[].pageElements[]` plus
`slides[].slideProperties.notesPage` for notes, and `presentations.pages.getThumbnail` for per-slide PNGs.
Requires OAuth or a service account with domain access. Caveat: exports drop transitions, slide animations,
and embedded A/V. **Prefer export-to-PPTX** — fewer API calls, one code path, notes preserved.

**[design] Slide-index alignment invariant.** Define `slide_index` as *the 1-based ordinal of the slide in the
delivered deck*. Every adapter must produce it:
- PPTX → enumerate order.
- PDF export → page number (assert page_count == slide_count when both are available).
- Google Slides → `objectId` mapped to ordinal, and persist the `objectId` too (it survives reordering).
Then `AnimationPlan.source_spans[].slide_index` is directly renderable as "Slide 14" in the review UI, and the
generated GIF can be dropped back into the deck at that position.

**Aligning transcript to slides.** If you have both a deck and a talk recording, build the mapping once at
ingestion:
1. Detect slide changes in video with **PySceneDetect** `ContentDetector` (HSV mean frame delta,
   `--threshold 27` is the documented starting point) or `detect-adaptive` / `detect-hash` /`detect-hist`.
   Caveats from the literature: picture-in-picture speaker insets, camera switching, and *slide builds*
   all confuse frame differencing.
2. OCR each keyframe, match to deck slides. MaViLS reports OCR features contribute most to matching accuracy,
   then image features, with speech transcript useful when OCR is weak; their multimodal algorithm hits
   **0.82** vs SIFT **0.56** and is ~11× faster ([arXiv:2409.16765](https://arxiv.org/html/2409.16765)).
3. Store the resulting `slide_index ↔ [t_start, t_end]` table once; all downstream spans join through it.

### 1.4 Manuscripts / papers

| Input | Tool | Equation fidelity | Notes |
|---|---|---|---|
| **arXiv LaTeX e-print** | `arxiv` + tar extract, `pylatexenc.latexwalker` | **perfect** (it *is* LaTeX) | Always try this first for arXiv ids. `unarXive` ([arXiv:2303.14957](https://arxiv.org/pdf/2303.14957)) is the reference design: preserves section/subsection structure and links in-text positions of math, figures, tables, citations. `latexwalker` gives you a node tree so you can pull `\begin{equation}` bodies verbatim with their labels. |
| **Markdown** | direct | perfect if `$...$`/`$$...$$` | Trivially the best input. Parse with a CommonMark parser that leaves math spans intact; use heading hierarchy as `para_id` prefix. |
| **PDF (born-digital, text-heavy)** | `pymupdf4llm` | poor-to-fair — symbols survive but not as LaTeX | Fastest by a wide margin, no ML models. Good default when the doc has no display math. |
| **PDF (academic, equations matter)** | **`marker` (marker-pdf)** | **best open-source in practice** | ~10× faster than nougat and more accurate outside arXiv (nougat is arXiv-trained). Marker detects equations then converts, so it converts *fewer* equations than nougat but hallucinates far less. Reported ~10.5/12 on a controlled equation-extraction benchmark vs Docling's 5/12. |
| **PDF, formula-max recall** | `nougat` | converts *all* formulas to LaTeX | arXiv-overfit, slow, prone to repetition loops on out-of-distribution layouts. Use only as a second opinion on equation regions. |
| **PDF, structure + tables** | `docling` (v2.117.x, 2026) | VLM pipeline ≈90% on equations | Two pipelines: fast default (specialist table models) and a VLM pipeline on **Granite-Docling-258M** (Apache-2.0) emitting DocTags. ~6.2 s/page on MLX; slower than marker on the same doc (marker ~47 s for a 6-page PDF on M5 Pro, >2× faster than Docling VLM). |

**Ranking for equation preservation: LaTeX source > nougat (recall) ≈ marker (precision) > docling VLM >
pymupdf4llm.** In practice **marker** is the right default for PDFs, with LaTeX-source short-circuit for arXiv.

**[design]** Store equations as first-class `Segment`s with `kind="equation"`, the raw LaTeX, the label
(`eq:3`), and the surrounding paragraph ids. The equation-derivation archetype (§4.1) consumes these directly
and this is the single highest-value ingestion output for a Manim pipeline.

### 1.5 Video of a talk: frames+OCR vs audio only

- **Audio alone gets you ~90% of the planning value** and costs one ASR pass. Speech is where the explanation
  lives.
- **Frames buy you three things audio can't**: (a) the equations and diagrams actually shown, (b) slide-change
  events that are excellent segmentation boundaries, (c) grounding for "as you can see here" deixis.
- **Recommended hybrid [design]:** keyframe-only, not dense sampling.
  1. `PySceneDetect` `ContentDetector`/`AdaptiveDetector` → slide-change timestamps.
  2. One frame per detected segment (plus a 1-frame-per-30 s floor so long static slides still get sampled).
  3. Run OCR *and* a VLM caption on each keyframe; cheap because N is small (a 60-min talk with 40 slides →
     ~40–120 frames).
  4. Emit `Segment(kind="slide_text", span.slide_index=<matched>, span.t_start=...)`.
- Dense frame sampling + OCR on every second is a waste; the marginal information rate of a lecture video is
  bounded by the slide change rate.

---

## 2. Segmentation and "concept worth animating" detection

### 2.1 Classical / unsupervised topic segmentation

- **TextTiling** (Hearst 1997) is still the backbone: score adjacent-block lexical/semantic similarity, find
  local minima, cut there. Every modern unsupervised method is a variant.
- **BertSeg / "Unsupervised Topic Segmentation of Meetings with BERT Embeddings"**
  ([arXiv:2106.12978](https://arxiv.org/html/2106.12978v1)): TextTiling with utterance embeddings instead of
  lexical overlap; overlapping blocks of embeddings aggregated to compute utterance similarity. Reported
  gains on ICSI/AMI. This is the cheapest thing that works on ASR output.
- **TreeSeg** ([arXiv:2407.12028](https://arxiv.org/pdf/2407.12028)): off-the-shelf embeddings + **divisive
  clustering**, producing a **binary tree** of segmentations rather than a flat cut list. Key advantage for
  this project: you don't have to commit to a segment count — you pick a depth in the tree per use. Designed
  for noisy ASR, evaluated on ICSI, AMI, and a new TinyRec corpus of manually annotated self-recorded sessions;
  outperforms baselines on ICSI/AMI.
- **Cross-segment BERT**: binary boundary classification over `[CLS] left_context [SEP] right_context`.
  Supervised, needs labels, but the strongest flat-segmentation family.
- **PODTILE** ([arXiv:2410.16148](https://arxiv.org/pdf/2410.16148)): production podcast chaptering — an
  encoder-decoder that generates chapter boundaries *and titles* jointly, with global episode context
  prepended so local chunks know where they sit. The "generate the title with the boundary" trick is worth
  copying: a chapter you cannot title is usually not a real chapter.
- **Multi-level segmentation** (Interspeech 2025,
  [Freisinger et al.](https://www.isca-archive.org/interspeech_2025/freisinger25_interspeech.pdf)): LoRA
  fine-tuning for table-of-contents generation; uses a TextTiling+sentence-embedding variant as the
  unsupervised baseline. Confirms the hierarchical framing (§2.3).

### 2.2 LLM-based chunk classification with rolling windows

Reported practice in lecture/curriculum pipelines
([arXiv:2501.12300](https://arxiv.org/pdf/2501.12300) and similar): transcribe with Whisper, then prompt an
LLM to emit *typed artifacts* per window — structured summaries with `topic`, `description`,
`key_concepts`, `key_equations`, and a lecture-type classification. The important design details that recur:

- **Overlapping windows** (e.g. 512-token chunks with ~100-token overlap, snapped to sentence/line breaks)
  so a concept straddling a boundary is seen whole at least once.
- **Schema-constrained extraction** with explicit "extract only what is explicitly supported" instructions —
  concept-extraction hallucination is well documented
  ([arXiv:2312.07110](https://arxiv.org/pdf/2312.07110): "LLMs Perform Poorly at Concept Extraction in
  Cyber-security Research Literature").
- **Coarse granularity beats fine**: 2–5 substantive items per window, not one per utterance.

**[design] Recommended hybrid (cheap signal → expensive judgement):**
1. **Tier 0 (every ~20 s of new confirmed text, ~free):** embed each new sentence; maintain a running
   cohesion score against the active bucket centroid. Cohesion drop = candidate boundary.
2. **Tier 1 (every 60–90 s, one small-model call):** classify the newly arrived window — `{is_new_concept,
   concept_name, concept_kind, has_equation, has_algorithm, has_architecture, has_comparison,
   references_slide, salience_1_5}`. Cheap model, strict JSON schema.
3. **Tier 2 (only when a bucket is judged mature):** the full planner call that emits the ANIMATION PLAN.

This keeps per-minute cost near-constant and puts the expensive reasoning only where it pays.

### 2.3 Bucket maturity — making "enough content" concrete

The owner's framing (bucket paragraphs into candidate animations, fire when a bucket is mature) is right.
Make it a scored predicate rather than a single threshold. **[design]**

```
mature(bucket) ⟺  mass_ok(b) AND (boundary_evidence(b) OR stale(b)) AND archetype_confident(b) AND NOT duplicate(b)
```

Signals, each cheap:

| Signal | Definition | Why |
|---|---|---|
| `mass` | confirmed tokens in bucket, and # distinct content sentences | A 2-sentence aside can't carry a 20 s animation. Practical floor: ~120 words / ~45 s of speech. |
| `cohesion` | mean cosine of member sentences to bucket centroid | Low cohesion = you've merged two concepts; split before planning. |
| `boundary_evidence` | TextTiling/BertSeg local minimum at the bucket's right edge, **or** a slide-change event, **or** a cue phrase | Slide changes are near-perfect boundaries when a deck exists — use them as hard priors. |
| `archetype_confidence` | max score over the archetype classifier (§4) | If nothing scores well, there's nothing to animate. This is the real "worth animating" test. |
| `concreteness` | presence of an equation, an algorithm, a named architecture, a numeric comparison, or a geometric object | Abstract motivational prose animates badly. This filter alone kills most false positives. |
| `stale` | no sentence has joined in the last K ticks (K≈3, i.e. ~3–4 min) | Forces emission so live mode never silently starves. |
| `duplicate` | cosine to any already-emitted concept fingerprint > τ (≈0.88) | Speakers repeat. Dedup or you'll render the same GIF three times. |
| `explicit cue` | "the key idea is", "let me draw", "intuitively", "consider the case where", "the algorithm works like this" | High-precision triggers; worth a hand-written lexicon. |

**Priority queue, not a boolean.** Score every mature bucket and render highest first — in live mode you are
throughput-bound, and a talk produces more animatable concepts than you can render.

### 2.4 Prior-art planning schemas (verbatim fields where available)

**TheoremExplainAgent** ([arXiv:2502.19400](https://arxiv.org/html/2502.19400v1), ACL 2025 oral;
[repo](https://github.com/TIGER-AI-Lab/TheoremExplainAgent)) — planner agent + coding agent, targeting >5 min videos.

- Pipeline: *plugin detection* (classify whether the theorem warrants a specific Manim plugin) → **Scene
  Outline** → per-scene **Implementation Plan** → code → TTS → render.
- **Scene Plan fields:** `Scene Title` (2–5 words), `Scene Purpose` (objective + connection to prior scenes),
  `Scene Description` (detailed content), `Scene Layout` (spatial positioning with **safe margins and spacing
  constraints**).
- Repair: on error, the coding agent reviews the traceback and regenerates; **max 5 retries (N=5)**.
- **TheoremExplainBench**: 240 theorems, 5 metrics — *Accuracy & Depth*, *Visual Relevance*, *Logical Flow*,
  *Element Layout*, *Visual Consistency*; overall = **geometric mean** (so any single-dimension collapse tanks
  the score — a good property to copy). o3-mini agent: **93.8% success rate, 0.77 overall**.
- **Failure taxonomy (majority first):** Manim code hallucinations (nonexistent functions/modules/properties,
  wrong signatures, invalid param types) > LaTeX rendering errors > general coding errors (missing imports,
  undefined vars, NumPy mistakes). Plus persistent minor layout problems: misaligned text, overlapping shapes,
  inconsistent sizes.
- Prompts are plain text with `{topic}`, `{description}`, `{implementation_plan}`, `{manim_code}`,
  `{error_message}` placeholders — **no structured/XML schema**. This is a weakness worth fixing (§3).

**Code2Video** ([arXiv:2510.01174](https://arxiv.org/abs/2510.01174), ICML 2026;
[repo](https://github.com/showlab/Code2Video)) — tri-agent Planner / Coder / Critic.

- **Storyboard fields per section:** `"title"`, `"lecture lines"` (narration), `"animations"` (visual sequence
  paired to each lecture line). The 1:1 pairing of *lecture line* ↔ *animation* is the cleanest "beat"
  abstraction in the literature — copy it.
- **External assets:** prompt `P_asset` reads the storyboard and names needed assets; retrieval from Google
  Images (CLIP-filtered) and Iconfinder; persistent cache `D_asset` for cross-scene temporal consistency.
- **ScopeRefine** auto-fix, hierarchical: *line scope* (error line ± context, up to K₁ attempts) → *block
  scope* (the lecture-line block, up to K₂) → *global scope* (regenerate the section from storyboard).
  Explicitly to minimize tokens and latency.
- **Critic / visual anchor prompt `P_vis`:** discretize the canvas into a **6×6 grid of anchor points** with
  fixed Manim coordinates. Point-level anchors for small elements (symbols, labels); region-level bounding
  boxes spanning multiple anchors for large ones. An **occupancy table** tracks each element's assigned
  anchors, scaling factor, and corresponding code lines, enabling conflict-free reallocation.
- **TeachQuiz:** `TQ(K,V) = S₂(K,V) − S₁(K)` where S₁ is a VLM's accuracy after concept unlearning and S₂ its
  accuracy after watching the generated video. Isolates video-induced learning.
- Results: **+40% over direct code generation**; MMMC benchmark of 117 3Blue1Brown-inspired topics; human
  aesthetics **80.3** for generated vs **99.7** for professional tutorials.
- Failure modes: asset retrieval returning unusable items (e.g. entirely black images); humans are highly
  sensitive to **even brief occlusions** while VideoLLMs miss frame-level issues; attractiveness and visual
  consistency remain below human baselines. Models used: Claude-4-Opus (code), Gemini-2.5-Pro (layout VLM).

**Manimator** ([arXiv:2507.14306](https://arxiv.org/html/2507.14306v1)) — research paper → animation.
Intermediate **Scene Description** is *Markdown*, with fields `Topic`, `Key Points` (including LaTeX
expressions), `Visual Elements`, `Style`. PDF ingested by base64ing into a long-context multimodal model
(Gemini 2.0 Flash); code by DeepSeek-V3. Limitations acknowledged: no iterative refinement from user feedback,
weak on intricate visual detail and pedagogical flow.

**ManimAgent** ([arXiv:2606.30296](https://arxiv.org/html/2606.30296v1)) — six agents: Storyboarder, Coder,
Reviewer (text-only crash diagnosis), Renderer (sandbox + static safety checks), VLM Reviewer, Visual Reviser.
- Task is typed: `τ = (s, r, d)` = section text, **scene role** ∈ {background, method, experiment, conclusion},
  **domain tag** ∈ {CS, math, physics, economics, quantum}.
- Each **scene spec `σᵢ`** carries: *scene name*, *the claim to be conveyed*, *the evidence to use*, *the final
  takeaway*. (Claim/evidence/takeaway is a genuinely good pedagogical triple — copy it.)
- Two reflection loops: **text-reflection** (crash → full regeneration of the `Scene` subclass, bounded at
  2 retries, short-circuit on repeated error category) and **visual-reflection** (VLM scores keyframes on
  *logical flow*, *layout/occlusion*, *accuracy*, each 0–100; terminate at ≥90, or 2 iterations).
- Results: human Pass@1 **84.9%** with experience memory vs **68.5%** VLM-only; reflection rounds drop
  **12.2 → 6.5**; quality 3.26 → 3.88 on a 1–5 scale. **Caution: VLM–human correlation r = −0.17** and human
  inter-rater κ = −0.01 on usability — i.e. *automatic visual review is not yet trustworthy as a gate*.

**"See Before You Code"** ([arXiv:2605.15585](https://arxiv.org/pdf/2605.15585)) — inserts an explicit
**layout plan** (object positions, sizes, types, spatial relationships, animation sequence/timing) between
prompt and code, to fix overlap, off-screen placement, spatial-reasoning failure, and temporal conflicts
(objects animated before initialization). *(Numbers from this PDF were extracted via a lossy fetch; treat the
specific failure-rate figures as indicative only. The architectural claim — a layout plan as a first-class
intermediate — is corroborated independently by Code2Video's anchor grid and TheoremExplainAgent's
`Scene Layout` field.)*

**LLM2Manim** ([arXiv:2604.05266](https://arxiv.org/html/2604.05266)) — human-in-the-loop, explicitly
grounded in multimedia learning principles (**segmentation, signaling, dual coding**). Three stabilizers worth
stealing: **constrained prompt templates**, a **symbol ledger** (consistent notation across scenes), and
**regenerate only the erroring parts**. Controlled study: 83% vs 78% post-test, d=0.67 vs PowerPoint.

**PRISM** ([arXiv:2605.19382](https://arxiv.org/html/2605.19382)) — 10,372 human-calibrated instruction↔Manim
code pairs, 437 subject categories, EN+ZH. Four funnel metrics: **Code-Level Reliability** (execution rate +
six failure types + mean render time), **Spatial Reasoning** (a sample passes only if *every frame* satisfies
all checks), **PADVC** (prompt-aware dynamic visual complexity), **Temporal Density**. The headline finding is
the **Execution–Spatial Gap: ~41 percentage points** average drop from "runs" to "looks right", across all
models. See §4.13 for the per-archetype implications.

**ManimTrainer/agentic inference** ([arXiv:2604.18364](https://arxiv.org/html/2604.18364)) — SFT+GRPO over 17
open models ≤30B on ManimBench (417 samples). Best: Qwen3-Coder-30B + GRPO + **RITL-DOC** (3 iterations) →
**85.7% visual similarity, 94% render success**, beating GPT-4.1 by +3.8 pp on visual quality.
**RITL** = renderer-in-the-loop: feed the last 10 lines of the error log back for up to K rounds.
**RITL-DOC** additionally retrieves API docs *for the functions the generated code actually calls* — no vector
store needed. Key result: **inference-time strategies gave larger gains than fine-tuning alone.** 7–8B is the
efficiency sweet spot (SeedCoder-8B, 72% render success under GRPO).

---

## 3. Proposed ANIMATION PLAN schema

Design goals: (a) reviewable by a human in <30 s; (b) directly attributable to source; (c) carries enough
*layout* intent to survive the Execution–Spatial Gap; (d) enforces complexity budgets; (e) each beat is
independently renderable and repairable.

```jsonc
{
  "schema_version": "1.0",
  "plan_id": "plan_01J8…",                   // ULID; stable across revisions
  "concept": {
    "concept_id": "c_attention_scaling",     // slug, stable, used for dedup + filenames
    "title": "Why attention divides by √d_k",// ≤ 60 chars, human-facing
    "one_line": "Dot products grow with dimension, so softmax saturates; scaling keeps variance ≈ 1.",
    "claim": "…", "evidence": "…", "takeaway": "…",   // ManimAgent's pedagogical triple
    "prerequisites": ["dot product", "softmax"],
    "fingerprint": [0.013, …]                // embedding, for duplicate suppression
  },
  "provenance": {
    "source_spans": [
      {"modality":"live","doc_id":"talk_2026_09_14","t_start_s":1712.4,"t_end_s":1789.0},
      {"modality":"slides","doc_id":"deck_v3","slide_index":14,"shape_ids":["12","15"]},
      {"modality":"manuscript","doc_id":"arxiv:1706.03762","para_id":"sec3.2.1.p2","char_start":880,"char_end":1420}
    ],
    "quotes": ["We suspect that for large values of d_k, the dot products grow large in magnitude…"],
    "equations": [{"label":"eq:attn","latex":"\\mathrm{softmax}\\!\\left(\\frac{QK^\\top}{\\sqrt{d_k}}\\right)V"}]
  },
  "audience": {
    "level": "grad",                         // enum: k12 | undergrad | grad | expert | mixed
    "assumed_known": ["matrix multiplication", "softmax"],
    "jargon_policy": "define_on_first_use"   // enum: avoid | define_on_first_use | assume
  },
  "archetype": {
    "primary": "equation_derivation",        // enum from §4
    "secondary": "plot_parameter_sweep",     // optional, at most one
    "confidence": 0.86,
    "rejected": [{"id":"architecture_diagram","reason":"no components named"}]
  },
  "budgets": {
    "target_duration_s": 22,                 // hard ceiling 45 for live mode
    "max_beats": 6,
    "on_screen_text_chars": 180,             // total simultaneous, NOT cumulative
    "max_concurrent_mobjects": 12,
    "max_simultaneous_animations": 3,
    "allow_3d": false,
    "allow_external_assets": false           // live mode: false (no network in render path)
  },
  "layout": {
    "canvas": "16:9",
    "grid": "6x6",                           // Code2Video anchor grid
    "regions": [
      {"name":"title",  "anchors":["r0c0","r0c5"], "role":"persistent_header"},
      {"name":"main",   "anchors":["r1c0","r4c5"], "role":"primary"},
      {"name":"sidebar","anchors":["r1c4","r4c5"], "role":"annotation"}
    ],
    "safe_margin_units": 0.5,                // Manim units from frame edge
    "min_gap_units": 0.3
  },
  "symbol_ledger": [                          // LLM2Manim: notation consistency across beats & plans
    {"symbol":"Q","latex":"Q","meaning":"query matrix","color":"#58C4DD","first_beat":1},
    {"symbol":"d_k","latex":"d_k","meaning":"key dimension","color":"#FFFF00","first_beat":2}
  ],
  "beats": [
    {
      "beat_id": 1,
      "purpose": "Establish the unscaled dot-product form.",
      "appears": [
        {"ref":"eq_raw","kind":"MathTex","content":"QK^\\top","region":"main","scale":1.2}
      ],
      "transforms": [],
      "disappears": [],
      "emphasis": [],
      "narration": "Attention starts with raw dot products between queries and keys.",
      "duration_s": 3.5,
      "wait_after_s": 0.4
    },
    {
      "beat_id": 2,
      "purpose": "Show that variance grows with d_k.",
      "appears": [
        {"ref":"var_note","kind":"Tex","content":"\\mathrm{Var}\\approx d_k","region":"sidebar","scale":0.8}
      ],
      "transforms": [
        {"from":"eq_raw","to":"eq_scaled","how":"TransformMatchingTex",
         "key_map":{"QK^\\top":"\\frac{QK^\\top}{\\sqrt{d_k}}"}}
      ],
      "emphasis": [{"ref":"eq_scaled","how":"Indicate","target_part":"\\sqrt{d_k}"}],
      "narration": "As the key dimension grows, so does the variance of those dot products.",
      "duration_s": 5.0,
      "wait_after_s": 0.6
    }
  ],
  "assets": [
    {"asset_id":"fig_softmax","kind":"image","source":"slides:deck_v3#p14:img0",
     "local_path":"assets/deck_v3_p14_img0.png","required":true}
  ],
  "style": {
    "theme": "dark",
    "palette": {"primary":"#58C4DD","accent":"#FFFF00","muted":"#888888"},
    "font_scale": 1.0,
    "math_font": "default",
    "pacing": "measured",                    // brisk | measured | slow
    "camera": "static"                       // static | pan | zoom | orbit(3d only)
  },
  "review": {
    "success_criteria": [
      {"id":"renders",       "check":"automatic", "assert":"manim exits 0, gif exists, frames > 0"},
      {"id":"no_overlap",    "check":"automatic", "assert":"no two labelled mobject bboxes overlap >5% on any sampled frame"},
      {"id":"in_frame",      "check":"automatic", "assert":"all mobject bboxes within safe margin on every sampled frame"},
      {"id":"text_budget",   "check":"automatic", "assert":"max simultaneous on-screen chars <= budgets.on_screen_text_chars"},
      {"id":"duration",      "check":"automatic", "assert":"abs(actual - target_duration_s) <= 0.25 * target"},
      {"id":"latex_matches", "check":"automatic", "assert":"every beat MathTex string appears in provenance.equations or symbol_ledger"},
      {"id":"claim_shown",   "check":"vlm",       "assert":"final frame visually supports concept.claim"},
      {"id":"legible",       "check":"vlm",       "assert":"all text readable at 480p; no element clipped"},
      {"id":"faithful",      "check":"human",     "assert":"no assertion beyond provenance.quotes"}
    ],
    "blocking": ["renders","in_frame","latex_matches","faithful"],
    "max_repair_rounds": 2
  },
  "meta": {
    "created_at":"2026-09-14T10:22:31Z", "planner_model":"…", "priority": 0.82,
    "status":"planned"   // planned|coding|rendering|review|accepted|rejected
  }
}
```

### Field-by-field justification

| Field | Why it exists |
|---|---|
| `concept.concept_id` + `fingerprint` | Dedup in live mode (speakers repeat); stable filenames; lets a later revision update rather than duplicate a GIF. |
| `claim / evidence / takeaway` | ManimAgent's scene spec triple. Forces the planner to commit to *one* assertion per animation — the single best guard against sprawling 6-idea scenes. |
| `provenance.source_spans[]` | The whole reason for §1's unified model. Enables "attribute this GIF to slide 14 / 28:32". Multiple spans because a concept legitimately spans speech + slide + paper. |
| `provenance.quotes` / `equations` | Grounding. The reviewer's `faithful` criterion is checkable only against verbatim source. Also feeds `MathTex` directly so the LLM never retypes an equation from memory. |
| `audience.level` / `assumed_known` | Changes beat count, whether to define terms on screen, and pacing. Codifying it means the same concept can be re-planned for a different audience without re-ingesting. |
| `archetype.primary` + `rejected` | Selects the code template (§4). Logging *rejected* archetypes with reasons makes the classifier debuggable and gives the human reviewer a one-click "no, it's a plot" override. |
| `budgets.*` | Directly targets PRISM's finding that complexity predicts spatial failure: top-quintile text expansion → 36.6% spatial pass; high dynamic complexity → 68% spatial failure. Budgets are the enforcement point, and `on_screen_text_chars` is deliberately *simultaneous*, not cumulative, since occlusion is a frame-level property. |
| `budgets.allow_external_assets` | Code2Video's asset retriever occasionally returns unusable items (all-black images). Live mode should hard-disable network asset fetch. |
| `layout.grid` / `regions` / `safe_margin_units` | Code2Video's 6×6 anchor grid + occupancy table, and TheoremExplainAgent's `Scene Layout` with explicit safe margins. Layout intent must be in the plan, not discovered by the coder — this is the highest-leverage field in the schema. |
| `symbol_ledger` | LLM2Manim. Guarantees `d_k` is the same colour and glyph in beat 2 and in a different plan 10 minutes later. Also gives `TransformMatchingTex` a reliable `key_map`. |
| `beats[]` | Code2Video's `lecture lines ↔ animations` pairing. Each beat is an independently renderable, independently repairable unit — enabling ScopeRefine-style *line/block/global* repair scoping. |
| `beats[].appears / transforms / disappears / emphasis` | Separating these four verbs maps 1:1 onto Manim's animation families (`Create`/`FadeIn`, `Transform*`, `FadeOut`/`Uncreate`, `Indicate`/`Circumscribe`/`Flash`) and prevents the "object animated before it exists" temporal bug that See-Before-You-Code calls out. |
| `beats[].ref` ids | Stable handles let the Critic rewrite one element's region without regenerating the scene, and let the automatic overlap checker name the offender. |
| `beats[].narration` | One line per beat, so TTS + `manim-voiceover` bookmarks can be generated mechanically and the audio length can be *measured* and reconciled with `duration_s` before rendering. |
| `beats[].duration_s` / `wait_after_s` | PRISM's Temporal Density metric penalizes both near-static and frantic output. Explicit per-beat durations make pacing reviewable and make total runtime predictable (critical for the live latency budget). |
| `assets[]` | Explicit manifest so the render worker can pre-stage files and fail fast (`required:true`) rather than mid-render. |
| `style.*` | Consistency across an entire talk's worth of GIFs. Separated from `layout` because style is global policy and layout is per-plan. |
| `review.success_criteria` with `check: automatic\|vlm\|human` | The literature is explicit that VLM review is not yet a trustworthy gate (ManimAgent: VLM–human r = −0.17, human κ = −0.01). So: cheap deterministic checks are *blocking*, VLM checks are *advisory*, human is the final gate on faithfulness. |
| `review.blocking` | Makes the auto-accept path explicit. Note `latex_matches` is blocking — LaTeX rendering errors are TheoremExplainAgent's #2 failure class and are entirely preventable by never letting the model invent a formula. |
| `review.max_repair_rounds` | ManimAgent bounds text-reflection at 2 retries; TheoremExplainAgent at 5. For a <3 min live budget, 2 is the ceiling. |
| `meta.priority` | Live mode produces more plans than render capacity. This is the queue key. |
| `meta.status` | Single source of truth for the pipeline state machine. |

**Markdown mirror.** Emit a human-readable rendering of the same object for review (title, one-line, the
beat table with narration and duration, the source links, and the checklist). Keep JSON as the machine
artifact; never hand-edit the Markdown.

**[design] Why not just free text (as TheoremExplainAgent does)?** Because the three enforcement points that
actually move the numbers — budgets, layout regions, and the equations-must-come-from-provenance rule — are all
mechanically checkable *only* if they're structured fields. A prose implementation plan cannot be validated
before a 30-second render is wasted.

---

## 4. Archetype taxonomy for ML / CS / math talks

Manim CE class names verified against the
[v0.21 reference manual](https://docs.manim.community/en/stable/reference.html).
Reliability ratings are my synthesis of PRISM's execution/spatial results, TheoremExplainAgent's failure
taxonomy, and Code2Video's layout findings. **[design]** for the per-archetype ratings.

### 4.1 Equation derivation / algebraic rewrite
- **When:** any `kind="equation"` segment; "we can rewrite this as", "substituting", loss-function walkthroughs.
- **Manim:** `MathTex` split into parts (`MathTex("Q", "K^\\top", "\\over", "\\sqrt{d_k}")`) →
  `TransformMatchingTex(old, new, key_map={...})`; `Write`; `Indicate` / `Circumscribe` on a submobject;
  `Brace` + `BraceLabel` for annotations; `SurroundingRectangle`.
- **Reliability: GOOD (best in class).** Most represented in training data. *Failure:* `TransformMatchingTex`
  part-matching is fragile — models pass a single monolithic `MathTex` string and get a mush transform.
  Known issue: `fade_transform_mismatches=True` errors when there are *no* mismatches
  ([manim#2845](https://github.com/ManimCommunity/manim/issues/2845)). **Mitigation:** the template must
  require the equation be authored as an explicit list of substrings, and `key_map` must be derived from the
  `symbol_ledger`.

### 4.2 Function plot / parameter sweep
- **When:** "as x grows…", learning-rate schedules, loss curves, activation functions, convergence.
- **Manim:** `Axes(x_range=, y_range=, axis_config=)`; `axes.plot(lambda x: ..., color=)`;
  `axes.c2p` / `p2c`; `ValueTracker` + `always_redraw`; `axes.get_area`; `axes.get_graph_label`;
  `Dot` on the curve; `axes.get_riemann_rectangles` for integrals.
- **Reliability: GOOD.** The canonical Manim example; `ValueTracker`+`always_redraw` is boilerplate models
  reproduce well. *Failure:* wrong `y_range` for the function (curve exits the axes), and forgetting `c2p`
  (placing a `Dot` in scene coords instead of axis coords).

### 4.3 Geometric proof / construction
- **When:** math talks, triangle inequality, projections, convexity, norms as balls.
- **Manim:** `Circle`, `Polygon`, `Line`, `Dot`, `Angle`, `RightAngle`, `DashedLine`, `Intersection`/`Union`/
  `Difference` (boolean ops); `Create`, `Rotate`, `Transform`, `MoveAlongPath`; `always_redraw` for dependent
  constructions.
- **Reliability: MEDIUM.** Syntax is easy; the *geometry* is where models err — hand-computed coordinates that
  don't actually satisfy the claimed property. **Mitigation:** compute vertices in Python from the
  construction (e.g. derive the right-angle foot) rather than letting the model hard-code floats.

### 4.4 Box-and-arrow architecture diagram
- **When:** "the encoder feeds into…", system diagrams, transformer blocks, training loops, service topology.
- **Manim:** `VGroup` of `RoundedRectangle` + `Text`; `VGroup.arrange(DOWN, buff=)` / `arrange_in_grid`;
  `Arrow` / `CurvedArrow` with `.next_to()` / `.get_edge_center()`; `LaggedStart(*[FadeIn(b) for b in boxes],
  lag_ratio=0.2)`; `SurroundingRectangle` to group; `Brace` for spans.
- **Reliability: POOR spatially / good syntactically.** This is *exactly* PRISM's failure profile — code
  executes, layout overlaps or leaves frame. **Mitigation is mandatory:** never let the model place boxes by
  absolute coordinates. Provide a helper that consumes `{nodes, edges, region}` and does the layout
  deterministically (`arrange_in_grid` + `next_to`), and have the LLM emit only the graph. This single change
  converts the worst archetype into a reliable one.

### 4.5 Data / tensor flow (shape tracking)
- **When:** "the input is B×T×D, after the projection it's B×T×H…"; conv/attention shape walkthroughs.
- **Manim:** grid of `Square`/`Rectangle` in `VGroup.arrange_in_grid`; `MathTex` shape labels;
  `Transform` from one grid to another; `Arrow` between stages; a moving `SurroundingRectangle` highlighter;
  `.animate.set_fill(opacity=)` for activation sweeps.
- **Reliability: MEDIUM-POOR.** Combinatorially many mobjects → occlusion. **Mitigation:** cap grid size
  (≤ 6×6 cells), represent large dims symbolically rather than cell-by-cell.

### 4.6 Sequence / rollout timeline
- **When:** RL rollouts, training schedules, protocol exchanges, autoregressive decoding step-by-step.
- **Manim:** horizontal `VGroup.arrange(RIGHT)` of step boxes, or `NumberLine` with `Dot` markers;
  `Arrow` between steps; `LaggedStart` for reveal; `Brace` for phases; `Text` timestamps above.
- **Reliability: MEDIUM.** Fails by running off-frame when the sequence is long. **Mitigation:** cap visible
  steps at ~6 and use an ellipsis mobject, or scroll the camera (`MovingCameraScene`).

### 4.7 Comparison table / ablation
- **When:** "method A gets 84, method B gets 91", ablations, tradeoff matrices.
- **Manim:** `Table`, `MathTable`, `MobjectTable`, `IntegerTable`, `DecimalTable`;
  `table.add_highlighted_cell((r,c))`, `table.get_cell`, `table.get_col_labels`;
  `Create(table, lag_ratio=...)`, then `Indicate` the winning cell.
- **Reliability: MEDIUM.** The `Table` constructor signature (`col_labels`, `row_labels`,
  `include_outer_lines`, `top_left_entry`) is frequently misremembered, and text overflow past the frame is
  common. **Mitigation:** template it; hard-cap at 4 columns × 5 rows for a 16:9 frame.

### 4.8 Algorithm trace / code walkthrough
- **When:** pseudocode, a training loop, a data structure operation.
- **Manim:** `Code(code_string=..., language=..., ...)` — **note the v0.19 rewrite**; a
  `SurroundingRectangle` line-highlighter that `.animate.move_to()`s down the listing; a side panel of
  `MathTex`/`Text` showing variable state; `Indicate` on the changing value.
- **Reliability: POOR — API drift is the killer.** Manim CE **v0.19.0 completely rewrote the `Code` mobject**
  ([PR #4115](https://docs.manim.community/en/stable/changelog/0.19.0-changelog.html)) with breaking interface
  changes, and `Code.styles_list` became the classmethod `Code.get_styles_list()`. LLMs overwhelmingly emit the
  pre-0.19 signature (`code=`, `tab_width=`, `background=`, `insert_line_no=`). This shows up as
  TheoremExplainAgent's "incorrect signatures / invalid parameter types" class. **Mitigation:** pin the Manim
  version, ship the exact `Code(...)` call in the template, and add the v0.19 changelog deltas to the
  RITL-DOC retrieval corpus.
- Other v0.19 breakages to preload: `ManimColor.from_hex(hex=)` → `hex_str=`;
  `Scene.next_section(type=)` → `section_type=`; `Sector` lost `inner_radius`/`outer_radius` (use
  `radius` + `angle`; `AnnularSector` keeps both); `SurroundingRectangle` now takes a *sequence* of mobjects,
  so previously-positional args must become keyword args.

### 4.9 Graph / network algorithm
- **When:** GNNs, BFS/DFS, dependency graphs, message passing, attention-as-graph.
- **Manim:** `Graph(vertices, edges, layout="spring"|"circular"|"tree", labels=True, vertex_config=,
  edge_config=)`, `DiGraph`; `graph.add_edges` / `remove_edges`;
  `Flash`/`Indicate` on a vertex; `.animate.change_layout("circular")`.
- **Reliability: MEDIUM.** `Graph` is high-level enough that models use it correctly; `layout="spring"` is
  non-deterministic across runs, which breaks frame-diff review. **Mitigation:** pass an explicit
  `layout=dict(v -> np.array([x,y,0]))` computed by your own code (networkx layout, seeded).

### 4.10 Matrix / linear-algebra transformation
- **When:** attention as matmul, PCA, rotations, change of basis, eigenvectors.
- **Manim:** `Matrix`, `DecimalMatrix`, `IntegerMatrix`, `MobjectMatrix`;
  `LinearTransformationScene` (`apply_matrix`, `add_transformable_mobject`); `NumberPlane`; `Vector`,
  `Arrow`; `get_brackets()`, `get_entries()` for per-entry highlighting.
- **Reliability: GOOD for `LinearTransformationScene` (very well documented, near-boilerplate); MEDIUM for
  hand-built matmul animations** (entry-by-entry highlighting requires index arithmetic models get wrong).

### 4.11 Probability / distribution / sampling
- **When:** sampling temperature, noise schedules, uncertainty, bootstrap, diffusion forward process.
- **Manim:** `Axes` + `axes.plot` for the density; `BarChart(values=, bar_names=)` for histograms;
  a `VGroup` of `Dot`s with `np.random` positions for sample clouds; `ValueTracker` on the parameter;
  `always_redraw` to rebuild the density.
- **Reliability: MEDIUM.** Fine with `Axes`; `BarChart`'s parameter set (`y_range`, `bar_names`,
  `y_axis_config`) is misremembered fairly often. Seed `np.random` explicitly or reviews are non-reproducible.

### 4.12 3D surface / manifold / loss landscape
- **When:** loss surfaces, manifolds, 3D geometry, spherical embeddings.
- **Manim:** `ThreeDScene`; `ThreeDAxes`; `Surface(lambda u,v: ..., u_range=, v_range=, resolution=)`;
  `set_camera_orientation(phi=, theta=)`, `move_camera`, `begin_ambient_camera_rotation`;
  `add_fixed_in_frame_mobjects` for 2D overlays; `Sphere`, `Cube`, `Line3D`, `Arrow3D`, `Dot3D`,
  `Polyhedron` (+ `Tetrahedron`/`Octahedron`/`Dodecahedron`/`Icosahedron`).
- **Reliability: POOR-MEDIUM, and expensive.** Camera-state bugs are common; `add_fixed_in_frame_mobjects`
  interacts badly with `TransformMatchingTex`
  ([manim#4085](https://github.com/ManimCommunity/manim/issues/4085)); `Surface` `resolution` drives render
  time superlinearly. **In live mode, gate this behind `budgets.allow_3d`, default false.**

### Optional extras
- **4.13a Number line / limits / counting** — `NumberLine`, `Dot`, `ValueTracker`, `MathTex` labels.
  *Reliability: GOOD.* Cheap and underused; excellent for "as n → ∞".
- **4.13b Set / Venn / partition** — `Circle` + boolean ops (`Intersection`, `Union`, `Difference`),
  `Text` labels. *Reliability: GOOD.* Small object count, hard to break.

### 4.13 Reliability summary and what it implies

| Archetype | Executes | Looks right | Primary risk |
|---|---|---|---|
| Equation derivation | high | high | `TransformMatchingTex` part matching |
| Function plot / sweep | high | high | `y_range` mismatch |
| Number line / limits | high | high | — |
| Set / Venn | high | high | — |
| Linear transformation (`LinearTransformationScene`) | high | high | — |
| Geometric proof | high | medium | geometry is wrong, not the code |
| Graph / network | high | medium | non-deterministic layout |
| Comparison table | medium | medium | constructor signature, overflow |
| Sequence timeline | high | medium | runs off frame |
| Probability / histogram | medium | medium | `BarChart` params, unseeded RNG |
| Data/tensor flow | medium | low | occlusion from object count |
| **Box-and-arrow architecture** | **high** | **low** | **overlap / out-of-bounds — the PRISM failure** |
| **Algorithm trace / `Code`** | **low** | medium | **v0.19 API drift** |
| 3D surface | medium | low | camera state, render cost |

**The actionable conclusion.** The Execution–Spatial Gap (≈41 pp, PRISM) is concentrated in exactly the
archetypes ML/CS talks need most (architecture diagrams, data flow). Free-form generation will not close it.
**Ship each archetype as a parameterized Manim template** — a Python function taking a validated dataclass and
doing deterministic layout — and have the LLM emit *the plan's beat list*, not the code, for the
6 low-reliability archetypes. Reserve free-form code generation for the high-reliability archetypes and for
the long tail, where RITL-DOC-style repair ([arXiv:2604.18364](https://arxiv.org/html/2604.18364): 94% render
success) is affordable.

---

## 5. Live mode design

### 5.1 State

```
TranscriptLog        append-only, confirmed text only (LocalAgreement-2 output), with (t_start,t_end) per sentence
Buckets              active: list[Bucket]; each = {bucket_id, sentence_ids[], centroid, t_open, t_last_add,
                                                   archetype_scores, evidence_flags, mass}
EmittedIndex         concept fingerprints of every plan already emitted (for dedup)
PlanQueue            priority queue of mature plans awaiting code+render
RenderPool           N warm worker processes
Watermark            last processed sentence id  -->  guarantees no reprocessing
```

Every tick reads only `TranscriptLog[watermark:]`. Nothing earlier is re-embedded, re-classified, or
re-planned. This is the whole trick: **buckets are the only mutable state, and they are bounded in size.**

### 5.2 Tick schedule

| Tick | Period | Work | Cost |
|---|---|---|---|
| **T0 — absorb** | on each confirmed sentence (≈ every 3–8 s) | embed the sentence (local MiniLM-class model, ~1 ms); assign to the nearest active bucket if cosine ≥ τ_join (≈0.6), else open a new bucket; update centroid incrementally; run the BertSeg-style cohesion check | ~free, CPU |
| **T1 — classify** | every 60–90 s | one small-model JSON call over *only* the sentences added since the last T1, per touched bucket: `{concept_name, archetype_scores, has_equation, has_algorithm, has_architecture, salience}`; merge into bucket state | 1 cheap call/min |
| **T2 — maturity sweep** | every 30 s | evaluate `mature()` (§2.3) over active buckets; close and enqueue matures; force-close stale buckets; garbage-collect empty ones | free |
| **T3 — plan** | on dequeue | full planner call → ANIMATION PLAN JSON (§3) | 1 strong-model call |
| **T4 — realize** | on plan | archetype template fill (or codegen) → render → checks → publish GIF | render pool |

**Why 60–90 s for T1.** It is roughly the time for a speaker to actually finish a thought (a lecture paragraph),
and it bounds LLM spend at ~60 calls/hour for classification. T0 at sentence granularity is what keeps the
*boundary* detection sharp despite the coarse T1 cadence — you get cheap continuous signal plus periodic
expensive judgement.

**Incremental-only guarantees.** (a) `TranscriptLog` is append-only because LocalAgreement-2 only emits
confirmed prefixes; (b) bucket centroids update via running mean, never recomputed; (c) T1 prompts contain only
the delta plus a ≤200-token bucket summary, so prompt size is constant regardless of talk length; (d) a global
"talk so far" summary is maintained by periodic rolling compaction (every ~10 min), used only as planner
context, never re-derived from scratch.

### 5.3 Latency budget: concept → GIF

Target: **≤ 150 s** from "bucket matures" to "GIF published". Everything before that (ASR + bucketing) runs
continuously and adds only the ~3.3 s LocalAgreement lag plus up to 30 s of maturity-sweep granularity.

| Stage | Budget | Notes |
|---|---|---|
| T2 sweep granularity | 0–30 s | reduce to 15 s if needed |
| T3 plan generation | 15–25 s | one strong-model call, structured output, ~1.5k output tokens |
| T4a template fill / codegen | 10–30 s | template fill (JSON→params) is ~5 s; free-form codegen ~25 s |
| T4b render | 20–45 s | `-ql --format=gif` (480p15). Dominated by LaTeX for math-heavy scenes |
| T4c automatic checks | 3–8 s | bbox overlap / in-frame / duration over sampled frames |
| T4d repair round (if needed) | +35 s each, max 2 | RITL: last 10 error-log lines + retrieved API docs |
| **Total, no repair** | **~50–140 s** | |
| **Total, 1 repair** | **~85–175 s** | at the edge of the 3 min budget |

### 5.4 The seven things that make this budget real **[design]**

1. **Warm render pool.** `import manim` alone costs seconds. Keep N forked worker processes with Manim
   preimported, and feed them scene modules. Never `subprocess` a cold `manim` CLI per job.
2. **Prewarm the LaTeX cache.** `MathTex` shells out to `latex` + `dvisvgm`; Manim caches rendered SVGs by
   content hash under `media/Tex`. Pre-render the `symbol_ledger` glyphs and any `provenance.equations` the
   moment a plan is created, *in parallel with code generation*. This alone can halve render time for
   derivation scenes.
3. **Prefer `Text`/`MarkupText` over `MathTex` for non-math labels.** `Text` is Pango, no LaTeX round-trip.
   Enforce in the template layer, not by asking the model nicely.
4. **`-ql` (480p15) for the live GIF, always.** High-quality re-render is an offline batch job on accepted
   plans only. Keep Manim's caching **on** (do not pass `--disable_caching`).
5. **Stay on the Cairo renderer for the live path.** OpenGL is *sometimes* slower than Cairo in Manim CE
   (reported: a scene at ~36 s under OpenGL vs ~24 s under Cairo, with `self.wait(1)` costing 4 s), and its
   mobject classes are incompatible with the Cairo ones — a fork in the template library you don't want.
6. **Hard complexity budget enforced in the validator, before render.** Reject a plan whose beats exceed
   `max_concurrent_mobjects` or `on_screen_text_chars` and re-plan (cheap) rather than render-then-fail
   (expensive). This is the direct operationalization of PRISM's complexity→failure finding.
7. **Speculative parallelism.** Run T4a for the top-2 queued plans concurrently; run the automatic checks on
   sampled frames *while* the GIF encodes. Pipeline depth, not per-stage speed, is what keeps the queue drained
   during a dense stretch of a talk.

### 5.5 Degradation policy

- **Queue depth > 3:** raise the maturity threshold (emit fewer, higher-salience concepts) rather than letting
  latency grow unboundedly.
- **Repair budget exhausted:** publish the plan *without* a GIF, marked `status: needs_human`. A plan with
  provenance and beats is still useful output; a stalled queue is not.
- **Archetype confidence < 0.5:** fall back to the highest-reliability compatible archetype (usually
  equation-derivation or a titled bullet reveal) rather than attempting the ambitious one.
- **Live vs post-hoc:** run the same planner offline after the talk with `allow_3d`, `allow_external_assets`,
  higher budgets, and `-qh`. Live output is a draft; the batch pass is the deliverable.

---

## 6. Concrete next steps for the build

1. Implement `Segment` / `SourceSpan` and the five adapters behind one `ingest(uri) -> list[Segment]` interface.
   PPTX and markdown first (cheapest, highest fidelity), then faster-whisper, then PDF/marker, then YouTube.
2. Build the bucketer (T0/T1/T2) against a *recorded* transcript first, replayed at 1× — live mode is just
   the same code with a different source.
3. Write the JSON Schema for the ANIMATION PLAN and a validator that enforces `budgets` and
   `latex_matches` *before* anything is rendered.
4. Implement the 5 high-reliability archetypes as parameterized templates (equation derivation, function plot,
   number line, box-and-arrow with deterministic layout, comparison table) before touching free-form codegen.
   The box-and-arrow deterministic layout helper is the single highest-value piece of code in the project.
5. Build the render pool + automatic checkers (overlap, in-frame, text budget, duration) and only then add
   the VLM advisory reviewer.
6. Pin Manim CE (≥0.19) and build a small API-doc corpus for RITL-DOC-style repair, seeded with the v0.19
   breaking changes.

---

## Sources

- [TheoremExplainAgent (arXiv:2502.19400)](https://arxiv.org/html/2502.19400v1) · [repo](https://github.com/TIGER-AI-Lab/TheoremExplainAgent) · [project page](https://tiger-ai-lab.github.io/TheoremExplainAgent/)
- [Code2Video (arXiv:2510.01174)](https://arxiv.org/abs/2510.01174) · [repo](https://github.com/showlab/Code2Video) · [OpenReview](https://openreview.net/forum?id=iuTUbkZO75)
- [Manimator (arXiv:2507.14306)](https://arxiv.org/html/2507.14306v1)
- [ManimAgent (arXiv:2606.30296)](https://arxiv.org/html/2606.30296v1)
- [PRISM benchmark (arXiv:2605.19382)](https://arxiv.org/html/2605.19382) · [repo](https://github.com/positionprivacy/PRISM)
- [Training & Agentic Inference for LLM Manim (arXiv:2604.18364)](https://arxiv.org/html/2604.18364)
- [LLM2Manim (arXiv:2604.05266)](https://arxiv.org/html/2604.05266)
- [See Before You Code (arXiv:2605.15585)](https://arxiv.org/pdf/2605.15585)
- [EduVisBench / EduVisAgent (arXiv:2505.16832)](https://arxiv.org/pdf/2505.16832)
- [Taxonomy of didactic roles of dynamic visualization in animated mathematics videos, Teaching Mathematics and its Applications 44(1):47](https://academic.oup.com/teamat/article/44/1/47/7681993)
- [TreeSeg (arXiv:2407.12028)](https://arxiv.org/abs/2407.12028)
- [Unsupervised Topic Segmentation of Meetings with BERT Embeddings (arXiv:2106.12978)](https://arxiv.org/html/2106.12978v1)
- [PODTILE (arXiv:2410.16148)](https://arxiv.org/pdf/2410.16148)
- [Towards Multi-Level Transcript Segmentation, Interspeech 2025](https://www.isca-archive.org/interspeech_2025/freisinger25_interspeech.pdf)
- [MaViLS video-to-slide alignment (arXiv:2409.16765)](https://arxiv.org/html/2409.16765)
- [Whisper-Streaming / LocalAgreement-2 (arXiv:2307.14743)](https://arxiv.org/html/2307.14743) · [repo](https://github.com/ufal/whisper_streaming)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [PyPI](https://pypi.org/project/faster-whisper/)
- [WhisperX](https://github.com/m-bain/whisperx)
- [OpenAI speech-to-text guide](https://platform.openai.com/docs/guides/speech-to-text)
- [Deepgram: interim results & endpointing](https://developers.deepgram.com/docs/understand-endpointing-interim-results) · [Utterance End](https://developers.deepgram.com/docs/utterance-end)
- [AssemblyAI Universal Streaming](https://www.assemblyai.com/docs/streaming/universal-streaming) · [WebSocket API spec](https://www.assemblyai.com/docs/streaming/api-spec/streaming-websocket)
- [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ) · [#13831 subtitle 429](https://github.com/yt-dlp/yt-dlp/issues/13831) · [#14390 SABR](https://github.com/yt-dlp/yt-dlp/issues/14390) · [#14530 auto-caption `>>`](https://github.com/yt-dlp/yt-dlp/issues/14530)
- [youtube-transcript-api #511 IP blocking](https://github.com/jdepoix/youtube-transcript-api/issues/511)
- [PyMuPDF](https://github.com/pymupdf/pymupdf) · [TextPage docs](https://pymupdf.readthedocs.io/en/latest/textpage.html) · [Images recipes](https://pymupdf.readthedocs.io/en/latest/recipes-images.html)
- [marker-pdf](https://pypi.org/project/marker-pdf/) · [Docling (arXiv:2501.17887)](https://arxiv.org/pdf/2501.17887) · [Benchmarking Document Parsers on Mathematical Formula Extraction (arXiv:2512.09874)](https://arxiv.org/pdf/2512.09874)
- [unarXive 2022 (arXiv:2303.14957)](https://arxiv.org/pdf/2303.14957) · [pylatexenc](https://pylatexenc.readthedocs.io/)
- [python-pptx speaker notes example](https://dri.es/extract-speaker-notes-from-powerpoint-to-text)
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) · [detectors](https://www.scenedetect.com/docs/api/detectors.html)
- [Manim CE reference manual](https://docs.manim.community/en/stable/reference.html) · [v0.19.0 changelog](https://docs.manim.community/en/stable/changelog/0.19.0-changelog.html) · [manim#2845](https://github.com/ManimCommunity/manim/issues/2845) · [manim#4085](https://github.com/ManimCommunity/manim/issues/4085) · [manim#1957 OpenGL perf](https://github.com/ManimCommunity/manim/issues/1957)
- [manim-voiceover](https://voiceover.manim.community/en/stable/quickstart.html)
