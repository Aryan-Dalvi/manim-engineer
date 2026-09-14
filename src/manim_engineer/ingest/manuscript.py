"""Manuscript adapters: Markdown/LaTeX-ish text with equations, and PDF papers via PyMuPDF."""

from __future__ import annotations

import re
from pathlib import Path

from manim_engineer.core import Document, Modality, Segment, SegmentKind, SourceSpan
from manim_engineer.ingest.common import doc_id_for

_DISPLAY_MATH = re.compile(
    r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\begin\{(equation\*?|align\*?)\}(.+?)\\end\{\3\}", re.S
)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^```")


def load_markdown(path: str | Path, title: str | None = None) -> Document:
    path = Path(path)
    text = path.read_text(errors="ignore")
    return document_from_markdown(
        text, source=str(path), title=title or _first_heading(text) or path.stem
    )


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            return m.group(2).strip()
    return None


def document_from_markdown(text: str, source: str, title: str) -> Document:
    doc_id = doc_id_for(source)
    segments: list[Segment] = []
    section = 0
    para = 0
    eq_n = 0
    cursor = 0

    def add(
        kind: SegmentKind, body: str, latex: str | None = None, start: int = 0, end: int = 0
    ) -> None:
        nonlocal para, eq_n
        body = body.strip()
        if not body:
            return
        if kind == SegmentKind.EQUATION:
            eq_n += 1
            pid = f"sec{section}.eq{eq_n}"
        elif kind == SegmentKind.HEADING:
            pid = f"sec{section}.h"
        else:
            para += 1
            pid = f"sec{section}.p{para}"
        segments.append(
            Segment(
                seg_id=f"s{len(segments):04d}",
                text=body,
                kind=kind,
                latex=latex,
                span=SourceSpan(
                    modality=Modality.MANUSCRIPT,
                    doc_id=doc_id,
                    para_id=pid,
                    char_start=start,
                    char_end=end,
                ),
            )
        )

    # Pull display equations out first, replacing them with markers so paragraphs split cleanly.
    equations: dict[str, tuple[str, int, int]] = {}

    def _sub(m: re.Match) -> str:
        latex = next(g for g in (m.group(1), m.group(2), m.group(4)) if g)
        key = f"\x00EQ{len(equations)}\x00"
        equations[key] = (latex.strip(), m.start(), m.end())
        return f"\n\n{key}\n\n"

    body = _DISPLAY_MATH.sub(_sub, text)
    blocks = re.split(r"\n\s*\n", body)
    in_fence = False
    fence_buf: list[str] = []
    for block in blocks:
        block_stripped = block.strip()
        if not block_stripped:
            continue
        if _FENCE.match(block_stripped) or in_fence:
            fence_buf.append(block_stripped)
            opens = block_stripped.count("```")
            if (not in_fence and opens == 1) or (in_fence and opens >= 1):
                in_fence = not in_fence if opens % 2 else in_fence
            if not in_fence:
                add(
                    SegmentKind.CODE,
                    "\n".join(fence_buf).strip("`\n"),
                    start=cursor,
                    end=cursor + len(block),
                )
                fence_buf = []
            cursor += len(block) + 2
            continue
        if block_stripped in equations:
            latex, s, e = equations[block_stripped]
            add(SegmentKind.EQUATION, latex, latex=latex, start=s, end=e)
            continue
        m = _HEADING.match(block_stripped.splitlines()[0])
        if m:
            section += 1
            para = 0
            add(SegmentKind.HEADING, m.group(2), start=cursor, end=cursor + len(block))
            rest = "\n".join(block_stripped.splitlines()[1:]).strip()
            if rest:
                add(SegmentKind.BODY, rest, start=cursor, end=cursor + len(block))
        else:
            add(
                SegmentKind.BODY,
                re.sub(r"\s+", " ", block_stripped),
                start=cursor,
                end=cursor + len(block),
            )
        cursor += len(block) + 2
    return Document(
        doc_id=doc_id, title=title, modality=Modality.MANUSCRIPT, source=source, segments=segments
    )


def load_pdf_paper(
    path: str | Path, title: str | None = None, max_pages: int | None = None
) -> Document:
    import pymupdf

    path = Path(path)
    doc_id = doc_id_for(str(path))
    pdf = pymupdf.open(str(path))
    segments: list[Segment] = []
    meta_title = (pdf.metadata or {}).get("title") or ""
    for pno, page in enumerate(pdf, start=1):
        if max_pages and pno > max_pages:
            break
        blocks = page.get_text("blocks")
        n = 0
        for b in blocks:
            txt = re.sub(r"\s+", " ", (b[4] or "")).strip()
            if len(txt) < 25:
                continue
            n += 1
            kind = (
                SegmentKind.HEADING
                if len(txt) < 80 and txt[0].isupper() and not txt.endswith(".")
                else SegmentKind.BODY
            )
            segments.append(
                Segment(
                    seg_id=f"s{len(segments):04d}",
                    text=txt,
                    kind=kind,
                    span=SourceSpan(
                        modality=Modality.MANUSCRIPT, doc_id=doc_id, para_id=f"p{pno}.{n}"
                    ),
                )
            )
    return Document(
        doc_id=doc_id,
        title=title or meta_title or path.stem,
        modality=Modality.MANUSCRIPT,
        source=str(path),
        segments=segments,
        meta={"pages": pdf.page_count},
    )
