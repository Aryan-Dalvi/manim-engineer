# Automated Quality Verification of LLM-Generated Manim Animations

Research scout report. Everything marked **[measured]** was run against a real
ManimCE **0.19.0** install on this machine (Linux, Python 3.10, TeX Live + ffmpeg present).
Working code lives in `research/verified/` next to this file and runs as-is.

---

## 0. The headline finding

**You do not need to render to check layout.** Manim's `Scene(skip_animations=True)`
path executes `construct()` end to end, applies every animation's final state to the
mobject tree, and — because `Scene.get_time_progression()` collapses to
`times = [run_time]` when `skip_animations` is set — does exactly **one** tick per
`play()` instead of `run_time × fps` ticks
([scene.py](https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/scene/scene.py#L1092)).
Swap in a no-op renderer and `DummySceneFileWriter` and there is zero rasterization,
zero encoding, zero disk I/O.

**[measured]** on a 20.5 s scene (Axes + plot + 11 `play()` calls):

| mode | wall | max RSS |
|---|---|---|
| **in-process layout probe (no render)** | **0.29 s** | ~160 MB |
| `manim -ql -s` (save_last_frame) | 0.76 s | 162 MB |
| `manim -ql --dry_run` | 1.17 s | 162 MB |
| `manim -ql` (854×480@15) | 2.06 s | 335 MB |
| `manim -qm` (1280×720@30) | 5.01 s | 554 MB |
| `manim -qh` (1920×1080@60) | 19.34 s | **1.68 GB** |

That is a **66× speedup over `-qh`** and **7× over `-ql`** for the check that catches
the most common defect class (overlap / off-frame / unreadable text). It also matches
the only published measurement I found: SGA reports its partial-execution geometric
check at **<5 s/iteration vs 30–90 s for a VLM critic that must render first — 6×–18×
per-iteration speedup** ([arXiv:2607.18116](https://arxiv.org/abs/2607.18116)).

Design consequence: **put geometry before pixels.** Tier 2 (render + VLM) should only
ever see candidates that already passed a deterministic geometric gate.

---

## 1. Tiered gate design

| Tier | Gate | Latency **[measured]** | Blocking? | Fires on |
|---|---|---|---|---|
| **0** | Parse → sandbox lint → structure → API-existence → LaTeX precompile → duration bound | **0.25 s** (+0.5 s manim import, amortized) | fatal ⇒ reject, no render | hallucinated symbols, dead APIs, uncompilable TeX, forbidden I/O |
| **1** | Sandboxed layout probe: run `construct()` with no rendering, sample bbox tree at every animation boundary | **0.3 s** for a 20 s scene | fatal ⇒ reject | runtime exceptions, overlap, off-frame, text < 24 px, timeout/OOM |
| **2** | `-ql` render (854×480@15) → per-section last frames + contact sheet → VLM critique | **2 s render + 1 VLM call** | score-gated | pedagogy, aesthetics, plan adherence, anything geometry can't see |
| **3** | Human review | minutes | ship/no-ship | final 5–10% |

Tier 0+1 together cost **~0.6 s** and need no GPU, no video, no model call. Budget
them as "free" and run them on every candidate and every repair iteration.

---

## 2. Tier 0 — static / deterministic, pre-render

Full implementation: `research/verified/static_checks.py` (runs in 0.25 s).

### 2.1 Parse

`ast.parse(src)` → `SyntaxError` carries `.lineno`/`.msg`. Fatal, no repair prompt
needed beyond the message.

### 2.2 Build a ground-truth API surface by introspection

The single most valuable static check. Don't pattern-match a hand-written banned list —
**introspect the installed module** and diff against it. This is exactly the
"dynamically-generated Knowledge Base built via library introspection" of
[arXiv:2601.19106](https://arxiv.org/abs/2601.19106), which reports **100% precision /
87.6% recall / F1 0.934** on 200 Python snippets and auto-corrects **77.0%** of what it finds.

```python
import inspect, manim

def manim_surface():
    names = {n for n in dir(manim) if not n.startswith("_")}
    members = {n: {a for a in dir(getattr(manim, n)) if not a.startswith("__")}
               for n in names if inspect.isclass(getattr(manim, n))}
    return {"names": names, "members": members}
```

Three rules on top of it:

1. **Unknown capitalized `Name` loads** → `ShowCreation`, `ColorfulBlob` are not in
   `dir(manim)` ⇒ fatal.
2. **Attribute on a variable of known class.** Track `var = SomeManimClass(...)`
   assignments, then check `var.attr ∈ members[SomeManimClass]`.
3. **The `.animate` proxy** — the highest-yield special case. `mob.animate.foo()`
   resolves through `_AnimationBuilder.__getattr__ → getattr(self.mobject.target, name)`
   ([mobject.py:3070](https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/mobject/mobject.py#L3070)),
   so `foo` must be a real method of `type(mob)`. In the AST the base is
   `Attribute(value=Attribute(value=Name, attr='animate'))` — unwrap one level:

```python
if isinstance(node, ast.Attribute):
    v = node.value
    if isinstance(v, ast.Attribute) and v.attr == "animate" and isinstance(v.value, ast.Name):
        v = v.value                      # mob.animate.shift_right -> base is `mob`
    if isinstance(v, ast.Name):
        cls = assigned.get(v.id)
        if cls and node.attr not in SURFACE["members"][cls]:
            emit_fatal(f"{cls} has no attribute '{node.attr}'", suggest(node.attr, cls))
```

Always attach `difflib.get_close_matches(name, pool, n=3, cutoff=0.7)`. "Did you mean:
`get_right`?" is the *admissible alternatives* field that the repair literature says
carries almost all of the fix-rate gain (§7).

**[measured]** on a deliberately broken file, Tier 0 emits, in 0.25 s:

```
[fatal] sandbox    L2    forbidden import 'os'
[fatal] legacy-api L10   'ShowCreation' is 3b1b-manim / removed API  Renamed to Create in ManimCE.
[fatal] api        L10   'ShowCreation' is not exported by manim 0.19.0
[fatal] api        L11   Square has no attribute 'shift_right'  Did you mean: get_right?
[fatal] api        L12   'ColorfulBlob' is not exported by manim 0.19.0
[fatal] latex      L8    MathTex('\frac{1}{2') does not compile: ! File ended while scanning use of \frac .
```

Known hole: attributes on objects whose class you couldn't infer (returned from a
function, element of a list). Downgrade those to `warn` or skip — Tier 1 executes the
code anyway and will raise the real `AttributeError`.

### 2.3 Legacy-API blocklist

Introspection misses *renames*, because the LLM's mental model is 3b1b-manim / ManimGL.
A small regex blocklist with the replacement in the message is worth it:

| banned | why |
|---|---|
| `ShowCreation` | → `Create` |
| `TexMobject` / `TextMobject` | → `MathTex` / `Tex` |
| `get_graph` | → `Axes.plot` |
| `ApplyMethod` | → `mob.animate.<method>()` |
| `CONFIG = {...}` | ManimGL only; CE uses `__init__` kwargs |

These are exactly the "Manim code hallucinations (nonexistent functions/modules)"
that TheoremExplainAgent names as one of its three dominant failure categories
([arXiv:2502.19400](https://arxiv.org/abs/2502.19400)).

### 2.4 Sandbox lint

Copy ManimAgent's list verbatim ([arXiv:2606.30296](https://arxiv.org/abs/2606.30296)):
reject imports of `os`, `subprocess`, `socket` (I'd add `sys`, `shutil`, `requests`,
`urllib`, `pathlib`, `ctypes`, `importlib`) and calls to `open`, `eval`, `exec`
(add `compile`, `__import__`, `input`). Also: reject any string literal ending in
`.png/.jpg/.svg/.mp3/.wav` — external assets that don't exist are a classic silent
generator failure, and TheoremExplainAgent's fix prompt has an explicit rule
"if external assets are referenced, remove them".

### 2.5 Structure

Also from ManimAgent: **a `Scene` subclass with the expected name must exist**, it must
define `construct`, and it must call `self.play` **at least twice** (fewer means the
model emitted a static slide). Cheap, catches a real failure mode.

### 2.6 LaTeX precompile

LaTeX errors are TheoremExplainAgent's second named failure category and they surface
*inside* the render, where the traceback is a `ValueError` five frames deep in
`tex_file_writing.compile_tex`. Pull them forward: extract every string literal passed
to `MathTex` / `Tex` / `Title` / `BulletedList` and compile each in a
`standalone` document before you ever construct a scene.

```python
_TEMPLATE = r"""\documentclass[preview]{standalone}
\usepackage[english]{babel}\usepackage{amsmath}\usepackage{amssymb}
\begin{document}
%s
\end{document}
"""
cp = subprocess.run(["latex", "-interaction=nonstopmode", "-halt-on-error",
                     "-output-directory", d, str(f)], capture_output=True, text=True)
if cp.returncode != 0:
    errs = [l for l in (Path(d)/"t.log").read_text(errors="ignore").splitlines()
            if l.startswith("!")][:3]      # manim's own heuristic, tex_file_writing.py:288
```

Wrap `MathTex` args as `$\displaystyle ...$`, leave `Tex` args alone. Manim itself
identifies errors by "lines beginning with `!`"
([tex_file_writing.py:288](https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/utils/tex_file_writing.py#L288)),
so use the same rule. ~0.2 s per snippet cold, effectively free warm. Only catches
literals, not f-strings/`.join()` — that's fine, it's an accelerator, not the only gate.

### 2.7 Duration bound from `run_time`

**The sum is wrong.** Animations inside one `play()` run *in parallel*:
`Scene.get_run_time()` is `max(a.run_time for a in animations)`, not the sum
([scene.py:1169](https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/scene/scene.py#L1169)).
The correct static estimate is:

```
duration ≈ Σ_over_play_calls  max(run_time of its animations, default 1.0)
         + Σ_over_wait_calls  (duration arg, default 1.0)
```

Defaults: `DEFAULT_WAIT_TIME = 1.0`, and `Animation.run_time` defaults to 1.0.
`AnimationGroup(lag_ratio=...)` breaks this (its own `run_time` is derived), so treat
the static number as a rough bound and take the exact figure from the Tier-1 probe,
which reads `self.duration` after each `play()`. **[measured]** static estimate 20.5 s,
probe 20.5 s, `ffprobe` on the rendered file 20.53 s — they agree.

Use it to fail fast on "the model wrote a 4-minute scene for a 20-second beat" and on
"the model wrote a 2-second scene" (`duration < 3 s` ⇒ warn).

---

## 3. Tier 1 — the layout probe (no render)

Full implementation: `research/verified/probe_lib.py` + `layout_checks.py` + `runner.py`.

### 3.1 Instrumenting the Scene

Three pieces:

```python
from manim.renderer.cairo_renderer import CairoRenderer
from manim.utils.testing._test_class_makers import DummySceneFileWriter   # ships with manim

class _NoOpRenderer(CairoRenderer):
    def update_frame(self, *a, **k): return
    def render(self, *a, **k): return
    def save_static_frame_data(self, *a, **k):
        self.static_image = None; return None
```

`DummySceneFileWriter` is manim's *own* test double — `add_partial_movie_file`,
`begin_animation`, `end_animation`, `combine_to_movie` are all no-ops
([_test_class_makers.py](https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/utils/testing/_test_class_makers.py)).
Reusing it means you inherit whatever the manim maintainers keep working.

Then subclass the candidate scene and wrap `play` / `next_section`:

```python
def probe(scene_cls):
    frames = []
    class _Probe(scene_cls):
        def __init__(self, **kw):
            super().__init__(renderer=_NoOpRenderer(file_writer_class=DummySceneFileWriter),
                             skip_animations=True, **kw)
            self._clock, self._section, self._i = 0.0, "default", 0
        def next_section(self, name="unnamed", *a, **k):
            self._section = name
            return super().next_section(name, *a, **k)
        def play(self, *args, **kw):
            label = ", ".join(type(a).__name__ for a in args[:3]) or "?"
            super().play(*args, **kw)          # animations run + finish() + clean_up_from_scene()
            self._clock += float(self.duration)
            frames.append(Keyframe(index=self._i, t=round(self._clock, 3),
                                   run_time=float(self.duration), section=self._section,
                                   anim=label, boxes=semantic_boxes(self)))
            self._i += 1
    with tempconfig({"dry_run": True, "disable_caching": True, "progress_bar": "none"}):
        _Probe().render()
    return frames
```

Why hook `play` and not `wait`: `Scene.wait()` is implemented as
`self.play(Wait(run_time=duration, ...))`
([scene.py:1242](https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/scene/scene.py#L1242)),
so wrapping `play` catches waits for free — **[measured]**, a scene with 3 `play()`s and
one `wait(2)` yields 4 keyframes.

**Version note.** This is the ManimCE **0.18/0.19** shape, where `Scene` owns
`self.renderer` and `Scene.render()` drives the loop. On **main / 0.21+** the loop moved
into a `Manager` (`Scene.play` → `self._get_manager().play(...)`), so the renderer-injection
constructor kwarg is gone. **Pin your manim version** — you are pinning it anyway for the
API-existence check in §2.2. If you must be version-agnostic, hooking `play`/`next_section`
on the Scene subclass still works on both; only the `renderer=` injection needs a branch.

### 3.2 Semantic boxes, not glyph boxes

`family_members_with_points()` decomposes a `Text` into one box **per glyph**.
**[measured]**, a 5-element scene produced **42 leaf boxes** and **26 bogus overlap
reports**. The fix is a semantic traversal: text mobjects are atomic; everything else
recurses one level into `submobjects`.

```python
TEXTUAL = (Text, MarkupText, Tex, MathTex, SingleStringMathTex)

def semantic_boxes(scene):
    boxes = []
    def emit(m, path, root):
        pts = m.get_all_points()
        if len(pts) == 0: return
        xy = np.asarray(pts)[:, :2]; lo, hi = xy.min(0), xy.max(0)
        boxes.append(Box(path, type(m).__name__, isinstance(m, TEXTUAL), root,
                         float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])))
    def walk(m, path, root):
        if isinstance(m, TEXTUAL) or not m.submobjects:
            emit(m, path, root); return
        for i, sub in enumerate(m.submobjects):
            walk(sub, f"{path}.{i}:{type(sub).__name__}", root)
    for i, top in enumerate(scene.mobjects):
        walk(top, f"m{i}:{type(top).__name__}", i)
    return boxes
```

`get_all_points()` returns every Bézier control point of the mobject and its family
(depth-first, may contain duplicates), so `min/max` over `[:, :2]` is a true AABB.
Do **not** use `mob.width`/`mob.height` for the box — they're derived from the same
points but you'd still need the center, and `get_center()` is the *bbox* center, not the
centroid, so mixing them is error-prone. One `min/max` pass is cheaper and unambiguous.

### 3.3 The semantic filter — the difference between a useful gate and noise

**[measured] without it: 26 findings on a perfectly good scene. With it: 0.**
An `Axes` legitimately overlaps its own arrow tips; a `Dot` legitimately sits on a
`ParametricFunction`; a `Brace` legitimately touches what it braces. SGA hits the same
wall and solves it with an object taxonomy Φ = {Text, Geom, Mark, Deco} plus a semantic
filter. Two rules get you most of the way:

```python
DECORATOR_KINDS = {"Dot","LabeledDot","SmallDot","ArrowTriangleFilledTip","ArrowTriangleTip",
  "ArrowSquareTip","ArrowCircleTip","StealthTip","Brace","BraceLabel","SurroundingRectangle",
  "BackgroundRectangle","Underline","Cross","Line","DashedLine","Arrow","DoubleArrow",
  "Vector","Angle","RightAngle","Tip"}

def reportable_pair(a, b):
    if a.root == b.root:  return False          # same top-level mobject: composed on purpose
    if a.kind in DECORATOR_KINDS or b.kind in DECORATOR_KINDS: return False
    return True
```

`root` = index of the top-level `scene.mobjects` entry the box descends from. Carry it
through the traversal.

### 3.4 The four geometric rules

Frame constants, from `default.cfg` + `ManimConfig`: `frame_height = 8.0`,
`aspect_ratio = pixel_width/pixel_height = 16/9`, so **`frame_width = 14.222222222222221`**;
origin at center, x ∈ [−7.111, 7.111], y ∈ [−4, 4]. **[measured]**, `config.frame_width`
prints `14.222222222222221`. (TheoremExplainAgent hard-codes exactly these numbers into
its codegen prompt and tells the model to stay inside x ∈ [−7, 7], y ∈ [−4, 4] — a 1.6%
margin. Use the same bound as a *lint*, and the real frame as the *gate*.)

**(a) Overlap.** AABB intersection, scored by *asymmetric coverage* — SGA's formulation:

```python
I  = max(0, min(a.x1,b.x1)-max(a.x0,b.x0)) * max(0, min(a.y1,b.y1)-max(a.y0,b.y0))
ρ  = I / min(a.area, b.area)
```
- `ρ > 0.30` ⇒ **high** severity (SGA's threshold)
- `0.10 < ρ ≤ 0.30` ⇒ medium
- both boxes textual ⇒ escalate to fatal at any `ρ > 0.10` (text-on-text is never intentional)

Emit the **minimum separation vector** with the finding — the shortest axis-aligned push
that clears the overlap. SGA feeds precisely this to the repair LLM:

```python
def msv(a, b):
    dx = min(a.x1-b.x0, b.x1-a.x0); dy = min(a.y1-b.y0, b.y1-a.y0)
    return (round(dx,2), 0.0) if abs(dx) < abs(dy) else (0.0, round(dy,2))
```

**(b) Out of frame.** Use a safe area, not the raw frame — `SAFE = 0.96` (2% inset per
side) matches broadcast practice and absorbs stroke width, which `get_all_points()`
does *not* include (points are the path spine; a `stroke_width=4` line bleeds ~0.015
world units either side at 1080p — negligible, but titles pushed to `to_edge(UP)` sit
right on the line). Report the clipped *fraction*, and the exact corrective shift:

```python
xlim, ylim = W/2*SAFE, H/2*SAFE
inside = max(0, min(b.x1,xlim)-max(b.x0,-xlim)) * max(0, min(b.y1,ylim)-max(b.y0,-ylim))
clipped = 1 - inside/b.area
severity = "fatal" if clipped > 0.02 else "warn"
fix = f"shift by ({push_x(b,xlim):+.2f}, {push_y(b,ylim):+.2f}) or scale_to_fit_width({2*xlim:.2f})"
```

**(c) Text too small.** Do **not** gate on the `font_size` kwarg. `font_size` maps to
world units through glyph-dependent factors — `Text.font_size` is
`height/initial_height/TEXT_MOB_SCALE_FACTOR*2.4*_font_size/48` and
`SingleStringMathTex.font_size` is `height/initial_height/SCALE_FACTOR_PER_FONT_POINT`
with `SCALE_FACTOR_PER_FONT_POINT = 1/960` — and any later `.scale()` silently changes
it. Gate on **rendered pixel height at the delivery resolution**:

```python
px = box.h / config.frame_height * config.pixel_height     # 135 px per world unit at 1080p
```

**[measured]** calibration: `Text("Hello World", font_size=48)` → world height 0.516 →
**69.7 px** at 1080p. `Text("tiny caption", font_size=8)` → 0.106 → **14.3 px**.
Empirically px ≈ 1.45 × font_size for mixed-case Latin at 1080p, but it varies with
ascenders/descenders, so measure, don't multiply.

Threshold: **24 px at the delivery resolution** (≈ font_size 17). Legibility guidance
for full-HD video puts body text at 40–60 px, so 24 px is a hard floor, not a target;
set `warn` at 24 and `fatal` at 16. The literature's nearest analogue is SGA's
legibility term, "fraction of objects exceeding a minimum scale threshold
δ (default **0.15 world units**)" — apply that one to non-text primitives.

Critically: **evaluate this against the *delivery* resolution, not the preview.** If you
verify at `-ql` (854×480) and ship at 1080p, a `-ql`-legible caption is fine; the reverse
is the trap. Compute px with `config.pixel_height` set to the delivery value.

**(d) Off-screen at rest vs. in flight.** The probe samples only *resting* states — the
end of each `play()`. SGA makes this distinction explicit: conflicts at t ∈ {0,1} are
"persistent errors requiring patches", mid-trajectory overlaps are "transient and
ignored" (it samples K=11 frames per animation to tell them apart). **Every finding the
probe produces is persistent by construction**, which is what you want: transient
mid-tween overlap is usually intentional (a `Transform` passing through). If you later
want in-flight checking, `Animation.interpolate(alpha)` can be called directly at
α ∈ {0.25, 0.5, 0.75} — the same sample points OmniManim uses
([arXiv:2605.15585](https://arxiv.org/abs/2605.15585)).

**[measured]** Tier-1 output on a deliberately bad layout, 0.37 s total:

```
[fatal] out_of_frame   t=2.0  Text bbox (-10.83,-0.37,10.83,0.37) escapes safe area
                              x=[-6.83,6.83] y=[-3.84,3.84]; 37% of it is off-screen
       fix: shift by (-4.00,+0.00) or scale_to_fit_width(13.65)
[fatal] overlap        t=3.0  Text and Text overlap: 100% of the smaller box is covered
       fix: separate by MSV (0.0, 0.57)
[fatal] out_of_frame   t=4.5  Circle bbox (6.0,2.0,8.0,4.0) ... 62% off-screen
[warn ] text_too_small t=4.5  Text renders at 13px (<24px) at 1920x1080
       fix: raise font_size by x1.84
```

### 3.5 Sandboxing: timeouts, memory, crashes

Run the probe in a child process with POSIX rlimits. ManimAgent's budgets are a good
starting point: **180 s wall, 120 s CPU, 4 GB RAM**. Given `-qh` **[measured]** at
1.68 GB for a trivial 20 s scene, 4 GB is not generous — raise it for Tier 2 or verify
only at `-ql`/`-qm`.

```python
def _apply_limits():
    resource.setrlimit(resource.RLIMIT_CPU,   (120, 120))
    resource.setrlimit(resource.RLIMIT_AS,    (4*1024**3, 4*1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512*1024**2, 512*1024**2))

p = mp.Process(target=_child, args=(path, cls, q)); p.start(); p.join(180)
if p.is_alive():
    p.kill(); p.join(); return {"ok": False, "category": "timeout"}
```

Catch `MemoryError` separately (that's `RLIMIT_AS` firing) and report `category: "oom"`.
Typed categories — ManimAgent uses `python | latex | manim_runtime | timeout | unknown` —
are what let the orchestrator decide *whether to retry at all* (§7).

### 3.6 Condensed tracebacks

`manim` on stderr produces a `rich` box-drawing traceback. **[measured]: 4968 bytes** for
one `AttributeError`, mostly manim-internal frames rendered as ASCII art. Running
in-process and condensing yields **~340 bytes** — a **14× reduction** — and is strictly
more informative because it keeps the *candidate's* source lines:

```python
def condense(exc, candidate_path, ctx=2):
    frames = [dict(line=fr.lineno, func=fr.name,
                   source="\n".join(f"{n:>4} | {linecache.getline(fr.filename,n).rstrip()}"
                                    for n in range(max(1,fr.lineno-ctx), fr.lineno+ctx+1)))
              for fr in traceback.extract_tb(exc.__traceback__)
              if os.path.abspath(fr.filename) == os.path.abspath(candidate_path)]
    last = traceback.extract_tb(exc.__traceback__)[-1]
    return dict(category=classify(exc), error=f"{type(exc).__name__}: {exc}",
                user_frames=frames[-2:],
                manim_frame=f"{os.path.basename(last.filename)}:{last.lineno} in {last.name}")
```

**[measured]** output:

```json
{"ok": false, "category": "api",
 "error": "AttributeError: Square object has no attribute 'shift_right'",
 "user_frames": [{"line": 6, "func": "construct",
   "source": "   4 |         s = Square()\n   5 |         self.play(Create(s), run_time=1)\n   6 |         self.play(s.animate.shift_right(3))"}],
 "manim_frame": "mobject.py:723 in __getattr__"}
```

The `manim_frame` field earns its place: `mobject.py:723 __getattr__` vs
`tex_file_writing.py:200 compile_tex` vs `cairo_renderer.py` tells you the failure
*class* even when the exception type is the same `ValueError`.

---

## 4. Tier 2 — low-res render + VLM critique

Only reached by candidates that passed Tiers 0–1.

### 4.1 Render settings

```
manim -ql --disable_caching --progress_bar none --save_sections scene.py SceneName
```

`-ql` = 854×480 @ 15 fps; **[measured] 2.06 s / 335 MB** for a 20 s scene. Options worth
knowing (`manim/cli/render/*.py`):

| flag | effect | use |
|---|---|---|
| `--dry_run` | render, write nothing | pure "does it execute" — but Tier 1 is faster and more informative |
| `-s` / `--save_last_frame` | forces `skip_animations=True`, writes one PNG | fastest possible pixel check; **[measured] 0.76 s** |
| `-n A,B` / `--from_animation_number` | render only animations A..B (raises `EndSceneEarlyException` past B) | re-render only the beat you just repaired |
| `--save_sections` | one mp4 per `next_section()` **plus a JSON manifest** | per-beat frames + plan alignment (§6) |
| `--disable_caching` | skip hash-based reuse | mandatory for verification: caching will silently serve the *previous* candidate's frames |
| `-q [l\|m\|h\|p\|k]` | 480p15 / 720p30 / 1080p60 / 1440p60 / 2160p60 | |

Two gotchas: **`--disable_caching` is not optional** in a repair loop, and
`-s` implies `skip_animations`, so `-s` output tells you nothing about intermediate beats —
use `--save_sections` for that.

### 4.2 Frame sampling

Three strategies, in increasing order of quality:

1. **`fps=1` uniform** — what TheoremExplainAgent does (`clip.iter_frames(fps=1)`).
2. **Chunk + pick most informative** — TheoremExplainAgent divides into `num_chunks`
   and, within each chunk, keeps `image_with_most_non_black_space`: grayscale the frame,
   count pixels `> 10`, keep the argmax. Cheap and effective at skipping mid-fade frames.
3. **Per-section last frame** — best for a planned pipeline, because it aligns 1:1 with
   your plan beats and always lands on a *resting* state:

```bash
for f in media/videos/<mod>/480p15/sections/*.mp4; do
  ffmpeg -loglevel error -sseof -0.2 -i "$f" -frames:v 1 -q:v 3 "sheet/$(basename $f .mp4).jpg" -y
done
```
**[measured]** 854×480 JPEG, **2.6–5.4 KB each** — a 10-beat video is ~40 KB of image
payload. Well inside one VLM call.

**Contact sheet** with a coordinate grid (Code2Video's "visual anchor prompt" is exactly
this idea — give the VLM an explicit spatial reference so it isn't guessing at
coordinates; its repo even ships a `GRID.png` reference asset):

```bash
ffmpeg -i scene.mp4 -vf "fps=1,scale=427:240,tile=3x3:margin=6:padding=4,\
drawgrid=w=iw/3:h=ih/3:t=1:c=red@0.4" -frames:v 1 -q:v 4 contact.jpg
```
**[measured]** 1301×740, **25.3 KB**.

### 4.3 The rubric

TheoremExplainBench's five dimensions are the de-facto standard; the actual prompt
files are in the repo (`eval_suite/prompts_raw/`). Scores are 1–5, decoded greedily
(temperature 0), aggregated as a **geometric mean** so one bad axis can't be averaged away:

| dimension | modality | judge | **Spearman ρ vs human** |
|---|---|---|---|
| Visual Relevance | key frames | GPT-4o | **0.72** |
| Element Layout | key frames | GPT-4o | **0.42** |
| Visual Consistency | video chunks | Gemini 2.0-Flash | 0.17 |
| Logical Flow | SRT transcript | GPT-4o | 0.16 |
| Accuracy & Depth | SRT transcript | GPT-4o | 0.14 |

The `Element Layout` sub-criteria are worth copying verbatim: *Placement and Size*,
*Overlap* ("free of unintentional overlap"), *Clarity*. Note the prompt explicitly warns
the judge that "the captured frame may be a frame where some motion is taking place" —
without that, VLMs penalize mid-`FadeIn` frames.

ManimAgent uses a leaner three-axis version (Logical Flow / Layout-Occlusion / Accuracy),
**nK = 4 keyframes**, unweighted mean → u ∈ [0,100].
SGA's VLM-critic baseline uses four 100-point scales: Educational Logic, Aesthetic Tone,
Layout Flow, Visual Clarity.

### 4.4 VLM judges are not reliable on layout — design around it

This is the most important negative result in the literature and it should shape the architecture.

- TheoremExplainAgent: **Element Layout ρ = 0.42**; the three narrative/consistency axes
  are **ρ = 0.14–0.17**, i.e. near-noise. Inter-rater Krippendorff's α **0.31–0.56**.
- ManimAgent: **VLM–human agreement is negative** — Pearson **r = −0.17**, Spearman
  **ρ = −0.20** — and the authors report it "only as diagnostics". Human raters
  themselves agreed at chance (**κ = −0.01**) on subjective usability.
- SGA's human study: the deterministic geometric checker **beat a Gemini-3.0-Flash VLM
  critic head-to-head at the thing VLMs are supposed to be for** — 56.7% preference on
  overlap and 73.3% on canvas errors, while costing 6–18× less per iteration. Against the
  raw baseline SGA won 93.3% (overlap) / 75.6% (canvas).
- General VLM grounding evidence: bounding-box-only highlighting gives recall **0.32**;
  performance recovers only when boxes are paired with **text tags and explicit coordinates**.

**Conclusions for the design:**

1. **Never let a VLM be the sole detector of overlap or out-of-frame.** Tier 1 owns those,
   deterministically. The VLM's job is the residual: is this *pedagogically* right, does
   it match the plan, is the color/emphasis sane, is the pacing plausible.
2. **Ground the VLM.** Send the contact sheet *plus* the Tier-1 box list as text
   (`kind`, `label`, bbox tuple) *plus* the grid overlay. That's the
   "text tags + bounding box coordinates" combination the grounding literature says is the
   only configuration that works.
3. **Use the VLM as a ranker, not a gate.** ManimAgent ships
   `c* = argmax_t u(t)` across renderable candidates rather than thresholding. With
   ρ ≈ 0.4 the ordinal signal is worth something; the absolute score is not.
4. **Treat Accuracy & Depth / Logical Flow scores as advisory** (ρ ≈ 0.15) and route
   correctness to the deterministic plan-coverage check in §6 instead.

---

## 5. Tier 3 — human review

Gate on: any Tier-2 score below threshold, any `warn` that survived two repair rounds,
and a fixed random sample (~10%) of *passing* videos to keep the Tier 0–2 thresholds
calibrated. SGA's video-level human preference (SGA 38.5% / VLM-critic 26.0% / raw 24.0%,
remainder ties) shows the ceiling: even the best automated pipeline leaves a large
"nobody prefers it strongly" band. Don't try to automate that band away.

---

## 6. Narration / plan alignment

`self.next_section(name=...)` is the hook that makes beats machine-inspectable, and
`--save_sections` writes a **JSON manifest** next to the per-section mp4s.
**[measured]**, `media/videos/<mod>/480p15/sections/<Scene>.json`:

```json
[{"name": "beat1_intro", "type": "default.normal", "video": "Sect_0000_beat1_intro.mp4",
  "width": 854, "height": 480, "nb_frames": "38", "duration": "2.533333",
  "avg_frame_rate": "15/1", "codec_name": "h264", "pix_fmt": "yuv420p"}, ...]
```

That gives four deterministic alignment gates, all free:

1. **Coverage.** `{section names} ⊇ {plan beat ids}` — and require the codegen prompt to
   emit `self.next_section(name="<beat_id>")` as the first statement of each beat. A
   missing beat is a *silent* failure mode that no visual check will catch.
2. **Order.** The JSON is emitted in render order; compare against plan order.
3. **Duration fit.** Narration at ~150 wpm needs `words/2.5` seconds. Flag any beat
   where `section.duration < 0.8 × narration_seconds` (animation finishes before the
   voiceover — the most common sync failure) or `> 2.0 ×` (dead air).
4. **Per-beat visual evidence.** Each section mp4 gives you a clean last frame for the
   VLM, labelled with the beat id — so the VLM critique can be *per beat against that
   beat's narration text* rather than a whole-video impression. This is strictly better
   grounding than TheoremExplainAgent's whole-transcript approach, whose logical-flow
   score came out at ρ = 0.16.

Two further hooks worth knowing: `Scene.add_subcaption(content, duration, offset)` and
`play(..., subcaption=...)` write an SRT alongside the video — that's how
TheoremExplainAgent gets the transcript it feeds to the text judge. And
`next_section(skip_animations=True)` lets you render *one* beat in isolation during repair.

The Tier-1 probe already records `section` on every keyframe, so layout findings come
back tagged with the beat that produced them: `"beat2_body, t=5.0, overlap"` is a
directly actionable repair target.

---

## 7. Repair loop design

### 7.1 Feedback format — what actually moves the fix rate

[arXiv:2607.14167](https://arxiv.org/abs/2607.14167) ran the ablation: structured
feedback = **failure location + observed value + admissible alternatives**.

- Qwen2.5-Coder-14B: **14/50 → 36/50 (+44 pp)**
- Llama-3.1-8B: **8/50 → 29/50 (+42 pp)**
- **Almost all of the gain came from the *admissible alternatives* field.** Location +
  observed value alone stayed near the raw-diagnostic baseline.
- Prose vs keyed JSON made **almost no difference**. Don't over-engineer the schema;
  do make sure every finding names a legal fix.

So every finding your gates emit must carry a *fix* field. Concretely:

| gate | location | observed | **admissible alternative** |
|---|---|---|---|
| api | `L11` | `Square has no attribute 'shift_right'` | `Did you mean: get_right? Use .animate.shift(RIGHT*3)` |
| latex | `L8` | `! File ended while scanning use of \frac` | `Balance the braces, or use Text()` |
| overlap | `beat2, t=3.0` | `Text∩Text, ρ=1.00` | `MSV (0.0, 0.57) — shift one by 0.57 in y` |
| out_of_frame | `beat1, t=2.0` | `bbox x1=10.83 > 6.83, 37% clipped` | `shift by (-4.00,0.00) or scale_to_fit_width(13.65)` |
| text_too_small | `beat3, t=4.5` | `13px < 24px @1080p` | `raise font_size by ×1.84` |

This is also SGA's design: it emits an MSV plus a **±5 line source context window around
`creation_lineno`** and a menu of fix strategies (`.shift()`, rescale, reposition to a
safe region, adjust `.next_to()` buffers, insert a temporal correction before the relevant
`self.play()`), then validates the patch with `ast.parse` and **rolls back on parse failure**.
Copy the rollback.

### 7.2 Traceback: condensed, not full

The condensed form (§3.6) is 14× smaller and drops the manim-internal ASCII-art frames
that dominate the raw rich traceback. ManimAgent goes further and has a "Text Reviewer"
compress the failure into **≤60 words** before regeneration. TheoremExplainAgent passes
the raw stderr and demands a structured `<ERROR_ANALYSIS>` (Error Type / Location / Root
Cause / Impact) before `<SOLUTION>` — i.e. it makes the *fixer* do the condensing.
Either works; doing it deterministically is cheaper and more reliable.

One rule from the agent-failure literature worth honoring: **context contamination** —
leaving the failed attempt in the context window raises the per-step error rate on the
retry ([arXiv:2605.08563](https://arxiv.org/html/2605.08563)). Prefer
*replace the failing region and restate the constraint* over *append another turn*.

### 7.3 Iteration budgets — published values

| system | loop | budget | result |
|---|---|---|---|
| TheoremExplainAgent | render-error retry | **N = 5** | success 7%/0%/3% at N=0 → **93%/91%/96%** at N=5 (easy/med/hard) |
| TheoremExplainAgent | visual self-reflection | until `<LGTM>`, resets retry counter | `-qh` render each pass |
| ManimAgent | text reflection (crash) | **T_text = 2** | give up if same error category twice, or Reviewer says give_up |
| ManimAgent | visual reflection | **T_vis = 2**, auto-pass at u ≥ **90**/100 | ships `argmax_t u(t)` |
| SGA | geometric refinement | **n = 1** | +16.1% MVQS over raw |
| bayan-manim-video-generator | bounded repair | **≤ 2** | classify → minimal fix → re-run all gates |

Synthesis for this pipeline:

- **Tier-0/1 fatal (deterministic, with a named fix): up to 3 attempts.** These have the
  highest fix rate — the feedback is exact.
- **Tier-2 VLM critique: 1–2 attempts, then stop.** ρ ≈ 0.4 means further iterations are
  as likely to walk backwards as forwards. ManimAgent's `Δ_fail = 5` guard (only accept a
  visual revision if the score improved by ≥5/100) is the right shape.
- **Abort immediately** if the same `category` + same error string recurs twice — that's
  ManimAgent's give-up condition and it saves a lot of tokens.
- **Total budget: 5 model calls per scene.** TheoremExplainAgent's own curve says the
  marginal return past N=5 is tiny; the structured-feedback paper capped at 4.

### 7.4 Fallback

When the budget is exhausted, degrade rather than fail:

1. **Simplify in place** — re-emit the beat from a constrained template: one `Title`,
   one body element, `VGroup(...).arrange(DOWN, buff=0.5)`, `Write` → `wait` → `FadeOut`.
   Layout-safe by construction (arrange + a single column can't overlap and can be
   `scale_to_fit_height`'d into the safe area).
2. **Text-only slide** from the beat's narration — always renders, always legible.
3. **Drop the beat** and let narration carry it, if the plan marks it optional.

Log which tier produced the shipped artifact; that's your quality telemetry.

---

## 8. Existing tools — survey

| tool | what it is | verdict |
|---|---|---|
| **`manim.utils.testing.frames_comparison`** ([docs](https://docs.manim.community/en/stable/contributing/testing.html)) | `@frames_comparison` pytest decorator; renders a scene and diffs frames against `.npz` control data; `--set_test` regenerates baselines, `--show_diff` visualizes | **Wrong tool for generated code** (there is no baseline for a novel scene) but the **right source of parts**: `DummySceneFileWriter`, `_make_test_scene_class`, and the `Scene(skip_animations=True).render()` pattern are all lifted from it. Do use it for **regression tests on your own template library**. |
| **`manim4ai`** ([github](https://github.com/aadya940/manim4ai)) | `LayoutManager` with `place()` / `static_check()`; Shapely `LineString` trajectories, `FRAME_BOX = box(-7,-4,7,4)`, `max_objects=4`, `samples=10`, collision-exception groups | Closest thing to a Manim layout linter that exists. **But** it requires you to *build the scene through its API*, so it can't verify arbitrary LLM output; and its `FRAME_BOX` is the wrong width (±7 vs ±7.111). Good source of ideas: the **collision-group exception list** and **trajectory sampling** are both worth stealing. |
| **SGA** ([arXiv:2607.18116](https://arxiv.org/abs/2607.18116)) | Plug-and-play geometric verifier: AST-instruments `construct()` to wrap every statement in try/except, partially executes, extracts AABBs, detects conflicts, emits MSV + fix templates | The reference design for Tier 1. Its **per-statement try/except instrumentation** is a genuine improvement over my probe: it extracts spatial primitives from the *surviving* statements even when one line raises. Worth adding once the basic gate works. |
| **TheoremExplainAgent** ([repo](https://github.com/TIGER-AI-Lab/TheoremExplainAgent)) | Full pipeline + `eval_suite/` | Take the **prompts verbatim** (`image_eval.txt`, `text_eval_new.txt`, `video_eval_new.txt`, `prompt_animation_fix_error.txt`, `code_limit.txt`, `code_font_size.txt`) and the `image_with_most_non_black_space` keyframe heuristic. |
| **Code2Video** ([arXiv:2510.01174](https://arxiv.org/abs/2510.01174), [repo](https://github.com/showlab/Code2Video)) | Planner/Coder/Critic, "visual anchor prompts", scope-guided auto-fix, TeachQuiz metric | Source of the **grid-overlay anchoring** idea for the VLM critic. TeachQuiz (unlearn a concept in a VLM, then measure recovery from the video) is a nice end-to-end metric but far too expensive for a per-candidate gate. |
| **`manim-checker`** | — | **Does not exist.** No such package on PyPI or GitHub; searches surface only generic Python linters. |
| generic hallucinated-API linters (e.g. `wraith`) | Rust static analyzer for fake APIs/packages | Not Manim-aware. The 20-line `dir(manim)` introspection in §2.2 is better for this, because it's version-exact. |

---

## 9. Measured cost summary

Per candidate scene (20 s of animation, 11 `play()` calls), on this machine:

| stage | wall | RSS | LLM cost |
|---|---|---|---|
| manim import (once per worker) | 0.51 s | ~150 MB | — |
| Tier 0 static (incl. 1 LaTeX compile) | **0.25 s** | — | — |
| Tier 1 probe + layout checks | **0.29 s** | ~160 MB | — |
| Tier 2 `-ql --save_sections` render | **~2.1 s** | 335 MB | — |
| Tier 2 frame extraction + contact sheet | ~0.3 s | — | — |
| Tier 2 VLM critique | ~2–5 s | — | 1 call, ~40 KB images |
| *(reference)* `-qh` final render | **19.3 s** | **1.68 GB** | — |

**Tier 0+1 ≈ 0.55 s and zero tokens** gates everything. Parallelize across scenes with
one process per scene; RSS at Tier 0/1 is ~160 MB, so ~8 workers per GB.

---

## 10. Calibration and known failure modes

Things that will bite, in rough order of how much time they'll cost:

1. **Overlap false positives** are the #1 risk. **[measured] 26 → 0** on a good scene
   once the semantic filter landed. Budget real time for tuning `DECORATOR_KINDS` and the
   `same-root` rule against your own template library. Ship the gate as `warn` first,
   measure the FP rate on 50 known-good scenes, *then* promote to `fatal`.
2. **`--disable_caching` must be on.** Manim hashes `(scene, camera, animations, mobjects)`
   and reuses partial movie files; in a repair loop this silently serves the previous
   candidate's frames (`cairo_renderer.py:79–92`).
3. **Version skew.** The probe's `renderer=` injection works on 0.18/0.19 and breaks on
   0.21+ (`Manager` refactor). The API-existence check is version-exact *by design* —
   which means it will flag valid code if the generator was prompted against a different
   version. Pin one version everywhere, and state it in the codegen prompt.
4. **`.animate` chains beyond one level** (`mob.animate.shift(...).scale(...)`) aren't
   covered by the AST rule; the probe catches them at runtime.
5. **Dynamically-generated text** (f-strings, `.join()`) escapes the LaTeX precheck and the
   `font_size` lint. Accept it; Tier 1 executes the real code.
6. **Updaters and `ValueTracker`** mean mobject state depends on `dt`. `skip_animations`
   still calls `update_to_time(run_time)` once per play, so resting states are correct,
   but a scene whose whole payload is a continuous updater loop will look static to the
   probe. Detect `add_updater` / `always_redraw` statically and route those scenes
   straight to Tier 2.
7. **3D scenes.** All of §3 is axis-aligned 2D. For `ThreeDScene`, AABBs in world space are
   meaningless after camera projection — fall back to `-ql` + VLM, or project through the
   camera matrix before boxing. (`manim4ai` declares the same limitation.)
8. **Stroke width is not in `get_all_points()`.** The 2% safe-area inset absorbs it; don't
   set `SAFE = 1.0`.
9. **Verify text size at the delivery resolution, not the preview resolution.**

---

## Sources

**Papers**
- SGA: Plug&Play Geometric Verification for Educational Video Synthesis — https://arxiv.org/abs/2607.18116 (AABB overlap, ε/ρ thresholds, MSV, AST-instrumented partial execution, MVQS, 6–18× speedup, human study)
- TheoremExplainAgent — https://arxiv.org/abs/2502.19400 · repo https://github.com/TIGER-AI-Lab/TheoremExplainAgent (5-dimension rubric, ρ vs human, N=5 retry curve, prompt files)
- See Before You Code / OmniManim — https://arxiv.org/abs/2605.15585 (pixel-space overlap metrics: IoU ≥ 0.20, overlap ratio ≥ 0.35, dense-cell ratio, interpolation-aware sampling at u ∈ {0.25,0.5,0.75})
- ManimAgent: Self-Evolving Multimodal Agents for Visual Education — https://arxiv.org/abs/2606.30296 (static checker, rlimits 180 s/120 s/4 GB, typed failure categories, T_text=2 / T_vis=2, VLM–human r = −0.17)
- Code2Video — https://arxiv.org/abs/2510.01174 · repo https://github.com/showlab/Code2Video (Planner/Coder/Critic, visual anchor prompts, TeachQuiz)
- Structured Feedback Improves Repair in an LLM Agent Loop — https://arxiv.org/abs/2607.14167 (+44 pp / +42 pp; admissible-alternatives ablation)
- Detecting and Correcting Hallucinations in LLM-Generated Code via Deterministic AST Analysis — https://arxiv.org/abs/2601.19106 (introspection KB, 100% P / 87.6% R / F1 0.934, 77.0% auto-correct)
- Why Retrying Fails: Context Contamination in LLM Agent Pipelines — https://arxiv.org/html/2605.08563

**Manim source and docs** (all links pinned to v0.19.0)
- `scene/scene.py` — `play`, `wait`, `next_section`, `get_run_time`, `get_time_progression`, `play_internal`: https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/scene/scene.py
- `mobject/mobject.py` — `get_all_points`, `get_critical_point`, `family_members_with_points`, `_AnimationBuilder.__getattr__`: https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/mobject/mobject.py
- `renderer/cairo_renderer.py` — `update_skipping_status`, caching: https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/renderer/cairo_renderer.py
- `utils/testing/frames_comparison.py`, `_test_class_makers.py` — `DummySceneFileWriter`: https://github.com/ManimCommunity/manim/tree/v0.19.0/manim/utils/testing
- `utils/tex_file_writing.py` — LaTeX log parsing (`startswith("!")`): https://github.com/ManimCommunity/manim/blob/v0.19.0/manim/utils/tex_file_writing.py
- `cli/render/{render_options,global_options}.py` — `-n`, `-s`, `-q`, `--save_sections`, `--dry_run`, `--disable_caching`
- `_config/{default.cfg,utils.py}` — `frame_height=8.0`, `frame_width = 8 × 16/9 = 14.2222…`
- `constants.py` — `DEFAULT_FONT_SIZE = 48`, `SCALE_FACTOR_PER_FONT_POINT = 1/960`, `DEFAULT_WAIT_TIME = 1.0`
- Output settings / sections: https://docs.manim.community/en/stable/tutorials/output_and_config.html
- Testing guide: https://docs.manim.community/en/stable/contributing/testing.html

**Tools**
- manim4ai — https://github.com/aadya940/manim4ai
- generative-manim — https://github.com/marcelo-earth/generative-manim
- bayan-manim-video-generator, bounded repair issue — https://github.com/abodacs/bayan-manim-video-generator/issues/71

**Verified code in this directory**: `verified/static_checks.py` (Tier 0),
`verified/probe_lib.py` + `verified/layout_checks.py` (Tier 1), `verified/runner.py`
(sandbox + traceback condenser), plus the four fixture scenes used to test them.
