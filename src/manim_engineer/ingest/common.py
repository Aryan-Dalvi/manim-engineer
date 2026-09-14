"""Shared helpers for adapters: ids, sentence grouping, timestamp parsing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from manim_engineer.core import Modality, Segment, SegmentKind, SourceSpan

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")


def doc_id_for(source: str) -> str:
    return hashlib.sha1(source.encode()).hexdigest()[:10]


@dataclass
class Cue:
    start: float
    end: float
    text: str


def group_cues(
    cues: list[Cue],
    doc_id: str,
    modality: Modality,
    target_s: float = 25.0,
    max_words: int = 80,
    kind: SegmentKind = SegmentKind.SPEECH,
) -> list[Segment]:
    """Merge caption-level cues into ~sentence-sized speech segments with time spans."""
    segments: list[Segment] = []
    buf: list[Cue] = []
    words = 0

    def flush() -> None:
        nonlocal buf, words
        if not buf:
            return
        text = " ".join(c.text.strip() for c in buf if c.text.strip())
        text = re.sub(r"\s+", " ", text).replace(">>", "").strip()
        if text:
            segments.append(
                Segment(
                    seg_id=f"s{len(segments):04d}",
                    text=text,
                    kind=kind,
                    span=SourceSpan(
                        modality=modality,
                        doc_id=doc_id,
                        t_start_s=round(buf[0].start, 2),
                        t_end_s=round(buf[-1].end, 2),
                    ),
                )
            )
        buf, words = [], 0

    for c in cues:
        buf.append(c)
        words += len(c.text.split())
        span = buf[-1].end - buf[0].start
        ends_sentence = c.text.rstrip().endswith((".", "?", "!"))
        if (span >= target_s and ends_sentence) or words >= max_words or span >= target_s * 1.6:
            flush()
    flush()
    return segments


def parse_timestamp(s: str) -> float:
    """'01:02:03.456' | '02:03.456' | '02:03,456' | '63.4' → seconds."""
    s = s.strip().replace(",", ".")
    parts = s.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError as e:
        raise ValueError(f"bad timestamp {s!r}") from e
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in SENTENCE_END.split(text) if p.strip()]
