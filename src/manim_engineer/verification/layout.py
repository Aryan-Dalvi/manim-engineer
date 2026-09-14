"""Tier 1 geometric gates on probed keyframes: overlap, out-of-frame, legibility.

Thresholds follow SGA (arXiv 2607.18116) and the research probe validation:
asymmetric coverage ratio for overlap, a 2% safe-area inset, text pixel height
at the delivery resolution. Every finding carries a minimum separation vector
or an exact shift as its fix.
"""

from __future__ import annotations

from manim_engineer.core import Finding, Severity
from manim_engineer.verification.probe import Box, Keyframe

FRAME_W = 14.222222222222221
FRAME_H = 8.0
SAFE = 0.96
OVERLAP_COVERAGE = 0.10
OVERLAP_HIGH = 0.30
MIN_SCALE = 0.15
INVISIBLE_KINDS = {
    "ValueTracker",
    "ComplexValueTracker",
    "Point",
    "Mobject",
    "VectorizedPoint",
    "VMobject",
    "VGroup",
    "Group",
}
SOLID_KINDS = {
    "Dot",
    "LabeledDot",
    "SmallDot",
    "ArrowTriangleFilledTip",
    "ArrowTriangleTip",
    "ArrowSquareTip",
    "ArrowCircleTip",
    "StealthTip",
    "Tip",
}
AXIS_KINDS = {
    "Axes",
    "NumberLine",
    "NumberPlane",
    "BarChart",
    "ThreeDAxes",
    "ComplexPlane",
    "PolarPlane",
}
DECORATOR_KINDS = {
    "Dot",
    "LabeledDot",
    "SmallDot",
    "ArrowTriangleFilledTip",
    "ArrowTriangleTip",
    "ArrowSquareTip",
    "ArrowCircleTip",
    "StealthTip",
    "Brace",
    "BraceLabel",
    "SurroundingRectangle",
    "BackgroundRectangle",
    "Underline",
    "Cross",
    "Line",
    "DashedLine",
    "Arrow",
    "DoubleArrow",
    "Vector",
    "Angle",
    "RightAngle",
    "Tip",
    "NumberLine",
    "Axes",
    "NumberPlane",
    "ParametricFunction",
    "FunctionGraph",
    "ImplicitFunction",
    "Rectangle",
    "RoundedRectangle",
    "Square",
    "Circle",
    "Ellipse",
    "Polygon",
    "Polygram",
    "RegularPolygon",
    "Triangle",
    "Sector",
    "Annulus",
    "Arc",
    "TangentLine",
}


def _inter(a: Box, b: Box) -> float:
    dx = min(a.x1, b.x1) - max(a.x0, b.x0)
    dy = min(a.y1, b.y1) - max(a.y0, b.y0)
    return max(0.0, dx) * max(0.0, dy)


def _px_height(b: Box, pixel_height: int) -> float:
    return b.h / FRAME_H * pixel_height


def _push_x(b: Box, xlim: float) -> float:
    if b.x1 > xlim:
        return xlim - b.x1
    if b.x0 < -xlim:
        return -xlim - b.x0
    return 0.0


def _push_y(b: Box, ylim: float) -> float:
    if b.y1 > ylim:
        return ylim - b.y1
    if b.y0 < -ylim:
        return -ylim - b.y0
    return 0.0


def msv(a: Box, b: Box) -> tuple[float, float]:
    dx = min(a.x1 - b.x0, b.x1 - a.x0)
    dy = min(a.y1 - b.y0, b.y1 - a.y0)
    return (round(dx, 2), 0.0) if abs(dx) < abs(dy) else (0.0, round(dy, 2))


def reportable_pair(a: Box, b: Box) -> bool:
    """Text-on-text always; text under a solid mark (tip, dot) too; hollow shapes never.

    Curves, axes, rectangles and arrows have large, mostly empty bounding boxes,
    so a label placed inside them is normal composition, not a collision.
    """
    if a.root == b.root:
        return False
    if a.textual and b.textual:
        return True
    if a.textual and b.kind in SOLID_KINDS:
        return True
    if b.textual and a.kind in SOLID_KINDS:
        return True
    return False


def _who(b: Box) -> str:
    return f"{b.kind}({b.text!r})" if b.text else b.label


def check_keyframe(
    frame: Keyframe, pixel_height: int = 1080, min_text_px: int = 24
) -> list[Finding]:
    issues: list[Finding] = []
    xlim, ylim = FRAME_W / 2 * SAFE, FRAME_H / 2 * SAFE
    # min_text_px is defined at 1080p delivery; scale it to the probe resolution.
    min_text_px = max(1, round(min_text_px * pixel_height / 1080))
    bs = [b for b in frame.boxes if b.kind not in INVISIBLE_KINDS and b.area > 1e-6]
    for b in bs:
        if b.x0 < -xlim or b.x1 > xlim or b.y0 < -ylim or b.y1 > ylim:
            inside = max(0.0, min(b.x1, xlim) - max(b.x0, -xlim)) * max(
                0.0, min(b.y1, ylim) - max(b.y0, -ylim)
            )
            clipped = 1.0 - inside / max(b.area, 1e-9)
            issues.append(
                Finding(
                    gate="out_of_frame",
                    severity=Severity.FATAL if clipped > 0.02 else Severity.WARN,
                    beat_id=frame.section,
                    t=frame.t,
                    who=[_who(b)],
                    bbox=[list(b.as_tuple())],
                    message=f"{_who(b)} bbox {b.as_tuple()} leaves the safe area (x±{xlim:.2f}, y±{ylim:.2f}); {clipped * 100:.0f}% off-screen",
                    fix=f"shift it by ({_push_x(b, xlim):+.2f}, {_push_y(b, ylim):+.2f}) or scale_to_fit_width({2 * xlim - 0.5:.1f}); prefer place()/fit_to_region() from the kit",
                )
            )
        if b.textual:
            px = _px_height(b, pixel_height)
            if px < min_text_px:
                root_kind = b.label.split(":", 1)[1].split(".", 1)[0] if ":" in b.label else ""
                tick_label = root_kind in AXIS_KINDS or len(b.text.strip()) <= 3
                issues.append(
                    Finding(
                        gate="text_too_small",
                        severity=Severity.WARN
                        if (tick_label or px >= min_text_px * 0.66)
                        else Severity.FATAL,
                        beat_id=frame.section,
                        t=frame.t,
                        who=[_who(b)],
                        bbox=[list(b.as_tuple())],
                        message=f"{_who(b)} renders at {px:.0f}px tall (<{min_text_px}px) at {pixel_height}p, i.e. under 24px at 1080p",
                        fix=f"raise font_size by x{min_text_px / max(px, 1e-6):.2f} or shorten the text",
                    )
                )
        elif (
            max(b.w, b.h) < MIN_SCALE
            and b.kind not in ("Dot", "SmallDot", "LabeledDot")
            and not b.kind.endswith("Tip")
        ):
            issues.append(
                Finding(
                    gate="too_small",
                    severity=Severity.INFO,
                    beat_id=frame.section,
                    t=frame.t,
                    who=[_who(b)],
                    message=f"{b.kind} max extent {max(b.w, b.h):.2f} < {MIN_SCALE} units",
                    fix="scale it up or drop it",
                )
            )
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            a, b = bs[i], bs[j]
            if not reportable_pair(a, b):
                continue
            inter = _inter(a, b)
            if inter <= 0:
                continue
            rho = inter / max(min(a.area, b.area), 1e-9)
            if rho < OVERLAP_COVERAGE:
                continue
            both_text = a.textual and b.textual
            sev = (
                Severity.FATAL
                if (both_text and rho > OVERLAP_COVERAGE) or rho > OVERLAP_HIGH
                else Severity.WARN
            )
            v = msv(a, b)
            issues.append(
                Finding(
                    gate="overlap",
                    severity=sev,
                    beat_id=frame.section,
                    t=frame.t,
                    who=[_who(a), _who(b)],
                    bbox=[list(a.as_tuple()), list(b.as_tuple())],
                    message=f"{_who(a)} and {_who(b)} overlap: {rho * 100:.0f}% of the smaller box is covered",
                    fix=f"move one of them by {v} (minimum separation), FadeOut the earlier one first, or use next_to()/arrange() with buff>=0.3",
                )
            )
    return issues


MIN_FILL_FRACTION = 0.30


def check_fill(frame: Keyframe) -> list[Finding]:
    """Advisory: the union bounding box of content should cover a fair share of the frame."""
    bs = [b for b in frame.boxes if b.area > 0]
    if len(bs) < 3:
        return []
    x0, y0 = min(b.x0 for b in bs), min(b.y0 for b in bs)
    x1, y1 = max(b.x1 for b in bs), max(b.y1 for b in bs)
    frac = ((x1 - x0) * (y1 - y0)) / (FRAME_W * FRAME_H)
    if frac < MIN_FILL_FRACTION:
        return [
            Finding(
                gate="sparse",
                severity=Severity.WARN,
                beat_id=frame.section,
                t=frame.t,
                message=f"content occupies only {frac * 100:.0f}% of the frame",
                fix="scale the main group up with fit_to_region(group, 'main') or add the title/caption regions",
            )
        ]
    return []


def check_all(frames: list[Keyframe], pixel_height: int = 1080) -> list[Finding]:
    """Findings across resting keyframes, deduplicated by (gate, who, section)."""
    seen: set[tuple[str, tuple[str, ...], str | None]] = set()
    out: list[Finding] = []
    for f in frames:
        for issue in check_keyframe(f, pixel_height=pixel_height) + check_fill(f):
            key = (issue.gate, tuple(issue.who), issue.beat_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(issue)
    return out


def check_budget(
    frames: list[Keyframe], max_concurrent_mobjects: int, on_screen_text_chars: int
) -> list[Finding]:
    out: list[Finding] = []
    worst_m = max((f.n_mobjects for f in frames), default=0)
    if worst_m > max_concurrent_mobjects:
        f = max(frames, key=lambda k: k.n_mobjects)
        out.append(
            Finding(
                gate="budget",
                severity=Severity.WARN,
                beat_id=f.section,
                t=f.t,
                message=f"{worst_m} top-level mobjects on screen exceeds budget {max_concurrent_mobjects}",
                fix="FadeOut elements that are no longer needed before adding new ones.",
            )
        )
    for f in frames:
        chars = sum(len(b.text) for b in f.boxes if b.textual)
        if chars > on_screen_text_chars:
            out.append(
                Finding(
                    gate="budget",
                    severity=Severity.WARN,
                    beat_id=f.section,
                    t=f.t,
                    message=f"~{chars} characters of text on screen exceeds budget {on_screen_text_chars}",
                    fix="Shorten labels or split the beat.",
                )
            )
            break
    return out
