"""Transcript adapters: JSON snippets, WebVTT, SRT, plain text with optional [mm:ss] marks."""

from __future__ import annotations

import json
import re
from pathlib import Path

from manim_engineer.core import Document, Modality, Segment, SegmentKind, SourceSpan
from manim_engineer.ingest.common import Cue, doc_id_for, group_cues, parse_timestamp

_TS_PREFIX = re.compile(r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)\]?\s*[-–:]?\s*")


def cues_from_json(data) -> list[Cue]:
    if isinstance(data, dict):
        data = data.get("snippets") or data.get("segments") or data.get("cues") or []
    cues: list[Cue] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        start = float(row.get("start", row.get("t_start_s", 0.0)) or 0.0)
        if "end" in row:
            end = float(row["end"])
        elif "duration" in row:
            end = start + float(row["duration"])
        else:
            end = start + max(1.0, len(text.split()) / 2.5)
        cues.append(Cue(start=start, end=end, text=text))
    return cues


def cues_from_vtt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    block: list[str] = []
    for line in text.splitlines() + [""]:
        if line.strip():
            block.append(line)
            continue
        if block:
            cue = _vtt_block(block)
            if cue:
                cues.append(cue)
            block = []
    return cues


def _vtt_block(block: list[str]) -> Cue | None:
    for i, line in enumerate(block):
        if "-->" in line:
            a, b = line.split("-->")[:2]
            b = b.strip().split(" ")[0]
            body = " ".join(block[i + 1 :]).strip()
            body = re.sub(r"<[^>]+>", "", body)
            if not body:
                return None
            return Cue(start=parse_timestamp(a), end=parse_timestamp(b), text=body)
    return None


def cues_from_plain(text: str) -> list[Cue]:
    cues: list[Cue] = []
    t = 0.0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _TS_PREFIX.match(line)
        if m:
            t = parse_timestamp(m.group(1))
            line = line[m.end() :].strip()
        if not line:
            continue
        dur = max(1.0, len(line.split()) / 2.5)
        cues.append(Cue(start=t, end=t + dur, text=line))
        t += dur
    return cues


def load_transcript(path: str | Path, title: str | None = None) -> Document:
    path = Path(path)
    raw = path.read_text(errors="ignore")
    suffix = path.suffix.lower()
    if suffix == ".json":
        cues = cues_from_json(json.loads(raw))
    elif suffix in (".vtt", ".srt"):
        cues = cues_from_vtt(raw)
    else:
        cues = cues_from_plain(raw)
    return document_from_cues(cues, source=str(path), title=title or path.stem)


def document_from_cues(
    cues: list[Cue],
    source: str,
    title: str,
    modality: Modality = Modality.TRANSCRIPT,
    meta: dict | None = None,
) -> Document:
    doc_id = doc_id_for(source)
    segs = group_cues(cues, doc_id, modality)
    dedup = _dedupe_overlap(segs)
    return Document(
        doc_id=doc_id,
        title=title,
        modality=modality,
        source=source,
        segments=dedup,
        meta=meta or {},
    )


def _dedupe_overlap(segs: list[Segment]) -> list[Segment]:
    """YouTube auto-captions repeat trailing words across cues; collapse exact repeats."""
    out: list[Segment] = []
    for s in segs:
        if out and s.text == out[-1].text:
            continue
        out.append(s)
    return out


def segment_from_text(text: str, doc_id: str, idx: int, t0: float, t1: float) -> Segment:
    return Segment(
        seg_id=f"s{idx:04d}",
        text=text,
        kind=SegmentKind.SPEECH,
        span=SourceSpan(modality=Modality.TRANSCRIPT, doc_id=doc_id, t_start_s=t0, t_end_s=t1),
    )
