"""Planner: triage a bucket, then produce a validated AnimationPlan."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import ValidationError

from manim_engineer.core import (
    AnimationPlan,
    Archetype,
    ArchetypeChoice,
    Audience,
    AudienceLevel,
    Beat,
    Budgets,
    Concept,
    Document,
    Equation,
    Layout,
    PlanMeta,
    Provenance,
    ReviewCriterion,
    ReviewSpec,
    SegmentKind,
    SymbolEntry,
)
from manim_engineer.llm import LLMBackend, LLMError, LLMRequest
from manim_engineer.planning.bucketer import Bucket
from manim_engineer.planning.prompts import PLAN_SCHEMA, TRIAGE_SCHEMA, plan_prompt, triage_prompt


class PlanError(RuntimeError):
    pass


@dataclass
class Triage:
    worth_animating: bool
    salience: int
    concept_name: str
    reason: str
    archetype: str
    difficulty: str = "medium"
    has_equation: bool = False

    @property
    def hint(self) -> str:
        return f"{self.concept_name} ({self.archetype}, salience {self.salience}/5, {self.difficulty}): {self.reason}"


@dataclass
class PlannerConfig:
    audience: str = "mixed"
    min_salience: int = 3
    constraints: list[str] = field(default_factory=list)
    default_duration_s: float = 24.0
    allow_3d: bool = False


def slugify(s: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    s = re.sub(r"_+", "_", s)[:max_len].strip("_")
    if not s or not s[0].isalpha():
        s = "c_" + s
    return s or "concept"


def _beat_id(raw: str, n: int) -> str:
    m = re.fullmatch(r"b(\d{1,2})_([a-z0-9_]+)", raw.strip().lower())
    if m:
        return f"b{n}_{m.group(2)[:40]}"
    return f"b{n}_{slugify(raw, 30) or 'beat'}"


def _ledger_index(doc: Document) -> dict[str, dict]:
    """para_id -> ledger entry, for documents ingested with an equation ledger."""
    return {
        str(e.get("para_id", "")): e
        for e in (doc.meta.get("equation_ledger") or [])
        if e.get("para_id")
    }


def _eq_label(para_id: str, seg_id: str, ledger: dict[str, dict]) -> str:
    entry = ledger.get(para_id)
    if entry and entry.get("label"):
        return str(entry["label"])
    return para_id or seg_id


def _norm_latex(s: str) -> str:
    return "".join(s.split())


def _equations(data: dict, eq_segs, ledger: dict[str, dict]) -> list[Equation]:
    """Source equations outrank anything the model re-typed.

    An equation the model produced that the source also contains would otherwise
    replace the verbatim one, which is the accuracy risk this ordering removes.
    """
    out: list[Equation] = []
    seen: set[str] = set()
    for s in eq_segs:
        if not s.latex:
            continue
        pid = s.span.para_id or ""
        entry = ledger.get(pid) or {}
        out.append(
            Equation(
                label=_eq_label(pid, s.seg_id, ledger),
                latex=s.latex,
                para_id=pid,
                env=str(entry.get("env", "")),
                verbatim=True,
            )
        )
        seen.add(_norm_latex(s.latex))
    for i, e in enumerate(data.get("equations") or []):
        latex = str(e.get("latex") or "")
        if not latex or _norm_latex(latex) in seen:
            continue
        out.append(Equation(label=str(e.get("label") or f"eq{i + 1}"), latex=latex))
        seen.add(_norm_latex(latex))
    return out


class Planner:
    def __init__(self, backend: LLMBackend, config: PlannerConfig | None = None):
        self.backend = backend
        self.cfg = config or PlannerConfig()

    # ------------------------------------------------------------------ triage
    def triage(self, bucket: Bucket, doc: Document) -> Triage:
        req = LLMRequest(
            prompt=triage_prompt(bucket.text, doc.title, bucket.span_label(), bucket.heading),
            tier="fast",
            json_schema=TRIAGE_SCHEMA,
            tag=f"triage_{bucket.bucket_id}",
            max_tokens=600,
        )
        data = self.backend.complete(req).require_structured()
        arch = data.get("archetype", "equation_derivation")
        if arch not in {a.value for a in Archetype}:
            arch = "equation_derivation"
        return Triage(
            worth_animating=bool(data.get("worth_animating")),
            salience=int(data.get("salience", 1)),
            concept_name=str(data.get("concept_name", "concept"))[:80],
            reason=str(data.get("reason", "")),
            archetype=arch,
            difficulty=str(data.get("difficulty", "medium")),
            has_equation=bool(data.get("has_equation", False)),
        )

    # ------------------------------------------------------------------ plan
    def plan(
        self,
        bucket: Bucket,
        doc: Document,
        triage: Triage | None,
        context_summary: str = "",
        extra_constraints: list[str] | None = None,
    ) -> AnimationPlan:
        eq_segs = [s for s in bucket.segments if s.kind == SegmentKind.EQUATION and s.latex]
        ledger = _ledger_index(doc)
        equations = [
            f"{_eq_label(s.span.para_id or '', s.seg_id, ledger)}: {s.latex}"
            for s in eq_segs
            if s.latex
        ]
        for ce in doc.meta.get("companion_equations", []) or []:
            if ce.get("latex"):
                equations.append(f"{ce['latex']}   (companion: {ce.get('source', '')})")
        cons = list(self.cfg.constraints) + list(extra_constraints or [])
        if not self.cfg.allow_3d:
            cons.append("Do not use 3D.")
        prompt = plan_prompt(
            bucket.text,
            doc.title,
            bucket.span_label(),
            equations,
            triage.hint if triage else "n/a",
            self.cfg.audience,
            cons,
            context_summary,
        )
        last_err = ""
        for _attempt in range(2):
            req = LLMRequest(
                prompt=prompt
                if not last_err
                else f"{prompt}\n\nYour previous plan was rejected: {last_err}\nFix it and return the full JSON again.",
                tier="strong",
                json_schema=PLAN_SCHEMA,
                tag=f"plan_{bucket.bucket_id}",
                max_tokens=6000,
            )
            try:
                data = self.backend.complete(req).require_structured()
                return self.build_plan(data, bucket, doc, triage, eq_segs)
            except (ValidationError, ValueError, LLMError) as e:
                last_err = str(e)[:800]
        raise PlanError(f"planner failed for {bucket.bucket_id}: {last_err}")

    def build_plan(
        self, data: dict, bucket: Bucket, doc: Document, triage: Triage | None, eq_segs=()
    ) -> AnimationPlan:
        concept_id = slugify(
            str(
                data.get("concept_id")
                or data.get("title")
                or (triage.concept_name if triage else "concept")
            )
        )
        beats_raw = data.get("beats") or []
        beats: list[Beat] = []
        for i, b in enumerate(beats_raw, 1):
            beats.append(
                Beat(
                    beat_id=_beat_id(str(b.get("beat_id", f"b{i}_beat")), i),
                    purpose=str(b.get("purpose", ""))[:300],
                    visuals=str(b.get("visuals", ""))[:1200],
                    narration=str(b.get("narration", ""))[:600],
                    duration_s=float(min(max(b.get("duration_s", 4), 1), 20)),
                    wait_after_s=float(min(max(b.get("wait_after_s", 0.5), 0), 4)),
                )
            )
        target = float(data.get("target_duration_s") or self.cfg.default_duration_s)
        total = sum(b.duration_s + b.wait_after_s for b in beats)
        target = max(target, total / 1.4, 8.0)
        arch = data.get("archetype") or (triage.archetype if triage else "equation_derivation")
        sec = data.get("secondary_archetype") or None
        provenance = Provenance(
            source_spans=[s.span for s in bucket.segments if s.kind != SegmentKind.HEADING][:12],
            quotes=[q for q in (data.get("quotes") or []) if isinstance(q, str)][:3],
            equations=_equations(data, eq_segs, _ledger_index(doc)),
            segment_ids=[s.seg_id for s in bucket.segments],
            macros=str(doc.meta.get("macros", "")),
        )
        level = data.get("audience_level") or self.cfg.audience
        if level not in {a.value for a in AudienceLevel}:
            level = "mixed"
        plan = AnimationPlan(
            plan_id=f"plan_{concept_id}",
            concept=Concept(
                concept_id=concept_id,
                title=str(data.get("title") or concept_id)[:80],
                one_line=str(data.get("one_line", ""))[:300],
                claim=str(data.get("claim", ""))[:400],
                evidence=str(data.get("evidence", ""))[:600],
                takeaway=str(data.get("takeaway", ""))[:400],
                prerequisites=[str(p) for p in (data.get("prerequisites") or [])][:6],
            ),
            provenance=provenance,
            audience=Audience(level=AudienceLevel(level)),
            archetype=ArchetypeChoice(
                primary=Archetype(arch),
                secondary=Archetype(sec)
                if sec and sec in {a.value for a in Archetype} and sec != arch
                else None,
                confidence=float(data.get("archetype_confidence", 0.6)),
            ),
            budgets=Budgets(
                target_duration_s=min(target, 90.0),
                max_beats=max(len(beats), 6),
                allow_3d=self.cfg.allow_3d,
            ),
            layout=Layout(template=data.get("layout_template") or "TOP_PERSISTENT_BOTTOM_CONTENT"),
            symbol_ledger=[
                SymbolEntry(
                    symbol=str(s.get("symbol", "")),
                    latex=str(s.get("latex", s.get("symbol", ""))),
                    meaning=str(s.get("meaning", "")),
                    color=s.get("color") or None,
                )
                for s in (data.get("symbol_ledger") or [])
                if s.get("symbol")
            ][:12],
            beats=beats,
            review=ReviewSpec(
                success_criteria=[
                    ReviewCriterion(
                        id="renders", check="automatic", **{"assert": "Tier 0 and Tier 1 pass"}
                    ),
                    ReviewCriterion(
                        id="claim_shown",
                        check="vlm",
                        **{"assert": f"final frames support: {str(data.get('claim', ''))[:120]}"},
                    ),
                    ReviewCriterion(
                        id="faithful",
                        check="human",
                        **{"assert": "no assertion beyond the source passage"},
                    ),
                ],
                blocking=["renders"],
            ),
            meta=PlanMeta(
                created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                planner_model=self.backend.model_for("strong"),
                priority=float(
                    min(max(data.get("priority", (triage.salience / 5) if triage else 0.5), 0), 1)
                ),
            ),
        )
        return plan
