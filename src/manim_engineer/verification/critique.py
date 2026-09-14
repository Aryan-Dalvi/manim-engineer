"""Tier 2: low-res render frames → contact sheet → VLM rubric (advisory, ADR 0004)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from manim_engineer.core import AnimationPlan, Finding, Severity, TierReport
from manim_engineer.llm import LLMBackend, LLMError, LLMRequest

RUBRIC = {
    "visual_relevance": "Do the visuals actually depict the claim and each beat's purpose?",
    "element_layout": "Are elements well placed, non-overlapping, readable, and using the frame well?",
    "logical_flow": "Do the beats build on each other in a sensible teaching order?",
    "clarity": "Would a first-time viewer understand each frame within about three seconds?",
    "plan_adherence": "Does each section match its planned beat (appears/transforms/narration)?",
}

CRITIQUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {k: {"type": "integer", "minimum": 1, "maximum": 5} for k in RUBRIC},
            "required": list(RUBRIC),
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "beat_id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warn", "fatal"]},
                    "message": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "message", "fix"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["scores", "issues", "summary"],
}


def _nonblack_ratio(jpg: Path) -> float:
    try:
        from PIL import Image

        im = Image.open(jpg).convert("L").resize((160, 90))
        px = list(im.getdata())
        return sum(1 for v in px if v > 12) / max(len(px), 1)
    except Exception:
        return 1.0


def extract_section_frames(section_mp4s: list[Path], out_dir: Path) -> list[Path]:
    """One representative frame per section: the most informative of three candidates.

    Sections typically end in a FadeOut, so the literal last frame is often black
    (the makefinks/manim-generator "highest density" trick, applied per beat).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for mp4 in section_mp4s:
        best: tuple[float, Path] | None = None
        for k, frac in enumerate((0.55, 0.8, 0.95)):
            cand = out_dir / f"{mp4.stem}_{k}.jpg"
            cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp4),
                "-vf",
                f"select='gte(t\\,{frac}*{_duration(mp4):.3f})'",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(cand),
            ]
            subprocess.run(cmd, check=False, capture_output=True)
            if not cand.exists():
                continue
            score = _nonblack_ratio(cand)
            if best is None or score > best[0] + 0.02:
                best = (score, cand)
        if best is not None:
            final = out_dir / f"{mp4.stem}.jpg"
            shutil.copyfile(best[1], final)
            frames.append(final)
    return frames


def _duration(mp4: Path) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(mp4),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        return max(float(out), 0.1) if out else 1.0
    except Exception:
        return 1.0


def contact_sheet(master_mp4: Path, out_path: Path, cols: int = 3, rows: int = 3) -> Path | None:
    """fps=1 tiles with a faint grid overlay, for spatial grounding."""
    if shutil.which("ffmpeg") is None:
        return None
    vf = f"fps=1,scale=427:240,tile={cols}x{rows}:margin=6:padding=4,drawgrid=w=iw/{cols}:h=ih/{rows}:t=1:c=red@0.4"
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(master_mp4),
        "-vf",
        vf,
        "-frames:v",
        "1",
        "-q:v",
        "4",
        str(out_path),
    ]
    subprocess.run(cmd, check=False, capture_output=True)
    return out_path if out_path.exists() else None


def build_prompt(plan: AnimationPlan, frame_paths: list[Path], box_summary: str) -> str:
    beats = "\n".join(f"- {b.beat_id}: {b.purpose}. Narration: {b.narration}" for b in plan.beats)
    files = "\n".join(f"- {p.name} (section {p.stem})" for p in frame_paths)
    rubric = "\n".join(f"- {k}: {v}" for k, v in RUBRIC.items())
    return f"""You are reviewing an educational animation rendered from a plan.

Concept: {plan.concept.title}
Claim the animation must convey: {plan.concept.claim}

Planned beats (section name = beat id):
{beats}

The attached images are the final frame of each section, in order:
{files}

Deterministic geometry checks already ran; their bounding-box summary (world units, frame is 14.2 x 8):
{box_summary or "(no boxes recorded)"}

Score each rubric item from 1 (bad) to 5 (excellent):
{rubric}

List concrete issues. For each issue name the beat_id, a severity (fatal only if the animation would mislead or is unreadable), a message, and an admissible fix in terms of Manim/kit operations (e.g. "FadeOut the title before beat b3", "move the label with next_to(box, DOWN)"). Do not report overlaps that the geometry summary already lists. Be concise."""


def critique(
    backend: LLMBackend,
    plan: AnimationPlan,
    frame_paths: list[Path],
    box_summary: str = "",
    tag: str = "critique",
) -> TierReport:
    if not frame_paths:
        return TierReport(tier=2, ok=True, notes="no frames to critique")
    req = LLMRequest(
        prompt=build_prompt(plan, frame_paths, box_summary),
        tier="vision",
        json_schema=CRITIQUE_SCHEMA,
        images=[str(p) for p in frame_paths],
        tag=tag,
        max_tokens=3000,
    )
    try:
        resp = backend.complete(req)
        data = resp.require_structured()
    except LLMError as e:
        return TierReport(tier=2, ok=True, notes=f"critique unavailable: {e}")
    scores = {k: float(v) / 5.0 for k, v in (data.get("scores") or {}).items()}
    findings = []
    for it in data.get("issues") or []:
        sev = it.get("severity", "warn")
        findings.append(
            Finding(
                gate="critique",
                severity=Severity(sev) if sev in ("info", "warn", "fatal") else Severity.WARN,
                beat_id=it.get("beat_id") or None,
                message=it.get("message", ""),
                fix=it.get("fix", ""),
            )
        )
    mean = sum(scores.values()) / len(scores) if scores else 0.0
    ok = mean >= 0.6 and not any(f.severity == Severity.FATAL for f in findings)
    return TierReport(
        tier=2, ok=ok, findings=findings, scores=scores, notes=data.get("summary", "")
    )


def summarize_boxes(frames_json: list[dict[str, Any]], limit: int = 40) -> str:
    lines = []
    for f in frames_json:
        for b in f.get("boxes", [])[:12]:
            if b.get("textual"):
                lines.append(
                    f"[{f['section']} t={f['t']}] {b['kind']} {b.get('text', '')!r} at ({b['x0']:.1f},{b['y0']:.1f})-({b['x1']:.1f},{b['y1']:.1f})"
                )
        if len(lines) > limit:
            break
    return "\n".join(lines[:limit])


def dumps(report: TierReport) -> str:
    return json.dumps(report.model_dump(), indent=1)
