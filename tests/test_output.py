import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from manim_engineer.core import ArtifactBundle, SectionArtifact
from manim_engineer.output import (
    REVEALJS_VERSION,
    DeckEntry,
    build_revealjs,
    ffmpeg_available,
    frame_count,
    load_bundle,
    publish,
)

FIX = Path(__file__).parent / "fixtures" / "scenes"


@pytest.mark.integration
def test_publish_good_scene_writes_bundle(tmp_path: Path):
    if not ffmpeg_available():
        pytest.skip("ffmpeg missing")
    bundle = publish(
        FIX / "good_scene.py", "GoodScene", tmp_path / "out", quality="l", gif_width=480, gif_fps=10
    )
    out = tmp_path / "out"
    assert (out / "manifest.json").exists()
    assert (out / bundle.master_mp4).exists()
    assert bundle.duration_s > 5
    names = [s.name for s in bundle.sections]
    assert names == ["b1_intro", "b2_plot", "b3_outro"]
    for s in bundle.sections:
        assert (out / s.mp4).exists()
        assert s.gif and (out / s.gif).exists()
        assert s.png and (out / s.png).exists()
        # 10 fps gif of a >=1s clip has frames
        assert frame_count(out / s.gif) >= 5
    assert bundle.thumbnail and (out / bundle.thumbnail).exists()
    assert bundle.pptx and (out / bundle.pptx).exists()
    reloaded = load_bundle(out)
    assert reloaded == bundle


def _bundle(root: Path, cid: str, beats: list[str], narration: str = ""):
    bdir = root / "animations" / cid
    (bdir / "sections").mkdir(parents=True)
    sections = []
    for i, beat in enumerate(beats, 1):
        rel = f"sections/{i:02d}_{beat}.mp4"
        (bdir / rel).write_bytes(b"mp4")
        sections.append(
            SectionArtifact(index=i, name=beat, duration_s=2.0, mp4=rel, narration=narration)
        )
    bundle = ArtifactBundle(
        plan_id=f"plan_{cid}",
        concept_id=cid,
        scene_class="Scene",
        manim_version="0.19.2",
        quality="480p15",
        width=854,
        height=480,
        fps=15.0,
        duration_s=2.0 * len(beats),
        master_mp4="master.mp4",
        sections=sections,
    )
    return bundle, bdir


def test_revealjs_deck_plays_beats_in_order_with_escaped_notes(tmp_path: Path):
    soft, soft_dir = _bundle(
        tmp_path,
        "softmax",
        ["b1_formula", "b2_sweep"],
        narration="Lower T <script>alert(1)</script> sharpens it.",
    )
    attn, attn_dir = _bundle(tmp_path, "attention", ["b1_scores", "b2_missing"])
    (attn_dir / attn.sections[1].mp4).unlink()  # a clip that failed to publish is skipped
    deck = build_revealjs(
        [
            DeckEntry("Softmax temperature", soft, soft_dir),
            DeckEntry("Attention", attn, attn_dir, needs_review=True),
        ],
        tmp_path / "deck.html",
        title="Talk",
    )
    assert deck is not None
    page = deck.read_text()
    assert re.findall(r'data-beat="([^"]+)"', page) == ["b1_formula", "b2_sweep", "b1_scores"]
    for src in re.findall(r'<video[^>]*\ssrc="([^"]+)"', page):
        assert (deck.parent / unquote(src)).is_file()
    # narration is model-written, so it must never reach the page as live markup
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert page.count('<aside class="notes">') == 2
    assert re.findall(r'data-concept="([^"]+)"[^>]*data-needs-review="true"', page) == ["attention"]
    for asset in ("reveal.js", "reveal.css", "plugin/notes.js", "LICENSE"):
        assert (tmp_path / "revealjs" / asset).is_file()
    assert REVEALJS_VERSION in page


def test_revealjs_deck_is_not_written_without_playable_clips(tmp_path: Path):
    assert build_revealjs([], tmp_path / "deck.html") is None
    assert not (tmp_path / "deck.html").exists()
