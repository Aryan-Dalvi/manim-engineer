# Project Brief

## Product Goal

Build **manim-engineer** for **presenters, lecturers, and paper authors** so
they can **turn the hard parts of a talk into short, verified Manim
animations (GIFs and steppable clips) from whatever input they have: live or
recorded transcript, slides, YouTube, audio, or manuscript**.

## Primary Workflows

1. **Batch run**: `manim-engineer run <input> --out outputs/<name>` ingests one
   input, plans the animation-worthy concepts, generates and verifies Manim
   scenes, publishes GIF/MP4/PNG bundles, and writes a browsable gallery.
   Success: every accepted animation passed Tier 0 and Tier 1 gates and has a
   manifest; rejected ones are listed with their findings.
2. **Live replay**: `manim-engineer live <transcript> --speed N` feeds a
   growing transcript through the bucketer and emits plans and animations as
   buckets mature. Success: plans appear while the transcript is still
   growing and no segment is processed twice.
3. **Review and revise**: the reviewer leaves notes in the gallery or
   `review/notes.json`; `manim-engineer revise <run> <concept_id>` folds the
   note into the plan and regenerates only that animation. Success: the
   revised bundle replaces the old one and the note is recorded in the plan.

## Non-Goals

- Narration audio or TTS muxing (narration text is planned, not voiced).
- A web server or hosted UI; the gallery is static HTML.
- Model training or fine-tuning.
- Extracting a deck's visual identity (palette, fonts); slide provenance only.

## External Systems

| System | Why it exists | Interface owner | Failure fallback |
| --- | --- | --- | --- |
| Claude CLI (`claude -p`) | Default LLM backend using the user's login | `llm.ClaudeCliBackend` | Raise `LLMError`; pipeline marks the concept `needs_human` |
| Anthropic SDK | LLM backend when an API key exists | `llm.AnthropicBackend` | Same as above |
| ManimCE 0.19.x | Rendering and the Tier 1 layout probe | `verification.runner`, `output.render` | Findings with category `manim_runtime`, `timeout`, `oom` |
| ffmpeg | GIF, stills, PPT-safe MP4 | `output.derivatives` | Bundle published without derivatives, flagged in manifest |
| Reveal.js 6.0.2 (vendored) | Offline HTML presenter deck per run | `output.revealjs`, `pipeline.gallery` | No deck when no clip is playable |
| faster-whisper | Audio to timestamped transcript | `ingest.audio` | Error if model unavailable |
| yt-dlp, youtube-transcript-api | YouTube captions and audio | `ingest.youtube` | Captions fail → download audio → faster-whisper |
| PyMuPDF, python-pptx | PDF and PPTX slides and manuscripts | `ingest.slides`, `ingest.manuscript` | Error with the failing page |
| LaTeX (`latex`, `dvisvgm`) | Tier 0 precompile and Manim text rendering | `verification.static` | Finding category `latex` |

## Definition Of Done

A feature is complete only when it has all of the following:

1. A small design artifact update (`design-tree.md` and/or ADR) when design changes.
2. Clear boundary types/interfaces (pydantic models in `core`, protocols in `llm`).
3. Behavior tests plus at least one edge case test.
4. Deterministic checks run (`./.beryl/scripts/check.sh` and `.venv/bin/pytest`).
5. No new illegal boundary crossings.
