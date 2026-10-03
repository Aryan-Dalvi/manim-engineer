"""verification bounded context: tiered gates with actionable findings (ADR 0004)."""

from __future__ import annotations

import time
from pathlib import Path

from manim_engineer.core import AnimationPlan, Candidate, Finding, Severity, TierReport
from manim_engineer.verification.alignment import check_alignment, check_equation_provenance
from manim_engineer.verification.critique import (
    CRITIQUE_SCHEMA,
    contact_sheet,
    critique,
    extract_section_frames,
    summarize_boxes,
)
from manim_engineer.verification.layout import check_all, check_budget
from manim_engineer.verification.runner import frames_from_result, run_probe, run_probe_inline
from manim_engineer.verification.static import manim_surface, run_tier0


def verify_tier0(candidate: Candidate, plan: AnimationPlan | None = None) -> TierReport:
    t0 = time.time()
    max_d = plan.budgets.target_duration_s * 2.0 if plan else 90.0
    findings = run_tier0(candidate.code_path, candidate.scene_class, max_duration_s=max_d)
    if plan is not None:
        findings += check_equation_provenance(plan, Path(candidate.code_path).read_text())
    ok = not any(f.severity == Severity.FATAL for f in findings)
    return TierReport(tier=0, ok=ok, findings=findings, elapsed_s=round(time.time() - t0, 2))


def verify_tier1(
    candidate: Candidate,
    plan: AnimationPlan | None = None,
    pixel_height: int = 1080,
    inline: bool = False,
) -> TierReport:
    t0 = time.time()
    result = (
        run_probe_inline(candidate.code_path, candidate.scene_class)
        if inline
        else run_probe(candidate.code_path, candidate.scene_class)
    )
    if not result.get("ok"):
        f = Finding(
            gate="runtime",
            severity=Severity.FATAL,
            category=result.get("category"),
            line=result.get("line"),
            message=result.get("error", "scene failed"),
            fix=_runtime_fix(result),
        )
        return TierReport(
            tier=1,
            ok=False,
            findings=[f],
            notes=_frames_note(result),
            elapsed_s=round(time.time() - t0, 2),
        )
    frames = frames_from_result(result)
    findings = check_all(frames, pixel_height=pixel_height)
    if plan is not None:
        findings += check_alignment(plan, frames)
        findings += check_budget(
            frames, plan.budgets.max_concurrent_mobjects, plan.budgets.on_screen_text_chars
        )
    ok = not any(f.severity == Severity.FATAL for f in findings)
    rep = TierReport(
        tier=1,
        ok=ok,
        findings=findings,
        duration_s=result.get("duration_s"),
        elapsed_s=round(time.time() - t0, 2),
    )
    rep.notes = summarize_boxes(result.get("frames", []))
    return rep


def _runtime_fix(result: dict) -> str:
    cat = result.get("category")
    if cat == "latex":
        return "Fix the LaTeX string (raw string, balanced braces, escape %) or use Text() for plain words."
    if cat == "api":
        return "Use only ManimCE 0.19 methods; check the attribute name and its arguments."
    if cat == "timeout":
        return "Reduce animation count/complexity; avoid heavy updaters and huge groups."
    if cat == "oom":
        return "Reduce the number of mobjects; avoid very large grids."
    return "Read the error and the source lines; change only what the traceback points at."


def _frames_note(result: dict) -> str:
    frames = result.get("user_frames") or []
    parts = [fr.get("source", "") for fr in frames]
    if result.get("manim_frame"):
        parts.append(f"(raised inside {result['manim_frame']})")
    return "\n".join(p for p in parts if p)


__all__ = [
    "CRITIQUE_SCHEMA",
    "check_alignment",
    "check_all",
    "check_budget",
    "check_equation_provenance",
    "contact_sheet",
    "critique",
    "extract_section_frames",
    "manim_surface",
    "run_probe",
    "run_tier0",
    "summarize_boxes",
    "verify_tier0",
    "verify_tier1",
]
