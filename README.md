# manim-engineer

Turn the hard parts of a research paper or talk into short, verified Manim animations.

Input: an arXiv paper (ID or URL), a PDF paper or slide deck, PPTX, Markdown with equations,
or a live or recorded transcript.
Output: per-beat GIFs, MP4 clips, poster PNGs, a browsable gallery and a presenter deck, plus an
editable animation plan for each concept so revisions are cheap.

<!-- Demo GIF: drop one of your arXiv run's GIFs here, e.g. ![demo](docs/demo.gif) -->

## Quick start

```bash
uv sync --all-extras

# From an arXiv paper: fetches the LaTeX source and keeps its equations exact
.venv/bin/manim-engineer run 2211.17192 --out outputs/specdec
open outputs/specdec/index.html

# Or from a local Markdown file
.venv/bin/manim-engineer run cases/e1_softmax_markdown/input.md --out outputs/e1
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

- **Inputs**: arXiv papers (LaTeX source with an equation ledger), PDF papers and decks, PPTX with speaker notes, Markdown with `$$` equations, transcripts (JSON/VTT/SRT/plain), audio (faster-whisper), YouTube (captions, audio fallback).
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
.venv/bin/pytest -q                 # full suite; renders one real scene
.venv/bin/ruff format src tests && .venv/bin/ruff check src tests
./.beryl/scripts/check.sh           # the deterministic gate
```

On macOS, see [docs/macos-setup.md](docs/macos-setup.md) for toolchain prerequisites
and the pycairo workaround.

## Origin and credits

manim-engineer started at NUS AI Society. [@checkpoint214159](https://github.com/checkpoint214159)
built the original pipeline (ingest, planning, code generation, verification and rendering).

My contributions since then:

- **Source fidelity for arXiv papers.** An arXiv LaTeX ingest adapter that builds an equation
  ledger and carries source equations into each animation plan word for word. A verification check
  blocks any render whose equations were changed or dropped (ADR 0007).
- **Presenter deck.** Every run now produces a Reveal.js presenter deck built from the section
  clips (ADR 0008).
- **Approval pins.** `approve` pins a concept's plan and accepted code. Re-runs keep approved
  concepts, and the deck is built only from them (ADR 0009).
- [macOS setup docs](docs/macos-setup.md) and test-manifest fixes.

Contributors: [@checkpoint214159](https://github.com/checkpoint214159),
[@Aryan-Dalvi](https://github.com/Aryan-Dalvi), [@architsharma69](https://github.com/architsharma69).
