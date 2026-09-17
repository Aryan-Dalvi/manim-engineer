"""Plan alignment: beat coverage, order and duration fit from probed sections."""

from __future__ import annotations

import ast
from difflib import SequenceMatcher

from manim_engineer.core import AnimationPlan, Finding, Severity
from manim_engineer.verification.probe import Keyframe
from manim_engineer.verification.static import collect_tex_literals

WORDS_PER_SECOND = 2.5
MIN_EQ_CHARS = 6
RESEMBLES_RATIO = 0.82


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


def _norm(s: str) -> str:
    return (
        "".join(s.split())
        .replace("\\left", "")
        .replace("\\right", "")
        .replace("\\,", "")
        .replace("\\!", "")
    )


def _in_code(key: str, code_n: str) -> bool:
    """The generator may split one equation across MathTex parts, so a prefix counts."""
    if len(key) < MIN_EQ_CHARS:
        return True
    return key in code_n or key[: max(MIN_EQ_CHARS, len(key) // 2)] in code_n


def check_equation_provenance(plan: AnimationPlan, code: str) -> list[Finding]:
    """Equations on screen must be the source's equations.

    This blocks only when the plan carries equations read from the source
    document (`verbatim`). For transcript, audio or slide input the plan's
    equations are the model's own, so every finding stays advisory and the
    unsourced-equation sweep is skipped entirely.
    """
    out: list[Finding] = []
    code_n = _norm(code)
    sourced = [e for e in plan.provenance.equations if e.verbatim and e.latex]

    for eq in plan.provenance.equations:
        if not eq.latex or _in_code(_norm(eq.latex), code_n):
            continue
        if eq.verbatim:
            out.append(
                Finding(
                    gate="fidelity",
                    severity=Severity.FATAL,
                    message=f"source equation '{eq.label}' is not on screen",
                    fix=f'Render it verbatim: MathTex(r"{eq.latex}")',
                )
            )
        else:
            out.append(
                Finding(
                    gate="fidelity",
                    severity=Severity.INFO,
                    message=f"provenance equation '{eq.label}' not found verbatim in the code",
                    fix=f"Use the source equation as written: {eq.latex}",
                )
            )

    if not sourced:
        return out
    known = [_norm(e.latex) for e in plan.provenance.equations if e.latex]
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return out  # the parse gate already reported this
    for lineno, kind, literal in collect_tex_literals(tree):
        lit = _norm(literal)
        if len(lit) < MIN_EQ_CHARS or any(lit in k or k in lit for k in known):
            continue
        near = max(sourced, key=lambda e: SequenceMatcher(None, lit, _norm(e.latex)).ratio())
        if SequenceMatcher(None, lit, _norm(near.latex)).ratio() >= RESEMBLES_RATIO:
            out.append(
                Finding(
                    gate="fidelity",
                    severity=Severity.FATAL,
                    line=lineno,
                    message=f"{kind} alters source equation '{near.label}': {literal!r}",
                    fix=f"Use the source form exactly: {near.latex}",
                )
            )
        else:
            out.append(
                Finding(
                    gate="fidelity",
                    severity=Severity.WARN,
                    line=lineno,
                    message=f"{kind} shows an equation that is not in the source: {literal!r}",
                    fix="Derive it from a provenance equation or drop it.",
                )
            )
    return out
