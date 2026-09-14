"""Style contract for every generated scene.

Adapted from the MIT-licensed 3brown1blue skill pack (Amit T Subhash, 2026),
see src/manim_engineer/generation/knowledge/LICENSE-3brown1blue. Numbers come
from its production audits: safe bounds, minimum sizes, dim opacity, timing.
"""

from __future__ import annotations

from manim import *  # noqa: F403

# ── Frame and safe area ───────────────────────────────────────────────
FRAME_W = 14.222222222222221
FRAME_H = 8.0
SAFE_X = 6.6  # |x| beyond this is at risk of clipping (frame edge is 7.11)
SAFE_Y = 3.7  # |y| beyond this is at risk of clipping (frame edge is 4.0)
SAFE_WIDTH = 2 * SAFE_X
SAFE_HEIGHT = 2 * SAFE_Y

# ── Named regions: (x_center, y_center, width, height) ────────────────
REGIONS: dict[str, tuple[float, float, float, float]] = {
    "title": (0.0, 3.25, SAFE_WIDTH, 0.9),
    "main": (0.0, -0.15, SAFE_WIDTH, 5.4),
    "main_upper": (0.0, 1.2, SAFE_WIDTH, 2.6),
    "main_lower": (0.0, -1.6, SAFE_WIDTH, 2.6),
    "left": (-3.4, -0.15, 6.2, 5.4),
    "right": (3.4, -0.15, 6.2, 5.4),
    "sidebar": (4.7, -0.15, 3.6, 5.4),
    "stage": (-1.5, -0.15, 9.8, 5.4),
    "footer": (0.0, -3.3, SAFE_WIDTH, 0.8),
}

# ── Palette: semantic names, consistent across scenes ─────────────────
C: dict[str, ManimColor] = {  # noqa: F405
    "primary": BLUE_C,  # noqa: F405
    "secondary": TEAL_C,  # noqa: F405
    "accent": YELLOW_C,  # noqa: F405
    "positive": GREEN_C,  # noqa: F405
    "negative": RED_C,  # noqa: F405
    "highlight": YELLOW_C,  # noqa: F405
    "muted": GRAY_B,  # noqa: F405
    "dim": GRAY_D,  # noqa: F405
    "text": WHITE,  # noqa: F405
    "box": BLUE_E,  # noqa: F405
    "purple": PURPLE_B,  # noqa: F405
    "orange": ORANGE,  # noqa: F405
}
PALETTE_CYCLE = [BLUE_C, TEAL_C, YELLOW_C, GREEN_C, RED_C, PURPLE_B, ORANGE, MAROON_B]  # noqa: F405

# ── Type scale (font_size) ────────────────────────────────────────────
TITLE_SIZE = 44
SUBTITLE_SIZE = 32
BODY_SIZE = 28
LABEL_SIZE = 22
CAPTION_SIZE = 22
MIN_FONT_SIZE = 20
EQ_SIZE = 42
EQ_SMALL = 30

# ── Timing ────────────────────────────────────────────────────────────
HOLD_SHORT = 0.6
HOLD_MEDIUM = 1.5
HOLD_LONG = 2.5
RT_WRITE = 1.2
RT_FADE = 0.6
RT_TRANSFORM = 1.5

DIM_OPACITY = 0.15
MIN_BUFF = 0.3
EDGE_BUFF = 0.5
