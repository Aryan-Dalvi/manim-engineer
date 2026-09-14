"""Realize one plan: generate → verify (tiers) → repair → publish → critique.

Repair policy (ADR 0004, research §7.3): up to N deterministic repairs with the
findings' fixes, abort on a repeated failure category, then a bounded visual
repair, then a layout-safe template fallback. Every attempt is kept on disk.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from manim_engineer.core import (
    AnimationPlan,
    ArtifactBundle,
    Candidate,
    Finding,
    PlanStatus,
    Severity,
    TierReport,
)
from manim_engineer.generation import fallback_scene, generate, repair, revise
from manim_engineer.llm import LLMBackend, LLMError
from manim_engineer.output import RenderError, publish
from manim_engineer.pipeline.config import RunConfig
from manim_engineer.verification import (
    critique,
    extract_section_frames,
    verify_tier0,
    verify_tier1,
)


@dataclass
class AttemptRecord:
    attempt: int
    kind: str  # generate | repair | visual_repair | fallback | revise
    code_path: str
    model: str = ""
    tier0_ok: bool | None = None
    tier1_ok: bool | None = None
    tier2_ok: bool | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    elapsed_s: float = 0.0
    error: str = ""


@dataclass
class ConceptResult:
    concept_id: str
    plan_id: str
    status: str
    attempts: list[AttemptRecord] = field(default_factory=list)
    accepted_code: str | None = None
    bundle_dir: str | None = None
    bundle: dict[str, Any] | None = None
    final_findings: list[dict[str, Any]] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    critique_summary: str = ""
    llm_calls: int = 0
    elapsed_s: float = 0.0
    used_fallback: bool = False
    message: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, default=str)


def _write_attempt(cdir: Path, n: int, code: str) -> Path:
    cdir.mkdir(parents=True, exist_ok=True)
    p = cdir / f"attempt_{n:02d}.py"
    p.write_text(code)
    return p


def _record(rec: AttemptRecord, reports: list[TierReport]) -> None:
    for r in reports:
        if r.tier == 0:
            rec.tier0_ok = r.ok
        elif r.tier == 1:
            rec.tier1_ok = r.ok
        elif r.tier == 2:
            rec.tier2_ok = r.ok
            rec.scores = r.scores
        rec.findings.extend(f.model_dump() for f in r.findings)


def _deterministic(cand: Candidate, plan: AnimationPlan, cfg: RunConfig) -> list[TierReport]:
    t0 = verify_tier0(cand, plan)
    reports = [t0]
    if t0.ok:
        reports.append(verify_tier1(cand, plan, pixel_height=cfg.probe_pixel_height))
    return reports


def _fatal(reports: list[TierReport]) -> list[Finding]:
    return [f for r in reports for f in r.findings if f.severity == Severity.FATAL]


def _notes(reports: list[TierReport]) -> str:
    return "\n".join(r.notes for r in reports if r.tier == 1 and not r.ok and r.notes)


def _category_key(findings: list[Finding]) -> str:
    return "|".join(
        sorted({f"{f.gate}:{f.category or ''}:{(f.message or '')[:40]}" for f in findings})
    )


def realize_plan(
    plan: AnimationPlan, run_dir: Path, backend: LLMBackend, cfg: RunConfig, log=print
) -> ConceptResult:
    t_start = time.time()
    cid = plan.concept.concept_id
    cdir = run_dir / "candidates" / cid
    result = ConceptResult(concept_id=cid, plan_id=plan.plan_id, status=PlanStatus.CODING)
    policy = cfg.repair
    attempt = 0
    code: str | None = None
    reports: list[TierReport] = []
    last_key = ""
    repeats = 0
    det_repairs = 0
    accepted: Candidate | None = None

    def next_attempt(kind: str, new_code: str, model: str = "") -> Candidate:
        nonlocal attempt, code
        attempt += 1
        code = new_code
        path = _write_attempt(cdir, attempt, new_code)
        cand = Candidate(
            plan_id=plan.plan_id,
            attempt=attempt,
            code_path=str(path),
            scene_class=plan.scene_class,
            model=model,
        )
        result.attempts.append(
            AttemptRecord(attempt=attempt, kind=kind, code_path=str(path), model=model)
        )
        return cand

    # ------------------------------------------------------------ generate
    try:
        g = generate(plan, backend)
        result.llm_calls += 1
        cand = next_attempt("generate", g.code, g.model)
    except LLMError as e:
        log(f"  [{cid}] generation failed: {e}; using template fallback")
        cand = next_attempt("fallback", fallback_scene(plan))
        result.used_fallback = True

    # ------------------------------------------------------------ deterministic loop
    while True:
        t0 = time.time()
        reports = _deterministic(cand, plan, cfg)
        rec = result.attempts[-1]
        _record(rec, reports)
        rec.elapsed_s = round(time.time() - t0, 2)
        fatal = _fatal(reports)
        if not fatal:
            accepted = cand
            break
        log(
            f"  [{cid}] attempt {attempt}: {len(fatal)} blocking finding(s): {fatal[0].one_line()[:140]}"
        )
        key = _category_key(fatal)
        repeats = repeats + 1 if key == last_key else 0
        last_key = key
        can_repair = (
            det_repairs < policy.deterministic_attempts
            and result.llm_calls < policy.max_llm_calls_per_concept
            and not (policy.abort_on_repeated_category and repeats >= 2)
            and not result.used_fallback
        )
        if can_repair:
            try:
                r = repair(plan, code or "", fatal, backend, notes=_notes(reports))
                result.llm_calls += 1
                det_repairs += 1
                cand = next_attempt("repair", r.code, r.model)
                continue
            except LLMError as e:
                log(f"  [{cid}] repair call failed: {e}")
        if policy.fallback_to_template and not result.used_fallback:
            log(f"  [{cid}] repair budget exhausted; falling back to template scene")
            cand = next_attempt("fallback", fallback_scene(plan))
            result.used_fallback = True
            continue
        result.status = PlanStatus.REJECTED
        result.final_findings = [f.model_dump() for f in fatal]
        result.message = "no candidate passed deterministic verification"
        result.elapsed_s = round(time.time() - t_start, 1)
        return result

    # ------------------------------------------------------------ publish + critique
    assert accepted is not None
    bundle_dir = run_dir / "animations" / cid
    try:
        bundle = publish(
            accepted.code_path,
            plan.scene_class,
            bundle_dir,
            plan=plan,
            quality=cfg.quality,
            gif_width=cfg.gif_width,
            gif_fps=cfg.gif_fps,
            media_dir=run_dir / "media" / cid,
        )
    except RenderError as e:
        # A render failure after a clean probe is rare (LaTeX at render time, etc.); try one repair then fallback.
        log(f"  [{cid}] render failed: {str(e)[-300:]}")
        result.attempts[-1].error = str(e)[-800:]
        if not result.used_fallback:
            cand = next_attempt("fallback", fallback_scene(plan))
            result.used_fallback = True
            reports = _deterministic(cand, plan, cfg)
            _record(result.attempts[-1], reports)
            try:
                bundle = publish(
                    cand.code_path,
                    plan.scene_class,
                    bundle_dir,
                    plan=plan,
                    quality=cfg.quality,
                    gif_width=cfg.gif_width,
                    gif_fps=cfg.gif_fps,
                    media_dir=run_dir / "media" / cid,
                )
                accepted = cand
            except RenderError as e2:
                result.status = PlanStatus.REJECTED
                result.message = f"render failed twice: {str(e2)[-300:]}"
                result.elapsed_s = round(time.time() - t_start, 1)
                return result
        else:
            result.status = PlanStatus.REJECTED
            result.message = f"render failed: {str(e)[-300:]}"
            result.elapsed_s = round(time.time() - t_start, 1)
            return result

    result.bundle_dir = str(bundle_dir)
    result.bundle = bundle.model_dump()
    result.accepted_code = accepted.code_path
    warn = [f for r in reports for f in r.findings if f.severity != Severity.FATAL]
    result.final_findings = [f.model_dump() for f in warn]

    if cfg.critique and not result.used_fallback:
        rep2 = _critique(plan, bundle, bundle_dir, backend, reports)
        result.llm_calls += 1
        _record(result.attempts[-1], [rep2])
        result.scores = rep2.scores
        result.critique_summary = rep2.notes
        vis_fatal = [f for f in rep2.findings if f.severity == Severity.FATAL]
        if vis_fatal:
            vis_fatal += [f for f in warn if f.gate in ("sparse", "overlap", "text_too_small")][:6]
        if (
            vis_fatal
            and policy.visual_attempts > 0
            and result.llm_calls < policy.max_llm_calls_per_concept
        ):
            log(f"  [{cid}] visual repair for {len(vis_fatal)} critique finding(s)")
            try:
                r = repair(plan, code or "", vis_fatal, backend, tag="visual_repair")
                result.llm_calls += 1
                cand = next_attempt("visual_repair", r.code, r.model)
                reps = _deterministic(cand, plan, cfg)
                _record(result.attempts[-1], reps)
                if not _fatal(reps):
                    try:
                        bundle2 = publish(
                            cand.code_path,
                            plan.scene_class,
                            bundle_dir,
                            plan=plan,
                            quality=cfg.quality,
                            gif_width=cfg.gif_width,
                            gif_fps=cfg.gif_fps,
                            media_dir=run_dir / "media" / cid,
                        )
                        rep3 = _critique(plan, bundle2, bundle_dir, backend, reps)
                        result.llm_calls += 1
                        _record(result.attempts[-1], [rep3])
                        if (
                            sum(rep3.scores.values()) >= sum(rep2.scores.values())
                        ) or not rep2.scores:
                            bundle, accepted = bundle2, cand
                            result.scores, result.critique_summary = rep3.scores, rep3.notes
                            result.bundle = bundle.model_dump()
                            result.accepted_code = cand.code_path
                        else:
                            # keep the earlier bundle: re-publish it
                            bundle = publish(
                                accepted.code_path,
                                plan.scene_class,
                                bundle_dir,
                                plan=plan,
                                quality=cfg.quality,
                                gif_width=cfg.gif_width,
                                gif_fps=cfg.gif_fps,
                                media_dir=run_dir / "media" / cid,
                            )
                            result.bundle = bundle.model_dump()
                    except RenderError:
                        bundle = publish(
                            accepted.code_path,
                            plan.scene_class,
                            bundle_dir,
                            plan=plan,
                            quality=cfg.quality,
                            gif_width=cfg.gif_width,
                            gif_fps=cfg.gif_fps,
                            media_dir=run_dir / "media" / cid,
                        )
                        result.bundle = bundle.model_dump()
            except LLMError as e:
                log(f"  [{cid}] visual repair failed: {e}")
    result.status = PlanStatus.NEEDS_HUMAN if result.used_fallback else PlanStatus.ACCEPTED
    if result.used_fallback:
        result.message = "template fallback used; review recommended"
    result.elapsed_s = round(time.time() - t_start, 1)
    return result


def _critique(
    plan: AnimationPlan,
    bundle: ArtifactBundle,
    bundle_dir: Path,
    backend: LLMBackend,
    reports: list[TierReport],
) -> TierReport:
    mp4s = [bundle_dir / s.mp4 for s in bundle.sections]
    frames = extract_section_frames(mp4s, bundle_dir / "frames")
    box_summary = "\n".join(r.notes for r in reports if r.tier == 1 and r.ok and r.notes)
    return critique(
        backend,
        plan,
        frames,
        box_summary=box_summary[:4000],
        tag=f"critique_{plan.concept.concept_id}",
    )


def revise_concept(
    plan: AnimationPlan,
    code: str,
    note: str,
    run_dir: Path,
    backend: LLMBackend,
    cfg: RunConfig,
    log=print,
) -> ConceptResult:
    """Apply a reviewer note: revise code → verify → publish. One deterministic repair allowed."""
    cid = plan.concept.concept_id
    cdir = run_dir / "candidates" / cid
    existing = sorted(cdir.glob("attempt_*.py"))
    n = len(existing)
    result = ConceptResult(concept_id=cid, plan_id=plan.plan_id, status=PlanStatus.CODING)
    r = revise(plan, code, note, backend)
    result.llm_calls += 1
    n += 1
    path = _write_attempt(cdir, n, r.code)
    cand = Candidate(
        plan_id=plan.plan_id,
        attempt=n,
        code_path=str(path),
        scene_class=plan.scene_class,
        model=r.model,
    )
    result.attempts.append(
        AttemptRecord(attempt=n, kind="revise", code_path=str(path), model=r.model)
    )
    reports = _deterministic(cand, plan, cfg)
    _record(result.attempts[-1], reports)
    fatal = _fatal(reports)
    if fatal:
        rr = repair(plan, r.code, fatal, backend, notes=_notes(reports))
        result.llm_calls += 1
        n += 1
        path = _write_attempt(cdir, n, rr.code)
        cand = Candidate(
            plan_id=plan.plan_id,
            attempt=n,
            code_path=str(path),
            scene_class=plan.scene_class,
            model=rr.model,
        )
        result.attempts.append(
            AttemptRecord(attempt=n, kind="repair", code_path=str(path), model=rr.model)
        )
        reports = _deterministic(cand, plan, cfg)
        _record(result.attempts[-1], reports)
        fatal = _fatal(reports)
    if fatal:
        result.status = PlanStatus.REJECTED
        result.final_findings = [f.model_dump() for f in fatal]
        result.message = "revision did not pass verification; previous animation kept"
        return result
    bundle_dir = run_dir / "animations" / cid
    try:
        bundle = publish(
            cand.code_path,
            plan.scene_class,
            bundle_dir,
            plan=plan,
            quality=cfg.quality,
            gif_width=cfg.gif_width,
            gif_fps=cfg.gif_fps,
            media_dir=run_dir / "media" / cid,
        )
    except RenderError as e:
        result.status = PlanStatus.REJECTED
        result.message = f"render failed: {str(e)[-300:]}"
        return result
    result.status = PlanStatus.ACCEPTED
    result.bundle_dir = str(bundle_dir)
    result.bundle = bundle.model_dump()
    result.accepted_code = cand.code_path
    result.message = f"revised: {note[:120]}"
    return result
