from pathlib import Path

import pytest

from manim_engineer.output import ffmpeg_available, frame_count, load_bundle, publish

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
