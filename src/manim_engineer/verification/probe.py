"""Tier 1: run construct() with rendering disabled and sample the mobject tree.

`Scene(skip_animations=True)` applies every animation's final state with one
tick per play(); a no-op renderer plus Manim's own DummySceneFileWriter means
zero rasterization. Measured ~0.3 s for a 20 s scene versus ~19 s at -qh.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from manim import config, tempconfig
from manim.mobject.text.tex_mobject import MathTex, SingleStringMathTex, Tex
from manim.mobject.text.text_mobject import MarkupText, Text
from manim.renderer.cairo_renderer import CairoRenderer
from manim.utils.testing._test_class_makers import DummySceneFileWriter

TEXTUAL = (Text, MarkupText, Tex, MathTex, SingleStringMathTex)


class _NoOpRenderer(CairoRenderer):
    def update_frame(self, *a, **k):
        return

    def render(self, *a, **k):
        return

    def save_static_frame_data(self, *a, **k):
        self.static_image = None
        return None


@dataclass
class Box:
    label: str
    kind: str
    textual: bool
    root: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str = ""

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2))


@dataclass
class Keyframe:
    index: int
    t: float
    run_time: float
    section: str
    anim: str
    boxes: list[Box] = field(default_factory=list)
    n_mobjects: int = 0


def semantic_boxes(scene) -> list[Box]:
    """One box per semantic element: text is atomic; groups expand one level per step."""
    boxes: list[Box] = []

    def emit(m, path, root):
        pts = m.get_all_points()
        if len(pts) == 0:
            return
        xy = np.asarray(pts)[:, :2]
        lo, hi = xy.min(0), xy.max(0)
        text = ""
        if isinstance(m, Text | MarkupText):
            text = getattr(m, "original_text", getattr(m, "text", ""))
        elif isinstance(m, Tex | MathTex):
            text = getattr(m, "tex_string", "")
        boxes.append(
            Box(
                label=path,
                kind=type(m).__name__,
                textual=isinstance(m, TEXTUAL),
                root=root,
                x0=float(lo[0]),
                y0=float(lo[1]),
                x1=float(hi[0]),
                y1=float(hi[1]),
                text=str(text)[:60],
            )
        )

    def walk(m, path, root):
        if isinstance(m, TEXTUAL) or not m.submobjects:
            emit(m, path, root)
            return
        for i, sub in enumerate(m.submobjects):
            walk(sub, f"{path}.{i}:{type(sub).__name__}", root)

    for i, top in enumerate(scene.mobjects):
        walk(top, f"m{i}:{type(top).__name__}", i)
    return boxes


def probe(scene_cls) -> list[Keyframe]:
    """Run the scene with no rendering; return one keyframe per play()/wait()."""
    frames: list[Keyframe] = []

    class _Probe(scene_cls):
        def __init__(self, **kw):
            super().__init__(
                renderer=_NoOpRenderer(file_writer_class=DummySceneFileWriter),
                skip_animations=True,
                **kw,
            )
            self._clock = 0.0
            self._section = "default"
            self._i = 0

        def next_section(self, name="unnamed", *a, **k):
            self._section = name
            return super().next_section(name, *a, **k)

        def play(self, *args, **kw):
            label = ", ".join(type(a).__name__ for a in args[:3]) or "?"
            super().play(*args, **kw)
            rt = float(self.duration)
            self._clock += rt
            frames.append(
                Keyframe(
                    index=self._i,
                    t=round(self._clock, 3),
                    run_time=rt,
                    section=self._section,
                    anim=label,
                    boxes=semantic_boxes(self),
                    n_mobjects=len(self.mobjects),
                )
            )
            self._i += 1

    media = tempfile.mkdtemp(prefix="me-probe-")
    with tempconfig(
        {
            "dry_run": True,
            "disable_caching": True,
            "progress_bar": "none",
            "verbosity": "ERROR",
            "media_dir": media,
            "tex_dir": f"{media}/Tex",
            "text_dir": f"{media}/texts",
        }
    ):
        s = _Probe()
        s.render()
    return frames


def load_scene(path: str | Path, class_name: str):
    path = Path(path)
    mod_name = f"candidate_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, class_name)


def frame_geometry() -> tuple[float, float, int, int]:
    return config.frame_width, config.frame_height, config.pixel_width, config.pixel_height
