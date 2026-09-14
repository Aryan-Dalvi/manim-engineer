# ADR 0006: Output contract and GIF recipe

## Status

Accepted (2026-09-14)

## Context

Manim's native `--format gif` forces an `rgb8` pixel format that discards the optimized palette; measured output is lower quality and 2.7x larger than an ffmpeg palettegen/paletteuse pass. Presenters on Google Slides need GIFs; PowerPoint takes MP4; web decks take reveal.js.

## Decision

`output.publish` renders once with `--save_sections`, then derives from the MP4s: per-section GIF (`fps=20,scale=960:-2`, `palettegen=max_colors=128:stats_mode=diff`, `paletteuse=dither=none:diff_mode=rectangle:new=1`, `-loop 0`), per-section last-frame PNG, master thumbnail, and a PowerPoint-safe H.264 yuv420p re-encode. `manifest.json` is the contract every downstream consumer reads. manim-slides HTML/PPTX/PDF export is an optional step that never fails the run.

## Consequences

- **Benefit:** small, high-quality GIFs; one render; downstream code never globs the filesystem.
- **Tradeoff:** ffmpeg is a hard runtime dependency for derivatives.
- **Follow-up:** add transparent WebM/APNG variants on request only.
