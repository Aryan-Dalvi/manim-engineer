# manim-engineer

Turn the hard parts of a talk into short, verified Manim animations.

Input: live or recorded transcript, slides (PDF/PPTX), YouTube link, audio, or manuscript.
Output: per-beat GIFs, MP4 clips, poster PNGs and a browsable gallery, plus an editable
animation plan for each concept so revisions are cheap.

See `docs/PLAN.md` for the full design and `docs/research/` for the research it rests on.

## Quick start

```bash
uv sync --all-extras
.venv/bin/manim-engineer run cases/e1_softmax_markdown/input.md --out outputs/e1
open outputs/e1/index.html
```

The default LLM backend is the Claude CLI (`claude -p`), which uses your existing
Claude Code login. Set `ANTHROPIC_API_KEY` to use the SDK instead, or pass
`--backend fake` for deterministic dry runs.

## What it does

```
input ─► ingest ─► bucket + triage ─► AnimationPlan (JSON, editable)
      ─► Manim code (kit + knowledge pack) ─► Tier 0 static ─► Tier 1 no-render probe
      ─► repair (findings carry fixes) ─► render ─► GIF/MP4/PNG + deck.pptx ─► Tier 2 critique
      ─► gallery with review notes ─► revise
```

- **Inputs**: transcript (JSON/VTT/SRT/plain), Markdown with `$$` equations, PDF decks and papers, PPTX with speaker notes, audio (faster-whisper), YouTube (captions, audio fallback).
- **Plans** live in `outputs/<run>/plans/*.json` with a Markdown mirror; edit and `render-plan`.
- **Verification** is deterministic first: API existence against the installed Manim, LaTeX precompile, and a 0.3 s layout probe that executes the scene without rendering. The vision critic only advises.
- **Outputs**: per-beat GIFs and MP4s, poster PNGs, a PowerPoint deck with one slide per beat, and `manifest.json`.

## Commands

```bash
manim-engineer run <input> --out outputs/<name> [--max-plans 4] [--audience grad] [--quality m]
manim-engineer live <transcript> --out outputs/<name> --chunk 4        # replay as a live stream
manim-engineer plan <input> --out outputs/<name>                        # plans only
manim-engineer render-plan outputs/<name>/plans/<concept>.json --out outputs/<name>
manim-engineer revise outputs/<name> <concept> --note "make the arrows blue"
manim-engineer approve outputs/<name> <concept>                         # pin it: re-runs keep it, the deck shows it
manim-engineer unapprove outputs/<name> <concept>
manim-engineer run-cases [--tier easy] [--only e1_softmax_markdown]     # the corpus in cases/
manim-engineer gallery outputs                                          # rebuild outputs/index.html
manim-engineer doctor
```

Backends: `--backend claude-cli` (default when the `claude` CLI is installed; uses your login),
`--backend anthropic` (needs `ANTHROPIC_API_KEY`), `--backend fake` (scripted, for tests).
Models per tier: `--model-fast`, `--model-strong`, `--model-vision`; effort: `--effort-strong low|medium|high`.

## Layout

- `src/manim_engineer/` — bounded contexts: `core`, `llm`, `ingest`, `planning`, `generation`, `kit`, `verification`, `output`, `pipeline`, plus `cli.py`.
- `cases/` — the nine-case corpus (easy / hard / challenging); `scripts/fetch_corpus.py` downloads the large inputs.
- `outputs/` — run directories with galleries (untracked). See `outputs/README.md` for how to review.
- `docs/PLAN.md`, `docs/research/` — the plan and the research behind it. `.beryl/agent/` — canonical design docs and ADRs.

## Development

```bash
uv sync --all-extras --group dev
.venv/bin/pytest -q                 # 60 tests, ~20 s (renders one scene)
.venv/bin/ruff format src tests && .venv/bin/ruff check src tests
./.beryl/scripts/check.sh           # the deterministic gate
```

On macOS, see [docs/macos-setup.md](docs/macos-setup.md) for toolchain prerequisites
and the pycairo workaround.
