"""Live replay: feed a growing document through the bucketer with a watermark."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from manim_engineer.core import AnimationPlan, Document, Segment
from manim_engineer.planning.bucketer import Bucket, Bucketer, MaturityConfig
from manim_engineer.planning.planner import PlanError, Planner, Triage


@dataclass
class LiveEvent:
    kind: str  # absorbed | mature | skipped | planned | error
    bucket_id: str = ""
    segment_id: str = ""
    triage: Triage | None = None
    plan: AnimationPlan | None = None
    message: str = ""


@dataclass
class LiveState:
    watermark: int = 0
    plans: list[AnimationPlan] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    processed_ids: set[str] = field(default_factory=set)


class LiveReplay:
    """Drive `feed()` repeatedly with new segments; plans come out as buckets mature."""

    def __init__(
        self,
        planner: Planner,
        doc: Document,
        config: MaturityConfig | None = None,
        max_plans: int | None = None,
    ):
        self.planner = planner
        self.doc = doc
        self.bucketer = Bucketer(config)
        self.state = LiveState()
        self.max_plans = max_plans

    def feed(self, segments: list[Segment]) -> Iterator[LiveEvent]:
        for seg in segments:
            if seg.seg_id in self.state.processed_ids:
                continue  # never process a segment twice
            self.state.processed_ids.add(seg.seg_id)
            self.state.watermark += 1
            b = self.bucketer.absorb(seg)
            yield LiveEvent(kind="absorbed", bucket_id=b.bucket_id, segment_id=seg.seg_id)
            yield from self._sweep()

    def finish(self) -> Iterator[LiveEvent]:
        yield from self._sweep(force=True)

    def _sweep(self, force: bool = False) -> Iterator[LiveEvent]:
        for bucket in self.bucketer.sweep(force=force):
            if self.max_plans is not None and len(self.state.plans) >= self.max_plans:
                yield LiveEvent(
                    kind="skipped", bucket_id=bucket.bucket_id, message="plan budget reached"
                )
                continue
            yield from self._handle(bucket)

    def _handle(self, bucket: Bucket) -> Iterator[LiveEvent]:
        yield LiveEvent(kind="mature", bucket_id=bucket.bucket_id, message=bucket.span_label())
        try:
            tri = self.planner.triage(bucket, self.doc)
        except Exception as e:  # LLM failure: keep the stream alive
            yield LiveEvent(kind="error", bucket_id=bucket.bucket_id, message=f"triage failed: {e}")
            return
        if not tri.worth_animating or tri.salience < self.planner.cfg.min_salience:
            self.state.skipped.append((bucket.bucket_id, tri.reason))
            yield LiveEvent(
                kind="skipped", bucket_id=bucket.bucket_id, triage=tri, message=tri.reason
            )
            return
        try:
            plan = self.planner.plan(bucket, self.doc, tri, context_summary=self._context())
        except PlanError as e:
            yield LiveEvent(kind="error", bucket_id=bucket.bucket_id, triage=tri, message=str(e))
            return
        self.state.plans.append(plan)
        yield LiveEvent(kind="planned", bucket_id=bucket.bucket_id, triage=tri, plan=plan)

    def _context(self) -> str:
        return "; ".join(p.concept.title for p in self.state.plans[-6:])
