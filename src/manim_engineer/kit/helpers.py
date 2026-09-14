"""Safe helpers: text that cannot overflow, regions, lifecycle utilities."""

from __future__ import annotations

from manim import *  # noqa: F403

from manim_engineer.kit.style import (
    BODY_SIZE,
    CAPTION_SIZE,
    DIM_OPACITY,
    EDGE_BUFF,
    LABEL_SIZE,
    MIN_FONT_SIZE,
    REGIONS,
    RT_FADE,
    SAFE_WIDTH,
    TITLE_SIZE,
    C,
)


def region_box(name: str) -> tuple[float, float, float, float]:
    """(x_center, y_center, width, height) of a named region."""
    if name not in REGIONS:
        raise KeyError(f"unknown region {name!r}; choose from {sorted(REGIONS)}")
    return REGIONS[name]


def region_center(name: str):
    x, y, _, _ = region_box(name)
    return np.array([x, y, 0.0])  # noqa: F405


def fit_to_region(mob, name: str, margin: float = 0.15, max_scale_up: float = 1.0):
    """Scale `mob` down (never up beyond max_scale_up) to fit the region, then center it."""
    x, y, w, h = region_box(name)
    avail_w, avail_h = w - 2 * margin, h - 2 * margin
    if mob.width > 0 and mob.height > 0:
        s = min(avail_w / mob.width, avail_h / mob.height)
        if s < 1.0 or max_scale_up > 1.0:
            mob.scale(min(s, max_scale_up))
    mob.move_to([x, y, 0.0])
    return mob


def place(mob, name: str, aligned_edge=None, buff: float = 0.15):
    """Move `mob` into a region, optionally hugging one of its edges."""
    x, y, w, h = region_box(name)
    if mob.width > w or mob.height > h:
        fit_to_region(mob, name)
    mob.move_to([x, y, 0.0])
    if aligned_edge is not None:
        target = np.array([x, y, 0.0]) + aligned_edge * np.array([w / 2 - buff, h / 2 - buff, 0.0])  # noqa: F405
        mob.move_to(target, aligned_edge=aligned_edge)
    return mob


def safe_text(
    text: str, font_size: int = BODY_SIZE, color=None, max_width: float = SAFE_WIDTH - 1.0, **kw
) -> Text:  # noqa: F405
    """Single-line Text capped to max_width. Never below MIN_FONT_SIZE by construction."""
    t = Text(text, font_size=max(font_size, MIN_FONT_SIZE), color=color or C["text"], **kw)  # noqa: F405
    if t.width > max_width:
        t.scale_to_fit_width(max_width)
    return t


def safe_multiline(
    *lines: str,
    font_size: int = BODY_SIZE,
    color=None,
    line_buff: float = 0.25,
    max_width: float = SAFE_WIDTH - 1.0,
) -> VGroup:  # noqa: F405
    """Centered multi-line text, one Text per line (Text with newlines left-aligns)."""
    texts = [
        safe_text(line, font_size=font_size, color=color, max_width=max_width) for line in lines
    ]
    return VGroup(*texts).arrange(DOWN, buff=line_buff, center=True)  # noqa: F405


def wrap_text(text: str, max_chars: int = 48, **kw) -> VGroup:  # noqa: F405
    """Greedy word wrap into safe_multiline."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return safe_multiline(*lines, **kw)


def section_title(text: str, color=None) -> Text:  # noqa: F405
    """Title in the title region."""
    t = safe_text(text, font_size=TITLE_SIZE, color=color or C["text"])
    return place(t, "title")


def caption(text: str, color=None) -> Text:  # noqa: F405
    """Footer caption. Reveal with FadeIn(shift=UP*0.2), not Write."""
    t = safe_text(
        text, font_size=CAPTION_SIZE, color=color or C["accent"], max_width=SAFE_WIDTH - 0.6
    )
    return place(t, "footer")


def label_for(
    mob, text: str, direction=DOWN, font_size: int = LABEL_SIZE, color=None, buff: float = 0.2
) -> Text:  # noqa: F405
    """A label placed next_to a mobject, pushed inward when near an edge."""
    t = safe_text(
        text, font_size=font_size, color=color or C["muted"], max_width=max(mob.width * 1.6, 2.5)
    )
    t.next_to(mob, direction, buff=buff)
    return clamp_to_safe(t)


def clamp_to_safe(mob, margin: float = 0.1):
    """Shift a mobject back inside the safe area if it crossed it."""
    from manim_engineer.kit.style import SAFE_X, SAFE_Y

    dx = dy = 0.0
    if mob.get_right()[0] > SAFE_X - margin:
        dx = SAFE_X - margin - mob.get_right()[0]
    elif mob.get_left()[0] < -SAFE_X + margin:
        dx = -SAFE_X + margin - mob.get_left()[0]
    if mob.get_top()[1] > SAFE_Y - margin:
        dy = SAFE_Y - margin - mob.get_top()[1]
    elif mob.get_bottom()[1] < -SAFE_Y + margin:
        dy = -SAFE_Y + margin - mob.get_bottom()[1]
    if dx or dy:
        mob.shift([dx, dy, 0.0])
    return mob


def labeled_box(
    label: str,
    width: float = 2.4,
    height: float = 0.9,
    color=None,
    font_size: int = LABEL_SIZE,
    fill_opacity: float = 0.18,
) -> VGroup:  # noqa: F405
    """Rounded rectangle with a centered, width-capped label. Access .rect / .label via [0]/[1]."""
    color = color or C["primary"]
    rect = RoundedRectangle(
        width=width,
        height=height,
        corner_radius=0.12,
        color=color,
        fill_opacity=fill_opacity,
        stroke_width=2,
    )  # noqa: F405
    text = safe_text(label, font_size=font_size, color=C["text"], max_width=width - 0.3)
    if text.height > height - 0.25:
        text.scale_to_fit_height(height - 0.25)
    text.move_to(rect)
    g = VGroup(rect, text)  # noqa: F405
    g.rect, g.label = rect, text  # type: ignore[attr-defined]
    return g


def arrow_between(a, b, color=None, buff: float = 0.15, stroke_width: float = 3) -> Arrow:  # noqa: F405
    """Arrow from the nearest edges of a to b (works in any direction)."""
    d = b.get_center() - a.get_center()
    if abs(d[0]) >= abs(d[1]):
        start = a.get_right() if d[0] > 0 else a.get_left()
        end = b.get_left() if d[0] > 0 else b.get_right()
    else:
        start = a.get_top() if d[1] > 0 else a.get_bottom()
        end = b.get_bottom() if d[1] > 0 else b.get_top()
    return Arrow(
        start,
        end,
        buff=buff,
        color=color or C["muted"],
        stroke_width=stroke_width,
        max_tip_length_to_length_ratio=0.2,
    )  # noqa: F405


def fade_all(scene, run_time: float = RT_FADE) -> None:
    """FadeOut everything currently on screen."""
    if scene.mobjects:
        scene.play(*[FadeOut(m) for m in scene.mobjects], run_time=run_time)  # noqa: F405


def dim(scene, *mobs, opacity: float = DIM_OPACITY, run_time: float = 0.5) -> None:
    scene.play(*[m.animate.set_opacity(opacity) for m in mobs], run_time=run_time)


def undim(scene, *mobs, run_time: float = 0.5) -> None:
    scene.play(*[m.animate.set_opacity(1.0) for m in mobs], run_time=run_time)


def edge_buff() -> float:
    return EDGE_BUFF
