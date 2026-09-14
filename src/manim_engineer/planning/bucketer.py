"""Bucketing and maturity: group segments into concept buckets, promote mature ones.

The owner's idea, made concrete: `mature(bucket)` is a scored predicate over
mass, boundary evidence, staleness, concreteness and dedup
(docs/research/ingestion-planning.md §2.3). Works identically on a replayed
recording and on a live stream because it only ever consumes appended segments.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from manim_engineer.core import Document, Segment, SegmentKind
from manim_engineer.planning.text import (
    Vectorizer,
    add_to_centroid,
    concreteness,
    cosine,
    jaccard,
    top_terms,
)


@dataclass
class Bucket:
    bucket_id: str
    segments: list[Segment] = field(default_factory=list)
    centroid: dict[str, float] = field(default_factory=dict)
    opened_at: int = 0
    last_add: int = 0
    closed: bool = False
    heading: str = ""

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.segments if s.kind != SegmentKind.HEADING)

    @property
    def words(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)

    @property
    def has_equation(self) -> bool:
        return any(s.kind == SegmentKind.EQUATION for s in self.segments)

    @property
    def terms(self) -> list[str]:
        return top_terms(self.centroid)

    def span_label(self) -> str:
        spans = [s.span for s in self.segments]
        if not spans:
            return ""
        first, last = spans[0], spans[-1]
        if first.t_start_s is not None:
            return f"{first.label().split('–')[0]}–{last.label().split('–')[-1]}"
        if first.slide_index is not None:
            return (
                f"slides {first.slide_index}–{last.slide_index}"
                if first.slide_index != last.slide_index
                else first.label()
            )
        return f"{first.label()}…{last.label()}"


@dataclass
class MaturityConfig:
    join_threshold: float = 0.12
    min_words: int = 70
    min_words_with_equation: int = 25
    max_words: int = 900
    stale_ticks: int = 6
    min_concreteness: float = 0.15
    dedup_jaccard: float = 0.55


@dataclass
class MaturityVerdict:
    mature: bool
    score: float
    reasons: list[str]


class Bucketer:
    def __init__(self, config: MaturityConfig | None = None):
        self.cfg = config or MaturityConfig()
        self.vec = Vectorizer()
        self.active: list[Bucket] = []
        self.emitted_terms: list[list[str]] = []
        self.dropped: list[Bucket] = []
        self.tick = 0
        self._n = 0
        self._last_slide: int | None = None

    # ------------------------------------------------------------------ absorb
    def absorb(self, seg: Segment) -> Bucket:
        self.tick += 1
        self.vec.fit_one(seg.text)
        boundary = self._boundary(seg)
        vec = self.vec.vector(seg.text)
        target: Bucket | None = None
        if not boundary and self.active:
            cur = self.active[-1]
            content_words = sum(
                len(x.text.split()) for x in cur.segments if x.kind != SegmentKind.HEADING
            )
            if content_words == 0:
                target = cur  # heading-only bucket: first content always joins it
            elif seg.kind in (SegmentKind.EQUATION, SegmentKind.CODE, SegmentKind.SLIDE_NOTES):
                target = cur
            elif content_words < self.cfg.min_words:
                target = cur  # too small to stand alone: keep absorbing
            else:
                best, best_sim = None, 0.0
                for b in self.active[-3:]:
                    sim = cosine(b.centroid, vec)
                    if sim > best_sim:
                        best, best_sim = b, sim
                if best is not None and best_sim >= self.cfg.join_threshold:
                    target = best
        if target is None:
            for b in self.active:
                b.closed = True
            target = Bucket(bucket_id=f"k{self._n:03d}", opened_at=self.tick)
            self._n += 1
            self.active.append(target)
            if seg.kind == SegmentKind.HEADING:
                target.heading = seg.text
        n = len([s for s in target.segments if s.kind != SegmentKind.HEADING])
        target.segments.append(seg)
        if seg.kind != SegmentKind.HEADING and vec:
            target.centroid = add_to_centroid(target.centroid, vec, n)
        target.last_add = self.tick
        if target.words >= self.cfg.max_words:
            target.closed = True
        return target

    def _boundary(self, seg: Segment) -> bool:
        if seg.kind == SegmentKind.HEADING:
            return True
        si = seg.span.slide_index
        if si is not None:
            changed = self._last_slide is not None and si != self._last_slide
            self._last_slide = si
            return changed
        return False

    # ------------------------------------------------------------------ maturity
    def verdict(self, b: Bucket, force: bool = False) -> MaturityVerdict:
        cfg = self.cfg
        reasons: list[str] = []
        min_words = cfg.min_words_with_equation if b.has_equation else cfg.min_words
        mass_ok = b.words >= min_words
        if not mass_ok:
            reasons.append(f"mass {b.words}<{min_words}")
        stale = (self.tick - b.last_add) >= cfg.stale_ticks
        boundary = b.closed
        if not (boundary or stale or force):
            reasons.append("still open")
        conc = concreteness(b.text) + (0.3 if b.has_equation else 0.0)
        if conc < cfg.min_concreteness:
            reasons.append(f"abstract ({conc:.2f})")
        dup = any(jaccard(b.terms, t) >= cfg.dedup_jaccard for t in self.emitted_terms)
        if dup:
            reasons.append("duplicate of emitted concept")
        score = (
            min(1.0, b.words / 250) * 0.4
            + min(1.0, conc) * 0.4
            + (0.2 if boundary or stale else 0.0)
        )
        mature = (
            mass_ok and (boundary or stale or force) and conc >= cfg.min_concreteness and not dup
        )
        return MaturityVerdict(mature=mature, score=round(score, 3), reasons=reasons)

    def sweep(self, force: bool = False) -> list[Bucket]:
        """Return mature buckets (removed from active); drop dead ones."""
        out: list[Bucket] = []
        keep: list[Bucket] = []
        for b in self.active:
            v = self.verdict(b, force=force)
            if v.mature:
                self.emitted_terms.append(b.terms)
                out.append(b)
            elif (b.closed or force) and (self.tick - b.last_add) >= cfg_stale(self):
                self.dropped.append(b)  # closed and not worth animating
            else:
                keep.append(b)
        self.active = keep
        return out

    def flush(self) -> list[Bucket]:
        return self.sweep(force=True)


def cfg_stale(bk: Bucketer) -> int:
    return bk.cfg.stale_ticks


def bucket_document(doc: Document, config: MaturityConfig | None = None) -> list[Bucket]:
    """Batch mode: absorb everything, then flush. Order preserved."""
    bk = Bucketer(config)
    out: list[Bucket] = []
    for seg in doc.segments:
        bk.absorb(seg)
        out.extend(bk.sweep())
    out.extend(bk.flush())
    return out
