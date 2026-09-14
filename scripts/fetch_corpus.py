"""Fetch the large corpus inputs that are not committed (PDFs, audio, transcripts).

Usage: .venv/bin/python scripts/fetch_corpus.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "cases"
PDFS = {
    "h1_transformer_slides/cs224n-lecture08-transformers.pdf": "https://web.stanford.edu/class/cs224n/slides/cs224n-spr2024-lecture08-transformers.pdf",
    "h3_specdec_paper/2603.03251.pdf": "https://arxiv.org/pdf/2603.03251",
}
TRANSCRIPTS = {
    "e2_vectors_transcript/transcript.json": "fNk_zzaMoSs",
    "h2_attention_talk/transcript.json": "eMlx5fFNoYc",
    "c2_multimodal_fusion/transcript.json": "eMlx5fFNoYc",
}


def fetch_pdf(rel: str, url: str) -> None:
    dst = ROOT / rel
    if dst.exists():
        print("have", rel)
        return
    print("fetching", url)
    urllib.request.urlretrieve(url, dst)


def fetch_transcript(rel: str, vid: str) -> None:
    dst = ROOT / rel
    if dst.exists():
        print("have", rel)
        return
    from youtube_transcript_api import YouTubeTranscriptApi

    t = YouTubeTranscriptApi().fetch(vid)
    rows = [{"start": round(s.start, 2), "duration": round(s.duration, 2), "text": s.text} for s in t]
    dst.write_text(json.dumps({"video_id": vid, "snippets": rows}, indent=1))
    print("wrote", rel, len(rows), "snippets")


def fetch_audio_clip() -> None:
    dst = ROOT / "e3_vectors_audio/vectors_first90s.mp3"
    if dst.exists():
        print("have e3 audio")
        return
    cmd = [sys.executable, "-m", "yt_dlp", "--js-runtimes", "node", "-q", "-x", "--audio-format", "mp3", "--download-sections", "*0:00-1:30", "--force-keyframes-at-cuts", "-o", str(dst.with_suffix(".%(ext)s")), "https://www.youtube.com/watch?v=fNk_zzaMoSs"]
    subprocess.run(cmd, check=True)
    print("wrote e3 audio")


def fetch_karpathy_window() -> None:
    dst = ROOT / "c1_live_replay/transcript.json"
    if dst.exists():
        print("have c1 transcript")
        return
    from youtube_transcript_api import YouTubeTranscriptApi

    t = YouTubeTranscriptApi().fetch("kCc8FmEb1nY")
    rows = [{"start": round(s.start, 2), "duration": round(s.duration, 2), "text": s.text} for s in t if 2520 <= s.start <= 3720]
    dst.write_text(json.dumps({"video_id": "kCc8FmEb1nY", "snippets": rows}, indent=1))
    print("wrote c1 transcript", len(rows))


if __name__ == "__main__":
    for rel, url in PDFS.items():
        fetch_pdf(rel, url)
    for rel, vid in TRANSCRIPTS.items():
        fetch_transcript(rel, vid)
    fetch_karpathy_window()
    fetch_audio_clip()
