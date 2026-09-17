# macOS setup

Getting a working environment on Apple Silicon. Verified 2026-09-17 on macOS 26.6
(arm64) with Python 3.11.16, Manim 0.19.2, and the full suite green.

## 1. Command line tools

Manim's dependencies compile C extensions, so `cc` must work:

```bash
sudo xcode-select -s /Library/Developer/CommandLineTools
```

If `cc`, `git` or `python3` report "You have not agreed to the Xcode license
agreements", this is the cause: `xcode-select` points at an `Xcode.app` whose
licence was never accepted, and every compile, clone and build fails behind it.

## 2. Native libraries

```bash
brew install cairo pango pkg-config ffmpeg python@3.11
```

`ffmpeg` is required by `output.derivatives` for GIFs, stills and PPT-safe MP4.
Homebrew's `python@3.11` is a reliable interpreter for building C extensions.

## 3. LaTeX

Manim shells out to `latex` and `dvisvgm` for every `Tex` / `MathTex`:

```bash
brew install --cask basictex
sudo tlmgr update --self
sudo tlmgr install dvisvgm standalone preview doublestroke relsize ragged2e \
  fundus-calligra microtype wasysym physics siunitx cm-super babel-english jknapltx
```

Without `dvisvgm`, nine tests fail with `FileNotFoundError: 'dvisvgm'`. The probe,
alignment, output and pipeline tests all render
`tests/fixtures/scenes/good_scene.py`, which contains a `MathTex`, so a single
missing binary looks like nine unrelated failures — including an `order`
assertion in `test_alignment_missing_beat_and_order` that fails only because the
probe returns no frames.

Do **not** `brew install dvisvgm`: it depends on Homebrew's own `texlive` and
pulls roughly 6 GB, duplicating BasicTeX.

## 4. pycairo does not build under `uv sync`

`uv.lock` records pycairo wheels for Windows only, so macOS must build it from
the sdist — and that build fails inside uv's isolated build environment:

```
../meson.build:1:0: ERROR: Compiler cc cannot compile programs.
```

The same build succeeds with plain `pip` in an ordinary venv using the same
interpreter, so this is specific to uv's build isolation, not the toolchain.
Neither switching interpreter (uv-managed 3.11 vs Homebrew 3.11) nor
`UV_FIND_LINKS` nor `--no-build-isolation-package pycairo` avoids it; uv deletes
the meson log on failure, so the underlying cause is still unidentified.

Workaround — build the wheel once, then install it into the project venv:

```bash
python3.11 -m venv /tmp/pycairo-build
/tmp/pycairo-build/bin/pip wheel pycairo -w /tmp/wheelhouse
uv sync --python /opt/homebrew/bin/python3.11 --group dev   # fails on pycairo, installs the rest
uv pip install --python .venv/bin/python /tmp/wheelhouse/pycairo-*.whl
```

`uv pip install` does not consult `uv.lock`, so the locally built wheel is
accepted. Note that re-running `uv sync` will try to rebuild pycairo and fail
again — re-run the last line afterwards.

## 5. Verify

```bash
.venv/bin/manim-engineer doctor
.venv/bin/pytest -q
```

`doctor` should list `manim`, `python`, `ffmpeg`, `ffprobe`, `latex`, `dvisvgm`
and an available backend. `faster-whisper` shows as missing unless you install
the optional `audio` extra.
