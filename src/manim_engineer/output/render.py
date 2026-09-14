"""Render a candidate scene with Manim in a subprocess and locate its outputs."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

QUALITY_FOLDER = {"l": "480p15", "m": "720p30", "h": "1080p60", "p": "1440p60", "k": "2160p60"}
QUALITY_DIMS = {"l": (854, 480, 15), "m": (1280, 720, 30), "h": (1920, 1080, 60)}


class RenderError(RuntimeError):
    pass


@dataclass
class RenderResult:
    master_mp4: Path
    sections_json: Path | None
    sections: list[dict] = field(default_factory=list)
    quality: str = "l"
    width: int = 854
    height: int = 480
    fps: float = 15
    duration_s: float = 0.0
    log: str = ""

    def section_mp4s(self) -> list[Path]:
        base = self.sections_json.parent if self.sections_json else None
        return [base / s["video"] for s in self.sections if base and s.get("video")]


def render(
    code_path: str | Path,
    scene_class: str,
    media_dir: str | Path,
    quality: str = "l",
    save_sections: bool = True,
    timeout_s: int = 900,
    python: str | None = None,
) -> RenderResult:
    code_path = Path(code_path).resolve()
    media_dir = Path(media_dir).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        python or sys.executable,
        "-m",
        "manim",
        "render",
        f"-q{quality}",
        "--disable_caching",
        "--progress_bar",
        "none",
        "--media_dir",
        str(media_dir),
    ]
    if save_sections:
        cmd.append("--save_sections")
    cmd += [str(code_path), scene_class]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, cwd=code_path.parent
        )
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"render timed out after {timeout_s}s") from e
    log = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RenderError(f"manim exited {proc.returncode}:\n{log[-3000:]}")
    folder = media_dir / "videos" / code_path.stem / QUALITY_FOLDER.get(quality, "480p15")
    master = folder / f"{scene_class}.mp4"
    if not master.exists():
        raise RenderError(f"expected output missing: {master}\n{log[-2000:]}")
    sections_json = folder / "sections" / f"{scene_class}.json"
    sections: list[dict] = []
    if sections_json.exists():
        sections = json.loads(sections_json.read_text())
    w, h, fps = QUALITY_DIMS.get(quality, (854, 480, 15))
    return RenderResult(
        master_mp4=master,
        sections_json=sections_json if sections_json.exists() else None,
        sections=sections,
        quality=quality,
        width=w,
        height=h,
        fps=fps,
        duration_s=probe_duration(master),
        log=log[-4000:],
    )


def probe_duration(path: Path) -> float:
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
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0
