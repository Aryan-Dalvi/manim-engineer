"""output bounded context: render once, derive everything, write the manifest (ADR 0006)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from manim_engineer.core import AnimationPlan, ArtifactBundle, SectionArtifact
from manim_engineer.output.deck import build_pptx
from manim_engineer.output.derivatives import (
    ffmpeg_available,
    frame_count,
    last_frame,
    pptx_safe,
    thumbnail,
    to_gif,
)
from manim_engineer.output.render import QUALITY_FOLDER, RenderError, RenderResult, render
from manim_engineer.output.revealjs import REVEALJS_VERSION, DeckEntry, build_revealjs


def publish(
    code_path: str | Path,
    scene_class: str,
    out_dir: str | Path,
    plan: AnimationPlan | None = None,
    quality: str = "m",
    gif_width: int = 960,
    gif_fps: int = 20,
    full_gif: bool = True,
    deck: bool = True,
    media_dir: str | Path | None = None,
) -> ArtifactBundle:
    """Render `scene_class` and write a slide-ready bundle under out_dir.

    Layout: master.mp4, master.pptx.mp4, full.gif, stills/{thumb,last}.png,
    sections/<idx>_<beat>.{mp4,gif,png}, deck.pptx, manifest.json.
    """
    import manim

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    media = Path(media_dir) if media_dir else out_dir / "media"
    rr: RenderResult = render(code_path, scene_class, media, quality=quality)
    warnings: list[str] = []
    master = out_dir / "master.mp4"
    shutil.copyfile(rr.master_mp4, master)
    bundle = ArtifactBundle(
        plan_id=plan.plan_id if plan else scene_class,
        concept_id=plan.concept.concept_id if plan else scene_class,
        scene_class=scene_class,
        manim_version=manim.__version__,
        quality=QUALITY_FOLDER.get(quality, quality),
        width=rr.width,
        height=rr.height,
        fps=rr.fps,
        duration_s=rr.duration_s,
        master_mp4="master.mp4",
    )
    if not ffmpeg_available():
        warnings.append("ffmpeg not found: no GIF/PNG derivatives")
    else:
        stills = out_dir / "stills"
        stills.mkdir(exist_ok=True)
        if thumbnail(master, stills / "thumb.png"):
            bundle.thumbnail = "stills/thumb.png"
        if last_frame(master, stills / "last.png"):
            bundle.last_frame = "stills/last.png"
        if pptx_safe(master, out_dir / "master.pptx.mp4"):
            bundle.pptx_mp4 = "master.pptx.mp4"
        if full_gif and to_gif(
            master, out_dir / "full.gif", fps=min(gif_fps, 15), width=min(gif_width, 720)
        ):
            bundle.full_gif = "full.gif"
    narr = {b.beat_id: b.narration for b in plan.beats} if plan else {}
    sec_dir = out_dir / "sections"
    sec_dir.mkdir(exist_ok=True)
    base = rr.sections_json.parent if rr.sections_json else None
    idx = 0
    for s in rr.sections:
        if not s.get("video") or base is None:
            continue
        name = s.get("name") or f"section{idx}"
        if name in ("autocreated", "default") and float(s.get("duration", 0) or 0) < 0.05:
            continue
        idx += 1
        stem = f"{idx:02d}_{name}"
        mp4 = sec_dir / f"{stem}.mp4"
        shutil.copyfile(base / s["video"], mp4)
        art = SectionArtifact(
            index=idx,
            name=name,
            duration_s=float(s.get("duration", 0) or 0),
            mp4=f"sections/{stem}.mp4",
            narration=narr.get(name, ""),
        )
        if ffmpeg_available():
            if to_gif(mp4, sec_dir / f"{stem}.gif", fps=gif_fps, width=gif_width):
                art.gif = f"sections/{stem}.gif"
            if last_frame(mp4, sec_dir / f"{stem}.png"):
                art.png = f"sections/{stem}.png"
        bundle.sections.append(art)
    if deck and bundle.sections:
        try:
            if build_pptx(
                bundle, out_dir, out_dir / "deck.pptx", title=plan.concept.title if plan else ""
            ):
                bundle.pptx = "deck.pptx"
        except Exception as e:  # deck is optional by design
            warnings.append(f"deck export failed: {e}")
    bundle.warnings = warnings
    (out_dir / "manifest.json").write_text(json.dumps(bundle.model_dump(), indent=1))
    (out_dir / "render.log").write_text(rr.log)
    return bundle


def load_bundle(out_dir: str | Path) -> ArtifactBundle:
    return ArtifactBundle.model_validate_json((Path(out_dir) / "manifest.json").read_text())


__all__ = [
    "REVEALJS_VERSION",
    "DeckEntry",
    "RenderError",
    "RenderResult",
    "build_pptx",
    "build_revealjs",
    "ffmpeg_available",
    "frame_count",
    "load_bundle",
    "publish",
    "render",
]
