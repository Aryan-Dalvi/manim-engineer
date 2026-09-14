# Output / Display Layer — Research Report

Scope: how LLM-generated Manim animations get out of the renderer and into a presenter's hands.
All version facts verified against source (cloned repos / raw.githubusercontent) on 2026-09-14.
All ffmpeg claims measured locally on ffmpeg 4.4.2 — numbers in Appendix A.

---

## 0. Executive summary

1. **One render produces everything.** `manim_slides.Slide` subclasses `manim.Scene`, and
   `Slide.next_slide()` literally calls `Scene.next_section()` under the hood
   (`manim_slides/slide/manim.py:135-148`). So a single
   `manim-slides render -qh --save_sections file.py Scene` run emits the full-scene MP4,
   per-section MP4s + section JSON index, **and** the `slides/Scene.json` + `slides/files/`
   tree that `manim-slides convert` consumes. No double render.
2. **Never ship Manim's native `--format gif`.** Manim builds the GIF with a good
   palettegen/paletteuse chain and then throws the palette away by forcing
   `output_stream.pix_fmt = "rgb8"` (3:3:2 fixed palette). Measured: 60 distinct colours
   instead of 245, SSIM 0.982 vs 0.997, and the file is **2.7× larger** (3.67 MB vs 1.35 MB).
   Still present in `main` (0.21). Always post-process the MP4 with ffmpeg instead.
3. **Dithering is the wrong default for Manim content.** Manim scenes are flat-colour.
   `dither=none` with `max_colors=64..128` beats bayer dithering on *both* size and SSIM for
   flat content, and costs 2.7× size for +0.0016 SSIM on gradients.
4. **manim-slides is the right HTML/PPTX tool**: MIT, 935 stars, actively maintained
   (last commit 2026-09-11), Qt is *not* required for `render`/`convert`, only for `present`.
   Headless/CI-clean.
5. **Presenter reality**: PowerPoint takes embedded MP4 (manim-slides `--to=pptx` does this
   natively with autoplay + loop). Google Slides **cannot** take a local video file reliably —
   it wants Drive or YouTube — so **animated GIF is the Google Slides delivery format**.
   Web dashboard gets reveal.js HTML (multi-file, not `--one-file`).

---

## 1. manim-slides (`jeertmans/manim-slides`)

### 1.1 Project facts

| Field | Value |
|---|---|
| License | MIT (`LICENSE.md`) |
| Stars / forks / open issues | 935 / 114 / 44 |
| Created / last push | 2022-07-12 / **2026-09-11** (actively maintained) |
| Latest PyPI release | **5.6.0**, 2026-04-15 |
| Release cadence | 5.5.0 (2025-03), 5.5.1, 5.5.2, 5.5.3 (2026-01), 5.5.4 (2026-02), 5.6.0 (2026-04) |
| Python (5.6.0 / main) | `>=3.9` released / `>=3.10` on main (breaking change in unreleased) |
| Docs | https://manim-slides.eertmans.be |
| Paper | JOSE, DOI in `CITATION.cff` |

Single maintainer + steady outside contributions; bus-factor risk is real but the code is
~3k lines and the output formats are all standard (reveal.js HTML, python-pptx, PIL PDF).

### 1.2 How `Slide` / `next_slide()` work

```python
from manim import *
from manim_slides import Slide

class Demo(Slide):
    def construct(self):
        c = Circle(radius=3, color=BLUE); d = Dot()
        self.play(GrowFromCenter(c))
        self.next_slide()                       # pause point
        self.next_slide(loop=True)              # next slide loops until keypress
        self.play(MoveAlongPath(d, c), run_time=2, rate_func=linear)
        self.next_slide(notes="Speaker note in **Markdown**")
        self.play(d.animate.move_to(ORIGIN))
```

Mechanics (`manim_slides/slide/base.py`, `slide/manim.py`, `config.py`):

- `Slide(BaseSlide, Scene)`; `ThreeDSlide(Slide, ThreeDScene)`. `Slide.__init__` forces
  `config["write_to_movie"] = True` (so it works under the OpenGL renderer too).
- `Slide.next_slide(*args, **kw)` → `Scene.next_section(*args, skip_animations=...)` **and**
  records a `PreSlideConfig(start_animation, end_animation, ...)`.
  Positional args pass straight through, so `self.next_slide("IntroDone", loop=True)` names
  the Manim section `IntroDone`.
- `Slide.next_section()` is an explicit **alias** to `next_slide()` — you cannot use Manim
  sections independently of slides inside a `Slide` subclass. They are the same cut.
- At `render()` end, `_save_slides()` concatenates the partial movie files per slide into
  `slides/files/<Scene>/<sha256>.mp4`, generates a `<sha>_reversed.mp4` for each (for
  backwards navigation), and writes `slides/<Scene>.json`.
- Class-level knobs: `disable_caching`, `flush_cache`, `skip_reversing` (skip reverse-video
  generation — big speedup, `rev_file = file`), `max_duration_before_split_reverse = 4.0`,
  `num_processes`.
- Instance knobs: `self.wait_time_between_slides` (default 0.0; set ≥ `1/fps` to avoid a
  1-frame flash on slide change), `self.wait_between_looping_slides`.
- Canvas API: `add_to_canvas(**mobjects)` / `remove_from_canvas()` / `self.canvas` /
  `self.mobjects_without_canvas`; transitions `self.wipe(...)`, `self.zoom(...)`.
- `start_skip_animations()` / `stop_skip_animations()` to exclude ranges from output.

`next_slide()` keyword args (`BaseSlideConfig`, `config.py:167-200`) and where each is honoured:

| kwarg | default | present (Qt) | convert html | convert pptx | convert pdf |
|---|---|---|---|---|---|
| `loop` | False | yes | yes (`data-background-video-loop`) | yes (`repeatCount=indefinite`) | n/a |
| `auto_next` | False | yes | yes (`data-autoslide=<ms>`) | no | n/a |
| `playback_rate` | 1.0 | yes | no | no | n/a |
| `reversed_playback_rate` | 1.0 | yes | no | no | n/a |
| `notes` (Markdown) | "" | yes | yes (`<aside class="notes">`) | yes (plain text) | no |
| `dedent_notes` | True | — | — | — | — |
| `skip_animations` | False | drops slide from output | ← | ← | ← |
| `src` (Path) | None | external video/image file as the slide | ← | ← | ← |
| `direction` | `horizontal` | — | `vertical` → reveal.js vertical stack | no | no |

### 1.3 Rendering artifacts (the `slides/` tree)

```
slides/
├── <Scene>.json                       # PresentationConfig
└── files/<Scene>/
    ├── <sha256>.mp4                   # one file per slide
    └── <sha256>_reversed.mp4
```

`slides/<Scene>.json`:

```json
{
  "slides": [
    {"file": "slides/files/BasicSlide/28bf…11.mp4",
     "rev_file": "slides/files/BasicSlide/28bf…11_reversed.mp4",
     "loop": false},
    {"file": "…", "rev_file": "…", "loop": true}
  ],
  "resolution": [854, 480],
  "background_color": "black"
}
```

Paths in the JSON are resolved relative to `path.parent.parent` on load — i.e. the JSON
assumes it sits in `slides/` next to `slides/files/`. Do not relocate it without rewriting.
Filenames are content hashes (`merge_basenames`), not human-readable — index by the JSON.

### 1.4 Supported Manim flavors / versions

- Auto-detects ManimCE vs ManimGL at import (`manim_slides/slide/__init__.py`).
- Extras: `manim = ["manim>=0.19"]`, `manimgl = ["manimgl>=1.7.2", "setuptools<80.10.2"]`.
- **v5.4.0 bumped the floor to `manim>=0.19`** → ManimCE **0.18.x is not supported by
  manim-slides ≥ 5.4.0**; for 0.18 you need manim-slides ≤ 5.3.1 (not recommended).
- v5.5.4 fixed `av>=14` compat, i.e. `manim>=0.19.2`.
- Release **5.6.0's own lockfile resolves ManimCE 0.19.0/0.19.1/0.19.2 only.** ManimCE 0.20
  (2026-02) and **0.21.0 (2026-08) postdate the release**; 0.21 appears only in main's
  `uv.lock`. See §5 for the concrete breakage found.

### 1.5 Export formats (`manim-slides convert`)

`Converter.from_string` (`convert.py:172-181`): `html → RevealJS`, `zip → HtmlZip`,
`pptx → PowerPoint`, `pdf → PDF`. `--to auto` (default) infers from the destination suffix
and falls back to HTML with a warning.

```bash
# reveal.js HTML + sibling assets folder
manim-slides convert Demo out/demo.html
# fully self-contained single file (videos as data: URIs, reveal.js inlined)
manim-slides convert --one-file --offline Demo out/demo.html
# zipped HTML bundle
manim-slides convert --to=zip Demo out/demo.zip
# PowerPoint with embedded, autoplaying videos
manim-slides convert --to=pptx Demo out/demo.pptx
# static PDF fallback (one page per slide)
manim-slides convert --to=pdf -cframe_index=last Demo out/demo.pdf
# inspect available options for a format / dump the Jinja template
manim-slides convert --to=html --show-config
manim-slides convert --show-template
```

Other `convert` flags: `--folder <dir>` (default `slides`), `--open`,
`-c<key>=<value>` (repeatable config options), `--use-template FILE|NAME`
(built-ins: `revealjs.html`, `firebase_sync.html`), `--revealjs-assets-timeout 10.0`,
`--flush-revealjs-cache`, `--disable-revealjs-cache`, `-v/--verbosity`.

**HTML (reveal.js) structure** — `manim_slides/templates/revealjs.html`, rendered with Jinja2:

- reveal.js **6.0.1** by default, from `https://cdn.jsdelivr.net/npm/reveal.js@{version}`
  (`cdn_url` is configurable — cdnjs and unpkg documented in the field description).
- Each slide is a `<section data-background-video="assets/<hash>.mp4" data-background-color=…>`;
  looping slides get `data-background-video-loop`; `auto_next` slides get
  `data-autoslide="<duration_ms>"`; vertical slides are wrapped in a parent `<section>` stack.
- Notes render as `<aside class="notes" data-markdown>` and pull in reveal's markdown plugin
  only when at least one slide has notes.
- SPACE is rebound to play/pause the current slide's video.
- `--one-file` inlines each video as a `data:video/mp4;base64,…` URI, split across multiple
  `<source>` elements and re-joined by JS at runtime (works around per-attribute size limits).
- `--offline` downloads reveal.js CSS/JS into the assets dir (or inlines them with
  `--one-file`), with a persistent cache under `platformdirs.user_cache_path("manim-slides")/revealjs<version>`.
- ~70 reveal.js options are exposed as `-c<key>=<value>`, including `controls`, `progress`,
  `slide_number`, `hash`, `transition`, `background_size`, `loop`, `auto_slide`, `show_notes`,
  `width`, `height`, `margin`, `min_scale`/`max_scale`, `title`, and **`embedded`**.
  Themes (`reveal_theme`): black (default), white, league, beige, sky, night, serif, simple,
  solarized, blood, moon, black-contrast, white-contrast, dracula.

**Can the HTML be embedded in an existing slideshow?** Yes, two ways:

```html
<!-- documented approach: iframe with 16:9 padding box -->
<div style="position:relative;padding-bottom:56.25%;">
  <iframe style="width:100%;height:100%;position:absolute;left:0;top:0;"
          frameborder="0" allowfullscreen allow="autoplay" src="demo.html"></iframe>
</div>
```

```bash
# or make the deck itself embeddable inside a host page's DOM
manim-slides convert -cembedded=true -ccontrols=false Demo fragment.html
```

`embedded: true` makes reveal.js size itself from its `.reveal` root instead of the viewport
(call `Reveal.layout()` if the container resizes outside a window resize). For dropping a
single animation into someone else's reveal.js/Slidev deck, an iframe or a bare
`<video src=… loop muted autoplay>` is simpler than embedding a whole deck.

**PPTX** (`convert.py:887-975`, python-pptx): blank layout, slide size from `width`/`height`
config (default 1280×720 — **set these to match your render resolution**), one video shape
per slide at `left`/`top`, `poster_frame_image` defaults to the slide's *first* frame (avoids
inter-slide blinking), autoplay injected by patching the `p:timing` XML with `delay=0`, and
`repeatCount=indefinite` for looping slides. Speaker notes land in `notes_slide`. Marked
**experimental** in the docs w.r.t. PowerPoint/LibreOffice version support.

**PDF** (`convert.py:816-848`): grabs one frame per slide (`-cframe_index=last|first`,
default `last`) via PyAV and saves a multi-page PDF with PIL at `-cresolution=100.0` DPI.
Pure static — no animation.

### 1.6 Dependencies, Qt, headless

Hard deps (`pyproject.toml`): `av>=9`, `beautifulsoup4`, `click`, `click-default-group`,
`jinja2`, `lxml`, `numpy`, `pillow`, `platformdirs`, `pydantic>=2`, `pydantic-extra-types`,
`python-pptx`, `qtpy`, `requests`, `rich`, `rtoml`, `tqdm`.

**Qt**: `qtpy` is a hard dep but is only a shim — no PyQt6/PySide6 binding is installed
unless you ask for the `pyqt6` / `pyside6` extra. Verified by module-level import scan:
`convert.py` imports **no** Qt; `config.py` defers `from qtpy.QtCore import Qt` into a
function (`key_id`, only reached when a `Config()`/`Keys()` is constructed);
`present/__init__.py` defers `qtpy` + `qt_utils` into the command body (line 294).
→ **`manim-slides render` and `manim-slides convert` run with no Qt binding and no display.**
Only `manim-slides present` (the live Qt player) needs a binding and a screen.

**Headless / Docker / CI** — what the project itself does:

- CI (`.github/workflows/tests.yml`): `QT_QPA_PLATFORM=offscreen`, `DISPLAY=:99` with
  `nohup Xvfb :99 &`; system packages `build-essential python3-dev libcairo2-dev
  libpango1.0-dev ffmpeg freeglut3-dev xvfb`. Matrix: Python 3.10–3.14 × macOS/Ubuntu/Windows.
- `docker/Dockerfile`: `python:3.14-slim`, builder installs `libcairo2-dev libpango1.0-dev
  libegl-dev` + a trimmed TeX Live; runtime needs only `libcairo2 libpango-1.0-0
  libpangocairo-1.0-0 libpangoft2-1.0-0 libffi8 libegl1 libgl1 ghostscript fonts-noto-core
  fontconfig`. Notably **no ffmpeg binary** — PyAV bundles its own ffmpeg libs in `av.libs/`.
  (You still want a real `ffmpeg` binary in *our* image for the GIF post-processing in §4.)

For our pipeline: install `manim-slides[manim]` (no Qt extra) in the render container.
Add `ffmpeg`. Nothing needs a display.

---

## 2. Native Manim GIF & section output

### 2.1 CLI flags (ManimCE 0.19.x; verified against v0.19.2 source)

```
--format [png|gif|mp4|mov|webm]     # default mp4
-q, --quality [l|m|h|p|k]           # 854x480@15 / 1280x720@30 / 1920x1080@60 / 2560x1440@60 / 3840x2160@60
-r, --resolution "W,H"
--fps / --frame_rate FLOAT
-t, --transparent                   # == background_opacity 0
-s, --save_last_frame               # PNG of final frame; forces write_to_movie=False
--save_sections                     # per-section videos + JSON index
-o, --output_file NAME
--media_dir PATH                    # default ./media
-c, --background_color COLOR
--renderer [cairo|opengl]
-n, --from_animation_number A[,B]
--disable_caching / --flush_cache
-g, --save_pngs                     # deprecated frame dump
```

Output layout (`manim/_config/default.cfg`):

```
media/
├── videos/<module>/<quality>/               # e.g. 1080p60
│   ├── <Scene>.mp4
│   ├── sections/
│   │   ├── <Scene>_0000_autocreated.mp4
│   │   ├── <Scene>_0001_<name>.mp4
│   │   └── <Scene>.json                     # section index
│   └── partial_movie_files/<Scene>/*.mp4
├── images/<module>/<Scene>.png
├── Tex/  texts/  logs/
```

### 2.2 `--format gif` — what actually happens, and why not to use it

`SceneFileWriter.combine_files(..., create_gif=True)` (v0.19.2 `scene_file_writer.py:649-702`,
identical in `main`):

```python
output_stream = output_container.add_stream(codec_name="gif")
output_stream.pix_fmt = "rgb8"          # <-- destroys the optimised palette
if config.transparent:
    output_stream.pix_fmt = "pal8"
...
palettegen = graph.add("palettegen", "stats_mode=diff")
paletteuse = graph.add("paletteuse", "dither=bayer:bayer_scale=5:diff_mode=rectangle")
```

`rgb8` is ffmpeg's fixed 3:3:2 RGB palette. paletteuse produces good `pal8` frames and the
encoder then re-quantises them to 256 *fixed* colours. Measured on a 5 s 1920×1080 flat-colour
clip (Appendix A.2):

| variant | size | SSIM vs source | distinct colours, frame 10 |
|---|---|---|---|
| manim's chain forced to `rgb8` (= what you get) | 3666.5 KB | 0.9823 | **60** |
| same chain with `pal8` | 1354.6 KB | **0.9968** | **245** |

So the native GIF is simultaneously worse-looking and 2.7× bigger. Other facts:

- Default GIF filename carries the version: `media/videos/<module>/<q>/<Scene>_ManimCE_v0.19.2.gif`
  (`add_version_before_extension`, skipped when `-o` is given).
- `--format gif` does **not** change `movie_file_extension` (stays `.mp4`), so partial movie
  files and **section videos remain MP4** — `--format gif --save_sections` gives you MP4
  sections plus one whole-scene GIF. It does **not** give per-section GIFs.
- Audio is skipped for gif (`config.format != "gif"` guard).
- **Looping**: no loop count is set; ffmpeg's GIF muxer defaults to `loop=0` = infinite. So
  Manim GIFs loop forever, which is what you want for a slide.
- **Transparency**: `-t` + `--format gif` sets `pix_fmt=pal8`, but `-t` also flips
  `movie_file_extension` to `.mov` (qtrle/argb) and the palettegen chain has no explicit
  `alpha_threshold` on paletteuse. Unvalidated and fragile — do not rely on it.

### 2.3 Quality/size tradeoffs and the ffmpeg recipes that actually work

Measured on the same clip, 720×406 @ 15 fps (Appendix A.1):

| recipe | size | SSIM |
|---|---|---|
| single-pass, no palette | 120.0 KB | 0.9823 |
| 2-pass palette, `dither=bayer:bayer_scale=5` | 189.7 KB | 0.9923 |
| manim's chain (`stats_mode=diff` + bayer) | 216.2 KB | 0.9922 |
| **`max_colors=64`, `dither=none`** | **152.2 KB** | **0.9923** |

On a gradient clip (where dithering is supposed to pay off):

| recipe | size | SSIM |
|---|---|---|
| `max_colors=64`, `dither=none` | 3300 KB | 0.99428 |
| `stats_mode=diff` + bayer | 8877 KB | 0.99431 |
| default palettegen + `sierra2_4a` | 7123 KB | 0.99584 |

→ **Default to `dither=none`.** Dithering injects per-frame noise that defeats GIF's
inter-frame compression; for flat Manim output it buys nothing, and even on gradients it
costs 2–2.7× size for a rounding error of quality. Reserve `dither=bayer:bayer_scale=5`
for scenes with large smooth gradients where banding is visibly objectionable.

**Canonical GIF recipe (validated):**

```bash
ffmpeg -y -i in.mp4 \
  -filter_complex "fps=20,scale=960:-2:flags=lanczos,split[a][b];\
[a]palettegen=max_colors=128:stats_mode=diff[p];\
[b][p]paletteuse=dither=none:diff_mode=rectangle:new=1" \
  -loop 0 out.gif
```

Levers, in order of effect on size: **duration → fps → resolution → max_colors → dither**.
`stats_mode=diff` + `new=1` + `diff_mode=rectangle` give a per-scene-change palette and
rectangle-only frame updates, which is exactly right for Manim (static background, small
moving region). Practical targets: 960×540 @ 20 fps for a slide-filling GIF; 640×360 @ 15 fps
if you need < 1 MB; hard-cap clip length at ~10 s.

**Transparency (validated, Appendix A.3):**

- `manim -t` → `.mov` / `qtrle` / `argb`. Lossless, alpha perfect, **huge** (~850 KB/s at
  640×360). This is the reliable transparent master.
- `manim -t --format webm` → VP9 `yuva420p`. The encoder accepted yuva420p, but the alpha
  did **not** survive a decode round-trip on ffmpeg 4.4.2. Verify on your exact ffmpeg build
  before depending on it.
- Transparent **APNG** round-trips alpha perfectly. Transparent **animated WebP** encodes
  fine (ffmpeg can't decode animated WebP back, but browsers can).
- Transparent **GIF** is 1-bit only: `palettegen=reserve_transparent=1` +
  `paletteuse=alpha_threshold=128`. Fine for Manim (alpha is 0 or 255), useless for soft edges
  — antialiased glyph edges will get hard jaggies.

### 2.4 Sections: one scene → many clips

```python
class Demo(Scene):                       # plain Scene, no manim-slides
    def construct(self):
        self.next_section("Setup")       # name shows up in the filename + JSON
        self.play(...)
        self.next_section("Proof", skip_animations=False)
        self.play(...)
```

```bash
manim render -qh --save_sections demo.py Demo
```

Mechanics (v0.19.2 `scene_file_writer.py:122-129, 213-235, 830-845`, `scene/section.py`):

- A first section named **`autocreated`** is always created; empty sections are dropped
  (`finish_last_section`). So numbering is contiguous but names/indices shift if a section
  ends up empty — **always read the JSON index, never guess filenames.**
- Filename: `<output_name>_{i:04}_{name}{movie_file_extension}` →
  `Demo_0000_autocreated.mp4`, `Demo_0001_Setup.mp4`, …
- Index: `media/videos/<module>/<q>/sections/<Scene>.json`, a JSON **array** of objects with
  keys `name`, `type`, `video`, `codec_name`, `width`, `height`, `avg_frame_rate`,
  `duration`, `nb_frames`. `video` is relative to the sections dir.
- `DefaultSectionType.NORMAL == "default.normal"` is the only built-in type; `type_` is a
  free-form string for third-party consumers (Manim Editor used it for skip/loop semantics).
- Sections respect `movie_file_extension`, so `--format webm --save_sections` gives WebM
  sections; `--format png`/`-s` disables sections entirely (`write_to_movie` is False).
- `skip_animations=True` on a section means no video file is emitted for it (`video: null`,
  and it's omitted from the index).

**With manim-slides**, `next_slide()` *is* `next_section()`, so adding `--save_sections` to a
`manim-slides render` run costs one extra concat pass and gives you per-slide MP4s with
readable names, alongside the hash-named manim-slides files. Name your cuts:
`self.next_slide("DerivationStep2", notes="…")`.

---

## 3. Alternatives for stepped / looping output

### 3.1 Format matrix

| Format | Loops | Alpha | Audio | Seek/step | Size (rel.) | Where it works |
|---|---|---|---|---|---|---|
| MP4 / H.264 yuv420p | via player attr | no | yes | yes | **1.0** | everywhere: PPT, Keynote, browsers, Drive |
| WebM / VP9 | via player attr | yuva420p (fragile) | yes | yes | 0.95 | browsers; **not** PowerPoint/Keynote |
| GIF | intrinsic, infinite | 1-bit | no | no | 4–30× | **everywhere incl. Google Slides**, chat, README |
| Animated WebP | intrinsic (`-loop 0`) | yes (8-bit) | no | no | 1.5× | all modern browsers; **not** Office |
| APNG | intrinsic (`-plays 0`) | yes (8-bit) | no | no | 6× | browsers; **not** Office |
| PNG (`-s`) | — | yes | — | — | tiny | everywhere |

Measured on the same 5 s clip at 720p15: mp4 48 KB, webm 46 KB, webp 72 KB, best GIF 152 KB,
APNG 310 KB. GIF and APNG are 3–6× the cost of video for the same pixels.

### 3.2 PowerPoint

- Microsoft's recommended format is **MP4 / H.264 + AAC**; WMV/AVI/MPEG-2/3GPP support is
  deprecated as of PowerPoint 2505. WebM, APNG and animated WebP are **not** supported.
- Embedded (not linked) video is the default and is what `manim-slides convert --to=pptx`
  produces — the deck is self-contained and portable.
- Animated GIFs are inserted as pictures and **do** animate in slideshow mode; they're the
  no-brainer fallback if a video refuses to play on a conference laptop.
- Encode for maximum compatibility:
  ```bash
  ffmpeg -y -i in.mp4 -c:v libx264 -profile:v high -level 4.0 -pix_fmt yuv420p \
    -crf 20 -preset slow -movflags +faststart -an out_pptx.mp4
  ```
  (`yuv420p` matters — yuv444p/10-bit H.264 will not decode in Office.)
- Set `-cwidth=1920 -cheight=1080` on `convert --to=pptx` to match a 1080p render, otherwise
  you get a 1280×720 deck.

### 3.3 Google Slides

- Video insertion accepts **YouTube** and **Google Drive**; a direct local-file upload is only
  present in some editor versions, and the universal path is *upload the MP4 to Drive, then
  Insert → Video → Google Drive*. Drive-hosted video means the deck no longer works offline
  and breaks for viewers without file access.
- **Animated GIFs inserted as images animate in present mode and need no Drive round-trip.**
- → For a Google Slides presenter, **GIF is the primary deliverable**, MP4-on-Drive is the
  upgrade path, and a PNG is the offline fallback.

### 3.4 Keynote

Accepts MP4/H.264 and MOV natively (including alpha via ProRes 4444 / qtrle `.mov`), plus
animated GIF. Keynote is the only mainstream deck tool that handles the transparent `.mov`
Manim emits with `-t`.

### 3.5 Web decks

- **reveal.js**: what manim-slides emits. Per-slide `data-background-video` + `-loop`
  + `data-autoslide`. `embedded: true` for in-page embedding.
- **Slidev**: Vue-based; drop a plain `<video src="/anim.mp4" autoplay loop muted playsinline />`
  into a slide, or a Vue component. Mature video support.
- **Marp**: weakest. No first-class video syntax (open upstream issues since 2018); you hand-write
  `<video>` HTML, autoplay/pause-on-slide-change is unreliable and export to HTML has known
  Chrome rendering problems. **Use GIF with Marp.**
- **Manim Editor** (`ManimCommunity/manim_editor`, MIT, 361★): a section-driven web presenter —
  conceptually the closest alternative to manim-slides for section output. **Last commit
  2024-07-17**; effectively unmaintained. Do not build on it.

### 3.6 Static fallback

`manim render -s --format png demo.py Demo` → `media/images/<module>/<Scene>.png`, exact
renderer output, but it forces `write_to_movie=False`, so it's a **second render pass**.
Cheaper: pull the frame out of the MP4 you already have.

```bash
# last frame (final state of the animation)
ffmpeg -y -sseof -0.1 -i in.mp4 -update 1 -frames:v 1 last.png
# representative frame for a thumbnail/card
ffmpeg -y -i in.mp4 -vf "thumbnail=100,scale=1280:-2" -frames:v 1 thumb.png
```
Caveat: these go through yuv420p, so colours can shift by ~1 LSB vs a native `-s` PNG.
Irrelevant for thumbnails; use a real `-s` pass if a PNG is the *shipped* artifact.

### 3.7 Recommendation by audience

| Presenter situation | Give them |
|---|---|
| PowerPoint, wants stepping | `.pptx` from `manim-slides convert --to=pptx` |
| PowerPoint, wants one animation on an existing slide | per-section `.mp4` (H.264 yuv420p) + the `.gif` as backup |
| Google Slides | **per-section `.gif`** + `.png` fallback |
| Keynote | per-section `.mp4`, or transparent `.mov` for overlays |
| Laptop-driven live talk, no internet | `manim-slides convert --one-file --offline` HTML, or the Qt `present` player |
| Web dashboard / our own UI | multi-file reveal.js HTML (**not** `--one-file`) + `.mp4` + poster `.png` |
| Chat / README / Slack / issue tracker | `.gif` |
| Print / handout / projector failure | `.pdf` from `convert --to=pdf` |

---

## 4. Recommended output contract

### 4.1 Artifact set — produced for every generated scene

```
out/<scene_id>/
├── manifest.json                     # our index; see 4.3
├── master/
│   ├── <Scene>.mp4                   # 1920x1080@60, H.264 yuv420p, +faststart   [manim]
│   └── <Scene>.pptx.mp4              # PPT-safe re-encode: high@4.0, crf 20, -an [ffmpeg]
├── sections/
│   ├── 0000_autocreated.mp4          # per-slide clips                            [manim --save_sections]
│   ├── 0001_<name>.mp4
│   ├── 0001_<name>.gif               # per-slide GIF, 960x540@20, dither=none      [ffmpeg]
│   ├── 0001_<name>.png               # last frame of that section                  [ffmpeg]
│   └── index.json                    # manim's section index, copied verbatim
├── stills/
│   ├── thumb.png                     # 1280w representative frame                  [ffmpeg]
│   └── last.png                      # final frame of the whole scene              [ffmpeg]
├── web/
│   ├── <Scene>.html + <Scene>_assets/   # reveal.js, multi-file (dashboard)        [manim-slides convert]
│   └── <Scene>.onefile.html             # --one-file --offline (hand to presenter) [manim-slides convert]
├── deck/
│   ├── <Scene>.pptx                                                                [manim-slides convert --to=pptx]
│   └── <Scene>.pdf                   # static fallback, one page per slide         [manim-slides convert --to=pdf]
└── raw/
    ├── slides/<Scene>.json           # manim-slides PresentationConfig
    └── slides/files/<Scene>/*.mp4    # hash-named per-slide + reversed clips
```

Optional, on request only (they're expensive):
`<Scene>.webm` (VP9, for a web-first dashboard), `<Scene>.mov` (`-t`, transparent overlay),
`<Scene>.webp` (animated, transparent, browser-only).

### 4.2 Pipeline — exact commands

```bash
set -euo pipefail
SCENE=Demo; FILE=scene.py; OUT=out/$SCENE
mkdir -p "$OUT"/{master,sections,stills,web,deck,raw}

# ---- 1. ONE render. Produces master mp4 + section mp4s + manim-slides slides/ tree.
manim-slides render -qh --save_sections --media_dir "$OUT/media" "$FILE" "$SCENE"
VID="$OUT/media/videos/$(basename "${FILE%.py}")/1080p60"

cp "$VID/$SCENE.mp4"                    "$OUT/master/$SCENE.mp4"
cp "$VID/sections/$SCENE.json"          "$OUT/sections/index.json"
cp "$VID"/sections/"$SCENE"_*.mp4       "$OUT/sections/"
cp -r slides                            "$OUT/raw/"

# ---- 2. Derivatives from the section clips (never re-render).
for f in "$OUT"/sections/"$SCENE"_*.mp4; do
  b="${f%.mp4}"
  ffmpeg -y -loglevel error -i "$f" \
    -filter_complex "fps=20,scale=960:-2:flags=lanczos,split[a][b];\
[a]palettegen=max_colors=128:stats_mode=diff[p];\
[b][p]paletteuse=dither=none:diff_mode=rectangle:new=1" -loop 0 "$b.gif"
  ffmpeg -y -loglevel error -sseof -0.1 -i "$f" -update 1 -frames:v 1 "$b.png"
done

# ---- 3. Stills + PPT-safe master.
ffmpeg -y -loglevel error -i "$OUT/master/$SCENE.mp4" \
  -vf "thumbnail=100,scale=1280:-2" -frames:v 1 "$OUT/stills/thumb.png"
ffmpeg -y -loglevel error -sseof -0.1 -i "$OUT/master/$SCENE.mp4" \
  -update 1 -frames:v 1 "$OUT/stills/last.png"
ffmpeg -y -loglevel error -i "$OUT/master/$SCENE.mp4" \
  -c:v libx264 -profile:v high -level 4.0 -pix_fmt yuv420p -crf 20 -preset slow \
  -movflags +faststart -an "$OUT/master/$SCENE.pptx.mp4"

# ---- 4. manim-slides conversions (all read slides/, all headless, no Qt).
manim-slides convert "$SCENE" "$OUT/web/$SCENE.html" \
  -cslide_number=true -ccontrols=true -ctransition=none -creveal_theme=black
manim-slides convert --one-file --offline "$SCENE" "$OUT/web/$SCENE.onefile.html"
manim-slides convert --to=pptx -cwidth=1920 -cheight=1080 "$SCENE" "$OUT/deck/$SCENE.pptx"
manim-slides convert --to=pdf  -cframe_index=last        "$SCENE" "$OUT/deck/$SCENE.pdf"
```

Cost profile: step 1 dominates (the actual render + per-slide reverse-video generation).
Steps 2–4 are cheap, CPU-only, and trivially parallel. Set `skip_reversing = True` on the
`Slide` subclass if backwards navigation in the Qt player isn't a requirement — it removes an
entire reverse-encode pass per slide.

### 4.3 `manifest.json`

Make this the pipeline's contract; everything downstream (review stage, dashboard, packaging)
reads it and nothing else globs the filesystem.

```json
{
  "scene_id": "demo-0001",
  "scene_class": "Demo",
  "manim_version": "0.19.2",
  "manim_slides_version": "5.6.0",
  "render": {"quality": "1080p60", "width": 1920, "height": 1080, "fps": 60,
             "duration_s": 42.5, "background_color": "#000000"},
  "artifacts": {
    "master_mp4":  "master/Demo.mp4",
    "pptx_mp4":    "master/Demo.pptx.mp4",
    "thumbnail":   "stills/thumb.png",
    "last_frame":  "stills/last.png",
    "html":        "web/Demo.html",
    "html_onefile":"web/Demo.onefile.html",
    "pptx":        "deck/Demo.pptx",
    "pdf":         "deck/Demo.pdf"
  },
  "sections": [
    {"index": 1, "name": "Setup", "duration_s": 8.2, "loop": false,
     "notes": "Speaker note text",
     "mp4": "sections/Demo_0001_Setup.mp4",
     "gif": "sections/Demo_0001_Setup.gif",
     "png": "sections/Demo_0001_Setup.png"}
  ]
}
```

Join key: the section `name` from `next_slide("Setup", ...)` links Manim's
`sections/index.json` entry to the manim-slides slide at the same ordinal in
`slides/<Scene>.json` (both are produced by the same `next_slide()` call, in order).
**Enforce unique, non-empty names on every cut in the generated code** — it's the only thing
that makes the two indices joinable and the filenames human-readable, and it costs the LLM
one extra string argument.

### 4.4 Rules for the code generator

1. Always subclass `Slide` / `ThreeDSlide`, never `Scene`.
2. Every cut is `self.next_slide("<UniquePascalName>", notes="…")`.
3. `self.next_slide(loop=True)` for any idle/ambient animation — it's the one feature that
   maps cleanly onto *all four* outputs (Qt, reveal.js, PPTX, and GIF's intrinsic looping).
4. Set `self.wait_time_between_slides = 0.1` in `construct` to kill the 1-frame flash.
5. Play at least one animation between cuts — `PreSlideConfig` raises if a slide has zero
   animations and no `src`.
6. No `-t`/transparent unless the artifact is explicitly an overlay; it silently switches the
   container to `.mov` and blows up file size.

---

## 5. Version compatibility — the constraint that bites

| Component | Pin | Why |
|---|---|---|
| Python | **3.11** | manim 0.21 needs ≥3.11; manim-slides main needs ≥3.10; 3.11 satisfies both and is what manim-slides' `.python-version` says |
| ManimCE | **0.19.2** | the newest version manim-slides 5.6.0's own lockfile resolves; 5.5.4 explicitly fixed `av>=14` / `manim>=0.19.2` |
| manim-slides | **5.6.0** `[manim]` extra, no Qt extra | latest release; `render`+`convert` need no Qt |
| ffmpeg | ≥ 4.4 binary in the image | for all GIF/thumbnail/re-encode work (PyAV's bundled libs are not on `$PATH`) |

Concrete facts behind that pin:

- **ManimCE 0.18.x is out.** manim-slides 5.4.0 raised the floor to `manim>=0.19`. Supporting
  0.18 means manim-slides ≤ 5.3.1 — an old, unsupported combination. Don't.
- **ManimCE 0.21.0 (2026-08) is not covered by any manim-slides release.** 5.6.0 shipped
  2026-04 and locks 0.19.x. 0.21 appears only in main's `uv.lock`.
- **Found a concrete 0.21 break:** `manim_slides/slide/manim.py:Slide.render()` calls
  `self.renderer.file_writer.flush_cache_directory()`. That method (and `clean_cache`) **no
  longer exists** on `SceneFileWriter` in manim `main`/0.21 — the writer was refactored around
  `_SceneFileWriterSettings` / `output_spec` / `output_plan`. It only fires when
  `--flush_cache` is passed, so it's a narrow path, but it proves the 0.21 surface has moved
  under manim-slides. `partial_movie_files` and `max_files_cached` do survive.
- If you must be on 0.20/0.21, install manim-slides from git `main` and pin the commit, and
  smoke-test `render → convert --to=html/pptx/pdf` in CI on every bump.
- **Insulation:** make the manim-slides step *optional* in the pipeline. Steps 1–3 of §4.2
  (render, sections, GIF, stills) depend only on ManimCE + ffmpeg and will survive any
  manim-slides breakage; only §4.2 step 4 (HTML/PPTX/PDF) depends on manim-slides. If
  manim-slides lags a ManimCE release, you degrade to "mp4 + gif + png + per-section clips"
  rather than failing the run.

---

## Appendix A — measured data

Environment: ffmpeg 4.4.2-0ubuntu0.22.04.1, Linux x86-64.
Artifacts kept at `/tmp/claude-0/-root-aisoc-manim-engineer/6bb3163b-6c17-4d10-8cd5-4b79b2c9a27a/scratchpad/research/bench/`.

**A.1** — 5 s, 1920×1080@30 synthetic Manim-like clip (flat background, one moving disc, one
text line). Source H.264 crf 18 = 76.4 KB. All GIFs at 720×406@15. SSIM vs a lossless
720×406@15 reference.

```
naive_1080p30.gif      613.5 KB   —
naive_720p15.gif       120.0 KB   0.982347
nodither_720p15.gif    152.2 KB   0.992255   (max_colors=64, dither=none)
two_pass_720p15.gif    189.7 KB   0.992267   (2-pass palette, bayer 5)
manimstyle_720p15.gif  216.2 KB   0.992183   (stats_mode=diff, bayer 5, diff_mode=rectangle)
out_720p15.webp         72.0 KB   —          (libwebp_anim q=70)
out_720p15.apng        310.4 KB   —
out_720p.mp4            48.0 KB   —          (1280w, x264 crf 23, faststart)
out_720p.webm           45.7 KB   —          (1280w, vp9 crf 34)
```

Gradient clip (1280×720, `gradients` lavfi source), same 720×406@15 GIF settings:

```
g_nodither.gif   3300.5 KB   0.994283
g_bayer.gif      8876.7 KB   0.994312
g_sierra.gif     7122.9 KB   0.995840
```

**A.2** — Manim's native GIF path reproduced at full 1920×1080@30, only `pix_fmt` varied:

```
manim_rgb8.gif   3666.5 KB   SSIM 0.982276   60 distinct colours in frame 10
manim_pal8.gif   1354.6 KB   SSIM 0.996805   245 distinct colours in frame 10
```

**A.3** — alpha round-trips (per-pixel alpha mean should be 89 for a 0.35 alpha source):

```
qtrle .mov (argb)         alpha mean 89.0   OK      1699 KB for 2 s @ 640x360
APNG (direct from filter) alpha mean 89.0   OK
VP9 .webm (yuva420p)      alpha mean 255.0  LOST on ffmpeg 4.4.2 decode (encoder did accept yuva420p)
GIF (reserve_transparent=1, alpha_threshold=128)   binary-only, as expected
animated WebP             encodes; ffmpeg 4.4 cannot decode it back (browser-only verification)
```

Validated command recipes (all exit 0, outputs inspected):
```
rec.gif        357.2 KB   fps=20,scale=960,max_colors=128,stats_mode=diff,dither=none,new=1
thumb.png       15.8 KB   -vf "thumbnail=100,scale=1280:-2" -frames:v 1
last.png        21.1 KB   -sseof -0.1 -update 1 -frames:v 1
pptx_safe.mp4   75.1 KB   libx264 high@4.0 yuv420p crf 20 preset slow +faststart -an
```

## Appendix B — source references

Local clone: `/tmp/claude-0/-root-aisoc-manim-engineer/6bb3163b-6c17-4d10-8cd5-4b79b2c9a27a/scratchpad/research/repos/manim-slides`
(commit `5e71dd5`, 2026-09-11).

- `manim_slides/convert.py` — converter registry (`:172`), RevealJS config fields (`:340-597`),
  `RevealJS.convert_to` (`:622`), `HtmlZip` (`:790`), `PDF` (`:816`), `PowerPoint` (`:887`),
  pptx autoplay XML hack (`:873`), `convert` CLI (`:1144`).
- `manim_slides/slide/base.py` — `next_slide` docstring (`:357`), `_save_slides` (`:591`),
  output folder `./slides` (`defaults.py`).
- `manim_slides/slide/manim.py` — `Slide.next_slide → Scene.next_section` (`:135`),
  `Slide.render` + `flush_cache_directory` call (`:151`).
- `manim_slides/config.py` — `BaseSlideConfig` (`:167`), `SlideConfig` (`:314`),
  `PresentationConfig` (`:327`), lazy Qt import in `key_id` (`:51`).
- `manim_slides/templates/revealjs.html` — section/video markup (`:41-62`), base64 splitter (`:304`).
- `.github/workflows/tests.yml` — headless env (`QT_QPA_PLATFORM=offscreen`, Xvfb `:99`).
- `docker/Dockerfile` — runtime package list, "no ffmpeg needed, PyAV bundles it".

ManimCE v0.19.2 (downloaded to `scratchpad/research/sfw_0192.py`, `utils_0192.py`):
- `scene_file_writer.py:131` `init_output_directories`, `:213` `next_section`,
  `:649-702` GIF/`rgb8`, `:722` `combine_to_movie`, `:830-845` `combine_to_section_videos`,
  `:548-556` transparent codec selection.
- `_config/utils.py:1044` `format` setter (png|gif|mp4|mov|webm), `:1429` `resolve_movie_file_extension`.
- `_config/default.cfg` — media dir layout, `sections_dir = {video_dir}/sections`.
