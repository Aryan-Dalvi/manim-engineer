# Testing Policy

## Command Matrix

| Check | Command | Status | Notes |
| --- | --- | --- | --- |
| Markdown sanity | `./.beryl/scripts/check-md.sh` | available | Unclosed fences and tabs |
| Test manifest immutability check | `./.beryl/scripts/check-tests-unchanged.sh` | available | Detects changes in configured test scope from `.beryl/agent/test-manifest.conf` |
| Affected test gate | `./.beryl/scripts/check-affected.sh --worktree` | available | Selects related tests from changed files and uses full-test fallback for broad changes |
| Aggregate deterministic gate | `./.beryl/scripts/check.sh` | available | Runs all deterministic checks |
| Format | `.venv/bin/ruff format src tests` | available | Run before checks |
| Lint | `.venv/bin/ruff check src tests` | available | |
| Typecheck | `not available yet` | unavailable | Add mypy/pyright when the surface stabilizes |
| Unit tests | `.venv/bin/pytest -q` | available | Fast suite; LLM calls use `FakeBackend`; Manim probe tests run in-process |
| Integration tests | `.venv/bin/pytest -q -m integration` | available | Renders with Manim and ffmpeg; skipped when tools are missing |
| Live LLM smoke | `.venv/bin/pytest -q -m live_llm` | opt-in | Requires the Claude CLI login or an API key; never run in the gate |
| E2E corpus | `.venv/bin/manim-engineer run-cases --cases easy` | manual | Produces `outputs/`; human-reviewed via gallery |

## Default Loop

1. Identify or add the failing behavior.
2. Select the smallest useful test level.
3. State success checks before implementation: expected artifact, narrow command, broader command, generated output or browser evidence when applicable, and one user-visible behavior.
4. Implement one internal feature slice.
5. Run `ruff format`, then narrow checks (`pytest tests/<file>`), then `.venv/bin/pytest -q`, then `./.beryl/scripts/check.sh`.
6. Repair from actual tool output.
7. For gallery HTML work, open the generated `index.html` and verify with a browser tool when available.

## Generated Output Verification

Rendering and publishing produce files users receive. For output-context changes verify:

- `animations/<concept>/manifest.json` lists every artifact and every listed file exists.
- Section GIFs decode with ffprobe and have the expected frame count.
- Gallery `index.html` references only files that exist.
- Run `deck.html` links only clips that exist plus the copied `revealjs/` assets, and every request it makes stays on the local origin.
- Run `deck.html` holds slides only for concepts whose approval pin in `review/approvals.json` still holds.
- In a browser the deck reports `Reveal.isReady()`, each beat's clip plays when its slide is shown, and narration comes back from `Reveal.getSlideNotes()`. Serve the deck over local HTTP for this; the in-app browser cannot run scripts in a `file://` page.
- Browser screenshots can omit `<video>` layers. Judge playback from element state, or draw the current frame onto a canvas over the video, never from a blank screenshot alone.

## Affected Test Gate

- The pre-commit hook sets `CHECK_AFFECTED_MODE=staged` and runs `./.beryl/scripts/check.sh`.
- `.beryl/scripts/check-affected.sh` reads `.beryl/agent/affected-tests.conf`, which maps source changes to `pytest` and broad changes to the full suite.

## Test Modification Rule

Existing tests may not be weakened to make implementation pass.

Intentional test changes are allowed only when all conditions are met:

1. The behavior change is explicit in the task or design artifact.
2. `./.beryl/scripts/update-test-manifest.sh` is run after the intentional change.
3. The manifest update is committed with the test change.
4. The final response explains why tests changed.
5. `.beryl/agent/test-manifest.conf` is updated if new test locations/patterns are introduced.

## Mocking Rules

- Mock external systems: LLM backends (`FakeBackend`), network (YouTube, arXiv), ASR models, clocks.
- Do not mock Manim in verification tests; the probe must run the real library.
- Do not mock domain logic in the same bounded context.
