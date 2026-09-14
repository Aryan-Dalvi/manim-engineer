import json
from pathlib import Path

import pytest

from manim_engineer.core import Modality, SegmentKind
from manim_engineer.ingest import (
    Cue,
    detect_kind,
    document_from_markdown,
    ingest,
    load_audio,
    load_document,
    load_pdf_deck,
    load_pdf_paper,
    load_pptx,
    load_transcript,
    load_youtube,
    save_document,
    video_id,
)

MD = """# Softmax temperature

Softmax turns logits into probabilities.

$$
p_i = \\frac{e^{z_i/T}}{\\sum_j e^{z_j/T}}
$$

Lower temperature sharpens the distribution. Higher temperature flattens it.

## Code

```python
import numpy as np
```

Final paragraph.
"""


def test_markdown_segments_headings_equations_code():
    doc = document_from_markdown(MD, source="x.md", title="t")
    kinds = [s.kind for s in doc.segments]
    assert kinds == [
        SegmentKind.HEADING,
        SegmentKind.BODY,
        SegmentKind.EQUATION,
        SegmentKind.BODY,
        SegmentKind.HEADING,
        SegmentKind.CODE,
        SegmentKind.BODY,
    ]
    eq = doc.equations()[0]
    assert eq.latex.startswith("p_i =")
    assert eq.span.para_id == "sec1.eq1"
    assert doc.segments[3].span.para_id == "sec1.p2"


def test_transcript_json_groups_cues_with_spans(tmp_path: Path):
    rows = [{"start": i * 4.0, "duration": 4.0, "text": f"Sentence number {i}."} for i in range(20)]
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"snippets": rows}))
    doc = load_transcript(p)
    assert doc.modality == Modality.TRANSCRIPT
    assert 2 <= len(doc.segments) <= 5
    first = doc.segments[0]
    assert first.span.t_start_s == 0.0 and first.span.t_end_s >= 24.0
    assert "Sentence number 0." in first.text
    save_document(doc, tmp_path / "doc.json")
    assert load_document(tmp_path / "doc.json") == doc


def test_transcript_vtt_and_plain(tmp_path: Path):
    vtt = "WEBVTT\n\n00:00.000 --> 00:03.000\nHello <b>there</b>.\n\n00:03.000 --> 00:06.000\nSecond cue.\n"
    p = tmp_path / "a.vtt"
    p.write_text(vtt)
    doc = load_transcript(p)
    assert "Hello there." in doc.segments[0].text and "<b>" not in doc.segments[0].text
    plain = tmp_path / "b.txt"
    plain.write_text("[00:10] First line here.\n[01:05] Second line here.\n")
    doc2 = load_transcript(plain)
    assert doc2.segments[0].span.t_start_s == 10.0
    assert detect_kind(str(plain)) == "transcript"


def test_pptx_slides_and_notes(tmp_path: Path):
    from pptx import Presentation

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Attention"
    s.placeholders[1].text = "Q K V"
    s.notes_slide.notes_text_frame.text = "Explain scaled dot product here."
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Second"
    p = tmp_path / "deck.pptx"
    prs.save(str(p))
    doc = load_pptx(p)
    assert doc.modality == Modality.SLIDES
    assert doc.segments[0].span.slide_index == 1 and doc.segments[0].kind == SegmentKind.SLIDE_TEXT
    assert any(s.kind == SegmentKind.SLIDE_NOTES and "scaled dot" in s.text for s in doc.segments)
    assert doc.segments[-1].span.slide_index == 2


def test_pdf_deck_and_paper(tmp_path: Path):
    import pymupdf

    deck = pymupdf.open()
    for i in range(3):
        page = deck.new_page(width=960, height=540)
        page.insert_text((72, 100), f"Slide {i + 1} title", fontsize=28)
        page.insert_text(
            (72, 160), "Some bullet text about attention heads and layers.", fontsize=14
        )
    dp = tmp_path / "deck.pdf"
    deck.save(str(dp))
    doc = ingest(str(dp), workdir=tmp_path / "wd")
    assert doc.modality == Modality.SLIDES
    assert [s.span.slide_index for s in doc.segments] == [1, 2, 3]
    assert doc.assets and Path(next(iter(doc.assets.values()))).exists()
    paper = pymupdf.open()
    for i in range(2):
        page = paper.new_page(width=612, height=792)
        y = 80
        for k in range(12):
            page.insert_text(
                (72, y),
                f"Paragraph {k} on page {i + 1}: " + "lorem ipsum dolor sit amet " * 4,
                fontsize=10,
            )
            y += 50
    pp = tmp_path / "paper.pdf"
    paper.save(str(pp))
    doc2 = ingest(str(pp))
    assert doc2.modality == Modality.MANUSCRIPT
    assert doc2.segments[0].span.para_id.startswith("p1.")
    assert len(doc2.segments) >= 12
    doc3 = load_pdf_paper(pp, max_pages=1)
    assert all(s.span.para_id.startswith("p1.") for s in doc3.segments)
    doc4 = load_pdf_deck(dp, max_pages=2)
    assert len(doc4.segments) == 2


def test_audio_with_injected_transcriber(tmp_path: Path):
    wav = tmp_path / "talk.wav"
    wav.write_bytes(b"RIFF")
    doc = load_audio(
        wav,
        transcriber=lambda p: [
            Cue(0, 3, "Vectors are arrows."),
            Cue(3, 6, "They add tip to tail."),
        ],
    )
    assert doc.modality == Modality.AUDIO
    assert doc.segments[0].span.t_end_s == 6.0
    assert "tip to tail" in doc.segments[0].text


def test_youtube_captions_then_audio_fallback(tmp_path: Path):
    assert video_id("https://www.youtube.com/watch?v=fNk_zzaMoSs&t=1") == "fNk_zzaMoSs"
    assert video_id("https://youtu.be/fNk_zzaMoSs") == "fNk_zzaMoSs"
    with pytest.raises(ValueError):
        video_id("https://example.com")
    doc = load_youtube("https://youtu.be/fNk_zzaMoSs", captions=lambda v: [Cue(0, 2, "hi there.")])
    assert doc.modality == Modality.VIDEO and doc.meta["path"] == "captions"

    def boom(v):
        raise RuntimeError("blocked")

    def fake_audio(v, wd: Path):
        f = wd / f"{v}.mp3"
        f.write_bytes(b"ID3")
        return f

    doc2 = load_youtube(
        "fNk_zzaMoSs",
        captions=boom,
        audio=fake_audio,
        transcriber=lambda p: [Cue(0, 2, "fallback works.")],
        workdir=tmp_path,
    )
    assert doc2.meta["path"] == "audio+asr" and "blocked" in doc2.meta["captions_error"]
    assert doc2.segments[0].text == "fallback works."
