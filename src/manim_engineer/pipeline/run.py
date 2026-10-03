"""Orchestrator: ingest → plan → realize (parallel) → gallery, all under one run directory."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

from manim_engineer.core import AnimationPlan, Document, ReviewNote
from manim_engineer.ingest import ingest, load_document, save_document
from manim_engineer.llm import LLMBackend, select_backend
from manim_engineer.pipeline.approval import (
    ApprovalError,
    ApprovalPin,
    approve_concept,
    check_pins,
    load_approvals,
    revoke,
    save_approvals,
)
from manim_engineer.pipeline.config import RunConfig
from manim_engineer.pipeline.gallery import write_run_gallery
from manim_engineer.pipeline.realize import ConceptResult, realize_plan, revise_concept
from manim_engineer.planning import (
    LiveReplay,
    MaturityConfig,
    Planner,
    PlannerConfig,
    load_plan,
    plan_document,
    save_plan,
)


class RunDir:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @property
    def document(self) -> Path:
        return self.path / "document.json"

    @property
    def plans(self) -> Path:
        return self.path / "plans"

    @property
    def run_json(self) -> Path:
        return self.path / "run.json"

    @property
    def notes(self) -> Path:
        return self.path / "review" / "notes.json"

    def concept_json(self, cid: str) -> Path:
        return self.path / "concepts" / f"{cid}.json"

    def ensure(self) -> RunDir:
        for d in ("plans", "candidates", "animations", "concepts", "review", "llm_calls", "media"):
            (self.path / d).mkdir(parents=True, exist_ok=True)
        return self

    def load_summary(self) -> dict[str, Any]:
        return json.loads(self.run_json.read_text()) if self.run_json.exists() else {}

    def save_summary(self, summary: dict[str, Any]) -> None:
        self.run_json.write_text(json.dumps(summary, indent=1, default=str))


def _backend(cfg: RunConfig, rd: RunDir) -> LLMBackend:
    return select_backend(
        cfg.backend,
        models=cfg.models or None,
        log_dir=rd.path / "llm_calls",
        effort=cfg.effort or None,
    )


def _planner_cfg(cfg: RunConfig) -> PlannerConfig:
    return PlannerConfig(
        audience=cfg.audience,
        min_salience=cfg.min_salience,
        constraints=list(cfg.constraints),
        allow_3d=cfg.allow_3d,
    )


def _concept_entry(result: ConceptResult, plan: AnimationPlan) -> dict[str, Any]:
    d = asdict(result)
    d["plan"] = plan.model_dump(by_alias=True)
    return d


def ingest_source(source: str, rd: RunDir, cfg: RunConfig) -> Document:
    opts: dict[str, Any] = {}
    if cfg.max_pages:
        opts["max_pages"] = cfg.max_pages
    doc = ingest(source, kind=cfg.input_kind, workdir=rd.path, title=cfg.title, **opts)
    companions = cfg.extra.get("companion") or []
    if companions:
        eqs = []
        for comp in companions:
            cdoc = ingest(str(comp), workdir=rd.path)
            eqs += [
                {"label": s.span.para_id or s.seg_id, "latex": s.latex, "source": cdoc.title}
                for s in cdoc.equations()
                if s.latex
            ]
        doc.meta["companion_equations"] = eqs
        doc.meta["companions"] = [str(c) for c in companions]
    save_document(doc, rd.document)
    return doc


def _settle_approvals(
    rd: RunDir, previous: dict[str, Any], log=print
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Keep run.json entries whose pin holds; revoke broken pins and say why."""
    approvals = load_approvals(rd.path)
    held, broken = check_pins(rd.path, previous, approvals)
    entries = {c.get("concept_id"): c for c in previous.get("concepts", [])}
    for cid, pin in held.items():
        log(f"[approval] {cid}: approved {pin.approved_at} (pin {pin.pin[:12]}); skipped")
    for cid, reason in broken.items():
        revoke(approvals, cid, reason)
        log(f"[approval] {cid}: approval revoked: {reason}")
    if broken:
        save_approvals(rd.path, approvals)
    return {cid: entries[cid] for cid in held}, list(broken)


def _merge_plans(
    fresh: list[AnimationPlan],
    rd: RunDir,
    held: dict[str, dict[str, Any]],
    broken: list[str],
    log=print,
) -> tuple[list[str], list[AnimationPlan]]:
    """This run's concept order and the plans still to realize.

    A held pin keeps its concept in place of a fresh plan. A broken pin renders the
    plan on disk, which is how a hand edit survives a re-run.
    """
    from_disk: dict[str, AnimationPlan] = {}
    for cid in broken:
        try:
            from_disk[cid] = load_plan(rd.plans / f"{cid}.json")
            log(f"[approval] {cid}: re-rendering from plans/{cid}.json")
        except (OSError, ValueError) as e:
            log(
                f"[approval] {cid}: plans/{cid}.json is unusable ({str(e)[:120]}); using this run's plan"
            )
    order: list[str] = []
    to_realize: list[AnimationPlan] = []
    for plan in fresh:
        cid = plan.concept.concept_id
        order.append(cid)
        if cid not in held:
            to_realize.append(from_disk.pop(cid, plan))
    for cid in held:
        if cid not in order:
            order.append(cid)
            log(f"[approval] {cid}: kept although this run did not plan it")
    for cid, plan in from_disk.items():
        order.append(cid)
        to_realize.append(plan)
    return order, to_realize


def run_pipeline(
    source: str,
    out_dir: str | Path,
    cfg: RunConfig | None = None,
    log=print,
    case_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or RunConfig()
    rd = RunDir(out_dir).ensure()
    t0 = time.time()
    backend = _backend(cfg, rd)
    log(f"[run] {source} → {rd.path} (backend {backend.name}, quality {cfg.quality})")
    doc = ingest_source(source, rd, cfg)
    log(f"[ingest] {doc.title!r}: {len(doc.segments)} segments ({doc.modality})")
    plans, skipped = plan_document(
        doc,
        backend,
        _planner_cfg(cfg),
        max_plans=cfg.max_plans,
        on_event=lambda k, b, x: log(
            f"[plan] {k} {b.bucket_id} {b.span_label()}"
            + (f": {x.hint[:100]}" if k == "triaged" and x else "")
        ),
    )
    log(f"[plan] {len(plans)} plan(s), {len(skipped)} passage(s) skipped")
    held, broken = _settle_approvals(rd, rd.load_summary(), log)
    order, to_realize = _merge_plans(plans, rd, held, broken, log)
    for p in to_realize:
        save_plan(p, rd.plans)
    summary: dict[str, Any] = {
        "source": source,
        "title": doc.title,
        "modality": str(doc.modality),
        "n_segments": len(doc.segments),
        "backend": backend.name,
        "config": cfg.to_dict(),
        "plans": order,
        "skipped": skipped,
        # approved entries are saved before realization so a crash cannot drop them
        "concepts": list(held.values()),
        "started_at": t0,
        **(case_meta or {}),
    }
    rd.save_summary(summary)
    results = realize_all(to_realize, rd, backend, cfg, log)
    realized = {p.concept.concept_id: _concept_entry(r, p) for p, r in results}
    summary["concepts"] = [held[cid] if cid in held else realized[cid] for cid in order]
    summary["llm"] = backend.log.summary() if hasattr(backend, "log") else {}
    summary["elapsed_s"] = round(time.time() - t0, 1)
    rd.save_summary(summary)
    write_run_gallery(rd.path, summary)
    statuses = [c.get("status") for c in summary["concepts"]]
    log(
        f"[done] {statuses.count('accepted')}/{len(statuses)} accepted ({len(held)} approved and kept) in {summary['elapsed_s']} s → {rd.path / 'index.html'}"
    )
    return summary


def realize_all(
    plans: list[AnimationPlan], rd: RunDir, backend: LLMBackend, cfg: RunConfig, log=print
) -> list[tuple[AnimationPlan, ConceptResult]]:
    results: list[tuple[AnimationPlan, ConceptResult]] = []
    if not plans:
        return results
    workers = max(1, min(cfg.workers, len(plans)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(realize_plan, p, rd.path, backend, cfg, log): p for p in plans}
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                r = fut.result()
            except Exception as e:  # keep the run alive; record the failure
                r = ConceptResult(
                    concept_id=p.concept.concept_id,
                    plan_id=p.plan_id,
                    status="rejected",
                    message=f"unexpected error: {e}",
                )
            rd.concept_json(p.concept.concept_id).write_text(r.to_json())
            log(
                f"[concept] {p.concept.concept_id}: {r.status} ({r.llm_calls} llm calls, {r.elapsed_s}s) {r.message}"
            )
            results.append((p, r))
    results.sort(key=lambda pr: plans.index(pr[0]))
    return results


def render_plan_file(
    plan_path: str | Path, out_dir: str | Path, cfg: RunConfig | None = None, log=print
) -> ConceptResult:
    """Realize one (possibly hand-edited) plan JSON into a run directory."""
    cfg = cfg or RunConfig()
    rd = RunDir(out_dir).ensure()
    backend = _backend(cfg, rd)
    plan = load_plan(plan_path)
    save_plan(plan, rd.plans)
    r = realize_plan(plan, rd.path, backend, cfg, log)
    rd.concept_json(plan.concept.concept_id).write_text(r.to_json())
    summary = rd.load_summary() or {
        "source": str(plan_path),
        "title": plan.concept.title,
        "modality": "plan",
        "n_segments": 0,
        "backend": backend.name,
        "config": cfg.to_dict(),
        "plans": [],
        "skipped": [],
        "concepts": [],
    }
    summary["concepts"] = [
        c for c in summary.get("concepts", []) if c.get("concept_id") != plan.concept.concept_id
    ] + [_concept_entry(r, plan)]
    summary["llm"] = backend.log.summary()
    rd.save_summary(summary)
    write_run_gallery(rd.path, summary)
    return r


def revise_run(
    out_dir: str | Path,
    concept_id: str,
    note: str,
    cfg: RunConfig | None = None,
    author: str = "",
    log=print,
) -> ConceptResult:
    cfg = cfg or RunConfig()
    rd = RunDir(out_dir).ensure()
    backend = _backend(cfg, rd)
    plan = load_plan(rd.plans / f"{concept_id}.json")
    summary = rd.load_summary()
    entry = next(
        (c for c in summary.get("concepts", []) if c.get("concept_id") == concept_id), None
    )
    if not entry or not entry.get("accepted_code"):
        raise FileNotFoundError(f"no accepted animation for {concept_id} in {rd.path}")
    code = Path(entry["accepted_code"]).read_text()
    plan.meta.revision += 1
    plan.meta.revision_notes.append(note)
    save_plan(plan, rd.plans)
    r = revise_concept(plan, code, note, rd.path, backend, cfg, log)
    notes = json.loads(rd.notes.read_text()) if rd.notes.exists() else []
    notes.append(
        ReviewNote(
            concept_id=concept_id,
            verdict="revise",
            note=note,
            author=author,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        ).model_dump()
    )
    rd.notes.write_text(json.dumps(notes, indent=1))
    if r.status == "accepted":
        prev = entry.copy()
        new_entry = _concept_entry(r, plan)
        new_entry["attempts"] = prev.get("attempts", []) + new_entry["attempts"]
        new_entry["scores"] = prev.get("scores", {})
        summary["concepts"] = [
            new_entry if c.get("concept_id") == concept_id else c for c in summary["concepts"]
        ]
    else:
        entry["message"] = r.message
    summary["llm"] = backend.log.summary()
    rd.save_summary(summary)
    rd.concept_json(concept_id).write_text(r.to_json())
    write_run_gallery(rd.path, summary)
    return r


def approve_run(
    out_dir: str | Path, concept_id: str, author: str = "", note: str = "", log=print
) -> ApprovalPin:
    rd = RunDir(out_dir)
    summary = rd.load_summary()
    pin = approve_concept(rd.path, summary, concept_id, author=author, note=note)
    write_run_gallery(rd.path, summary)
    log(f"[approval] {concept_id}: approved (pin {pin.pin[:12]})")
    return pin


def unapprove_run(out_dir: str | Path, concept_id: str, author: str = "", log=print) -> ApprovalPin:
    rd = RunDir(out_dir)
    approvals = load_approvals(rd.path)
    pin = revoke(approvals, concept_id, f"unapproved by {author}" if author else "unapproved")
    if pin is None:
        raise ApprovalError(f"{concept_id} is not approved in {rd.path}")
    save_approvals(rd.path, approvals)
    write_run_gallery(rd.path, rd.load_summary())
    log(f"[approval] {concept_id}: {pin.revoked_reason}")
    return pin


def run_live(
    source: str,
    out_dir: str | Path,
    cfg: RunConfig | None = None,
    chunk: int = 3,
    log=print,
    case_meta: dict[str, Any] | None = None,
    sleep_s: float = 0.0,
) -> dict[str, Any]:
    """Replay a recorded input as a live stream: plans and animations are produced as buckets mature."""
    import time as _t

    cfg = cfg or RunConfig()
    rd = RunDir(out_dir).ensure()
    approved = sorted(load_approvals(rd.path).approved)
    if approved:
        raise ApprovalError(
            f"{rd.path} has approved concepts ({', '.join(approved)}); live replay would "
            "overwrite them. Replay into a new --out directory."
        )
    t0 = time.time()
    backend = _backend(cfg, rd)
    doc = ingest_source(source, rd, cfg) if not rd.document.exists() else load_document(rd.document)
    log(f"[live] replaying {len(doc.segments)} segments in chunks of {chunk}")
    planner = Planner(backend, _planner_cfg(cfg))
    live = LiveReplay(planner, doc, MaturityConfig(), max_plans=cfg.max_plans)
    summary: dict[str, Any] = {
        "source": source,
        "title": doc.title,
        "modality": str(doc.modality),
        "n_segments": len(doc.segments),
        "backend": backend.name,
        "config": cfg.to_dict(),
        "plans": [],
        "skipped": [],
        "concepts": [],
        "mode": "live",
        "timeline": [],
        **(case_meta or {}),
    }
    results: list[tuple[AnimationPlan, ConceptResult]] = []
    ex = ThreadPoolExecutor(max_workers=max(1, cfg.workers))
    futs = {}

    def handle(ev):
        if ev.kind == "planned" and ev.plan is not None:
            save_plan(ev.plan, rd.plans)
            summary["plans"].append(ev.plan.concept.concept_id)
            summary["timeline"].append(
                {
                    "t": round(time.time() - t0, 1),
                    "event": "planned",
                    "concept": ev.plan.concept.concept_id,
                    "watermark": live.state.watermark,
                }
            )
            log(
                f"[live t+{time.time() - t0:.0f}s] planned {ev.plan.concept.concept_id} after {live.state.watermark} segments"
            )
            futs[ex.submit(realize_plan, ev.plan, rd.path, backend, cfg, log)] = ev.plan
        elif ev.kind == "skipped" and ev.triage is not None:
            summary["skipped"].append((ev.bucket_id, ev.message))
        elif ev.kind == "error":
            summary["skipped"].append((ev.bucket_id, ev.message))

    for i in range(0, len(doc.segments), chunk):
        for ev in live.feed(doc.segments[i : i + chunk]):
            handle(ev)
        if sleep_s:
            _t.sleep(sleep_s)
        done = [f for f in futs if f.done()]
        for f in done:
            p = futs.pop(f)
            r = f.result()
            rd.concept_json(p.concept.concept_id).write_text(r.to_json())
            results.append((p, r))
            summary["timeline"].append(
                {
                    "t": round(time.time() - t0, 1),
                    "event": r.status,
                    "concept": p.concept.concept_id,
                }
            )
            summary["concepts"] = [_concept_entry(rr, pp) for pp, rr in results]
            rd.save_summary(summary)
            write_run_gallery(rd.path, summary)
    for ev in live.finish():
        handle(ev)
    for f in as_completed(list(futs)):
        p = futs[f]
        r = f.result()
        rd.concept_json(p.concept.concept_id).write_text(r.to_json())
        results.append((p, r))
        summary["timeline"].append(
            {"t": round(time.time() - t0, 1), "event": r.status, "concept": p.concept.concept_id}
        )
    ex.shutdown(wait=True)
    summary["concepts"] = [_concept_entry(r, p) for p, r in results]
    summary["llm"] = backend.log.summary()
    summary["elapsed_s"] = round(time.time() - t0, 1)
    rd.save_summary(summary)
    write_run_gallery(rd.path, summary)
    log(
        f"[live done] {len(results)} concept(s) in {summary['elapsed_s']} s → {rd.path / 'index.html'}"
    )
    return summary
