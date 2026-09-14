"""planning bounded context: buckets → triage → validated AnimationPlan (ADR 0003)."""

from __future__ import annotations

import json
from pathlib import Path

from manim_engineer.core import AnimationPlan, Document
from manim_engineer.llm import LLMBackend
from manim_engineer.planning.bucketer import (
    Bucket,
    Bucketer,
    MaturityConfig,
    MaturityVerdict,
    bucket_document,
)
from manim_engineer.planning.live import LiveEvent, LiveReplay, LiveState
from manim_engineer.planning.planner import PlanError, Planner, PlannerConfig, Triage, slugify
from manim_engineer.planning.prompts import PLAN_SCHEMA, TRIAGE_SCHEMA


def plan_document(
    doc: Document,
    backend: LLMBackend,
    planner_config: PlannerConfig | None = None,
    maturity: MaturityConfig | None = None,
    max_plans: int | None = None,
    on_event=None,
) -> tuple[list[AnimationPlan], list[tuple[str, str]]]:
    """Batch planning: bucket everything, triage each mature bucket, plan the best ones.

    Returns (plans, skipped) where skipped is a list of (bucket_id, reason).
    """
    planner = Planner(backend, planner_config)
    buckets = bucket_document(doc, maturity)
    triaged: list[tuple[Bucket, Triage]] = []
    skipped: list[tuple[str, str]] = []
    for b in buckets:
        try:
            tri = planner.triage(b, doc)
        except Exception as e:
            skipped.append((b.bucket_id, f"triage failed: {e}"))
            if on_event:
                on_event("error", b, None)
            continue
        if on_event:
            on_event("triaged", b, tri)
        if tri.worth_animating and tri.salience >= planner.cfg.min_salience:
            triaged.append((b, tri))
        else:
            skipped.append((b.bucket_id, tri.reason))
    triaged = merge_same_concept(triaged)
    triaged.sort(key=lambda bt: (-bt[1].salience, bt[0].opened_at))
    if max_plans is not None:
        for b, tri in triaged[max_plans:]:
            skipped.append((b.bucket_id, f"over plan budget (salience {tri.salience})"))
        triaged = triaged[:max_plans]
    triaged.sort(key=lambda bt: bt[0].opened_at)
    plans: list[AnimationPlan] = []
    seen_ids: set[str] = set()
    for b, tri in triaged:
        try:
            plan = planner.plan(
                b, doc, tri, context_summary="; ".join(p.concept.title for p in plans[-6:])
            )
        except PlanError as e:
            skipped.append((b.bucket_id, str(e)))
            if on_event:
                on_event("error", b, tri)
            continue
        if plan.concept.concept_id in seen_ids:
            plan.concept.concept_id = f"{plan.concept.concept_id}_{len(plans) + 1}"
            plan.plan_id = f"plan_{plan.concept.concept_id}"
        seen_ids.add(plan.concept.concept_id)
        plans.append(plan)
        if on_event:
            on_event("planned", b, plan)
    return plans, skipped


def merge_same_concept(triaged: list[tuple[Bucket, Triage]]) -> list[tuple[Bucket, Triage]]:
    """Adjacent buckets whose triage named the same concept are one animation, not two."""
    out: list[tuple[Bucket, Triage]] = []
    for b, tri in triaged:
        if out:
            pb, pt = out[-1]
            if _same_concept(pt.concept_name, tri.concept_name):
                merged = Bucket(
                    bucket_id=pb.bucket_id,
                    segments=pb.segments + b.segments,
                    centroid=pb.centroid,
                    opened_at=pb.opened_at,
                    last_add=b.last_add,
                    closed=True,
                    heading=pb.heading or b.heading,
                )
                out[-1] = (merged, pt if pt.salience >= tri.salience else tri)
                continue
        out.append((b, tri))
    return out


def _same_concept(a: str, b: str) -> bool:
    ta = {w for w in slugify(a).split("_") if len(w) > 3}
    tb = {w for w in slugify(b).split("_") if len(w) > 3}
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.5


def save_plan(plan: AnimationPlan, plans_dir: str | Path) -> Path:
    d = Path(plans_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{plan.concept.concept_id}.json"
    p.write_text(json.dumps(plan.model_dump(by_alias=True), indent=1))
    (d / f"{plan.concept.concept_id}.md").write_text(plan.to_markdown())
    return p


def load_plan(path: str | Path) -> AnimationPlan:
    return AnimationPlan.model_validate_json(Path(path).read_text())


__all__ = [
    "PLAN_SCHEMA",
    "TRIAGE_SCHEMA",
    "Bucket",
    "Bucketer",
    "LiveEvent",
    "LiveReplay",
    "LiveState",
    "MaturityConfig",
    "MaturityVerdict",
    "PlanError",
    "Planner",
    "PlannerConfig",
    "Triage",
    "bucket_document",
    "load_plan",
    "plan_document",
    "save_plan",
    "slugify",
]
