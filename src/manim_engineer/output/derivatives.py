"""ffmpeg derivatives: GIF (palette, no dither), stills, PowerPoint-safe MP4 (ADR 0006)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

GIF_FILTER = (
    "fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
    "[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
    "[b][p]paletteuse=dither=none:diff_mode=rectangle:new=1"
)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(cmd: list[str], timeout: int = 300) -> bool:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def to_gif(mp4: Path, gif: Path, fps: int = 20, width: int = 960, colors: int = 128) -> bool:
    vf = GIF_FILTER.format(fps=fps, width=width, colors=colors)
    return (
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp4),
                "-filter_complex",
                vf,
                "-loop",
                "0",
                str(gif),
            ]
        )
        and gif.exists()
    )


def last_frame(mp4: Path, png: Path) -> bool:
    return (
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-sseof",
                "-0.15",
                "-i",
                str(mp4),
                "-update",
                "1",
                "-frames:v",
                "1",
                str(png),
            ]
        )
        and png.exists()
    )


def thumbnail(mp4: Path, png: Path, width: int = 1280) -> bool:
    return (
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp4),
                "-vf",
                f"thumbnail=100,scale={width}:-2",
                "-frames:v",
                "1",
                str(png),
            ]
        )
        and png.exists()
    )


def pptx_safe(mp4: Path, out: Path) -> bool:
    return (
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp4),
                "-c:v",
                "libx264",
                "-profile:v",
                "high",
                "-level",
                "4.0",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "20",
                "-preset",
                "medium",
                "-movflags",
                "+faststart",
                "-an",
                str(out),
            ]
        )
        and out.exists()
    )


def frame_count(path: Path) -> int:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_read_frames",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout.strip()
        return int(out) if out.isdigit() else 0
    except Exception:
        return 0
