"""Plan alignment: beat coverage, order and duration fit from probed sections."""

from __future__ import annotations

from manim_engineer.core import AnimationPlan, Finding, Severity
from manim_engineer.verification.probe import Keyframe

WORDS_PER_SECOND = 2.5


def section_durations(frames: list[Keyframe]) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in frames:
        out[f.section] = out.get(f.section, 0.0) + f.run_time
    return out


def section_order(frames: list[Keyframe]) -> list[str]:
    order: list[str] = []
    for f in frames:
        if not order or order[-1] != f.section:
            order.append(f.section)
    return order


def check_alignment(plan: AnimationPlan, frames: list[Keyframe]) -> list[Finding]:
    out: list[Finding] = []
    planned = [b.beat_id for b in plan.beats]
    seen = [s for s in section_order(frames) if s != "default"]
    missing = [b for b in planned if b not in seen]
    for b in missing:
        out.append(
            Finding(
                gate="coverage",
                severity=Severity.FATAL,
                beat_id=b,
                message=f"beat '{b}' has no self.next_section('{b}') with animations",
                fix=f"Add self.next_section('{b}') before that beat's first self.play().",
            )
        )
    extra = [s for s in seen if s not in planned]
    for s in extra:
        out.append(
            Finding(
                gate="coverage",
                severity=Severity.WARN,
                beat_id=s,
                message=f"section '{s}' is not a planned beat",
                fix="Use only the plan's beat ids as section names.",
            )
        )
    if not missing:
        seen_planned = [s for s in seen if s in planned]
        if seen_planned != [b for b in planned if b in seen_planned]:
            out.append(
                Finding(
                    gate="order",
                    severity=Severity.FATAL,
                    message=f"beats play in order {seen_planned}, plan expects {planned}",
                    fix="Reorder the sections to match the plan.",
                )
            )
    durs = section_durations(frames)
    for b in plan.beats:
        if b.beat_id not in durs:
            continue
        actual = durs[b.beat_id]
        target = b.duration_s + b.wait_after_s
        words = len(b.narration.split())
        narr = words / WORDS_PER_SECOND if words else 0.0
        floor = max(target * 0.6, narr * 0.8) if narr else target * 0.6
        ceil = max(target * 1.8, narr * 2.0 if narr else 0)
        if actual < floor:
            out.append(
                Finding(
                    gate="duration_fit",
                    severity=Severity.WARN,
                    beat_id=b.beat_id,
                    message=f"beat runs {actual:.1f}s but plan wants ~{target:.1f}s"
                    + (f" and narration needs ~{narr:.1f}s" if narr else ""),
                    fix=f"add self.wait({max(0.5, floor - actual):.1f}) after the beat's last animation or raise run_time",
                )
            )
        elif actual > ceil:
            out.append(
                Finding(
                    gate="duration_fit",
                    severity=Severity.WARN,
                    beat_id=b.beat_id,
                    message=f"beat runs {actual:.1f}s, well over the planned ~{target:.1f}s",
                    fix="reduce run_time/wait in this beat",
                )
            )
    return out


def check_equation_provenance(plan: AnimationPlan, code: str) -> list[Finding]:
    """Every provenance equation should appear (normalized) somewhere in the code.

    Advisory: the generator may legitimately split an equation into parts.
    """
    out: list[Finding] = []

    def norm(s: str) -> str:
        return "".join(s.split()).replace("\\left", "").replace("\\right", "").replace("\\,", "")

    code_n = norm(code)
    for eq in plan.provenance.equations:
        key = norm(eq.latex)
        if len(key) >= 6 and key not in code_n and key[: max(6, len(key) // 2)] not in code_n:
            out.append(
                Finding(
                    gate="fidelity",
                    severity=Severity.INFO,
                    message=f"provenance equation '{eq.label}' not found verbatim in the code",
                    fix=f"Use the source equation as written: {eq.latex}",
                )
            )
    return out
