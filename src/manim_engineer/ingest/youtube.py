"""YouTube adapter: captions first, audio download + local ASR as fallback."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from manim_engineer.core import Document, Modality
from manim_engineer.ingest.audio import Transcriber, load_audio
from manim_engineer.ingest.common import Cue
from manim_engineer.ingest.transcript import document_from_cues

_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")

CaptionFetcher = Callable[[str], list[Cue]]
AudioFetcher = Callable[[str, Path], Path]


def video_id(url: str) -> str:
    m = _ID_RE.search(url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    raise ValueError(f"not a YouTube URL or id: {url}")


def is_youtube(source: str) -> bool:
    return "youtube.com" in source or "youtu.be" in source


def fetch_captions(vid: str) -> list[Cue]:
    from youtube_transcript_api import YouTubeTranscriptApi

    t = YouTubeTranscriptApi().fetch(vid)
    return [
        Cue(
            start=float(s.start),
            end=float(s.start) + float(s.duration),
            text=s.text.replace("\n", " "),
        )
        for s in t
    ]


def fetch_audio(vid: str, workdir: Path) -> Path:
    import subprocess
    import sys

    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / f"{vid}.%(ext)s"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--js-runtimes",
        "node",
        "-q",
        "-x",
        "--audio-format",
        "mp3",
        "-o",
        str(out),
        f"https://www.youtube.com/watch?v={vid}",
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=900)
    mp3 = workdir / f"{vid}.mp3"
    if not mp3.exists():
        raise RuntimeError("yt-dlp did not produce an mp3")
    return mp3


def fetch_title(vid: str) -> str:
    try:
        import subprocess
        import sys

        out = (
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "yt_dlp",
                    "--js-runtimes",
                    "node",
                    "--skip-download",
                    "--print",
                    "%(title)s",
                    f"https://www.youtube.com/watch?v={vid}",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            .stdout.strip()
            .splitlines()
        )
        return out[-1] if out else vid
    except Exception:
        return vid


def load_youtube(
    url: str,
    title: str | None = None,
    captions: CaptionFetcher | None = None,
    audio: AudioFetcher | None = None,
    transcriber: Transcriber | None = None,
    workdir: Path | None = None,
    prefer_audio: bool = False,
) -> Document:
    vid = video_id(url)
    src = f"https://www.youtube.com/watch?v={vid}"
    cues: list[Cue] = []
    err: str | None = None
    if not prefer_audio:
        try:
            cues = (captions or fetch_captions)(vid)
        except Exception as e:  # rate limit / blocked / no captions
            err = f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
    if cues:
        t = title or (fetch_title(vid) if captions is None else vid)
        return document_from_cues(
            cues,
            source=src,
            title=t,
            modality=Modality.VIDEO,
            meta={"video_id": vid, "path": "captions"},
        )
    wd = workdir or Path(tempfile.mkdtemp(prefix="me-yt-"))
    mp3 = (audio or fetch_audio)(vid, wd)
    doc = load_audio(mp3, title=title or vid, transcriber=transcriber)
    doc.source = src
    doc.modality = Modality.VIDEO
    doc.meta.update({"video_id": vid, "path": "audio+asr", "captions_error": err})
    return doc
