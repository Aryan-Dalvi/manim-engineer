"""ingest bounded context: every input modality becomes a Document of Segments."""

from __future__ import annotations

import json
from pathlib import Path

from manim_engineer.core import Document
from manim_engineer.ingest.audio import load_audio, whisper_transcriber
from manim_engineer.ingest.common import Cue, doc_id_for, group_cues
from manim_engineer.ingest.manuscript import document_from_markdown, load_markdown, load_pdf_paper
from manim_engineer.ingest.slides import load_pdf_deck, load_pptx, pdf_is_deck
from manim_engineer.ingest.transcript import document_from_cues, load_transcript
from manim_engineer.ingest.youtube import is_youtube, load_youtube, video_id

KINDS = ("transcript", "markdown", "pdf", "pdf-deck", "pdf-paper", "pptx", "audio", "youtube")
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4", ".mkv", ".webm"}
TRANSCRIPT_SUFFIXES = {".json", ".vtt", ".srt"}


def detect_kind(source: str) -> str:
    if is_youtube(source):
        return "youtube"
    suffix = Path(source).suffix.lower()
    if suffix in TRANSCRIPT_SUFFIXES:
        return "transcript"
    if suffix in (".md", ".markdown", ".txt", ".tex"):
        return "markdown" if suffix != ".txt" else "transcript"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".pptx":
        return "pptx"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    raise ValueError(f"cannot detect input kind for {source!r}; pass kind explicitly")


def ingest(
    source: str,
    kind: str | None = None,
    workdir: str | Path | None = None,
    title: str | None = None,
    **opts,
) -> Document:
    """Normalize any supported input into a Document. `workdir` receives assets and downloads."""
    kind = kind or detect_kind(source)
    wd = Path(workdir) if workdir else None
    if kind == "youtube":
        return load_youtube(source, title=title, workdir=wd, **opts)
    if kind == "transcript":
        return load_transcript(source, title=title)
    if kind == "markdown":
        return load_markdown(source, title=title)
    if kind == "pptx":
        return load_pptx(source, title=title)
    if kind == "audio":
        return load_audio(source, title=title, **opts)
    if kind == "pdf":
        kind = "pdf-deck" if pdf_is_deck(source) else "pdf-paper"
    if kind == "pdf-deck":
        return load_pdf_deck(
            source, title=title, assets_dir=(wd / "assets") if wd else None, **opts
        )
    if kind == "pdf-paper":
        return load_pdf_paper(source, title=title, **opts)
    raise ValueError(f"unknown kind {kind!r}; choose from {KINDS}")


def save_document(doc: Document, path: str | Path) -> None:
    Path(path).write_text(json.dumps(doc.model_dump(), indent=1))


def load_document(path: str | Path) -> Document:
    return Document.model_validate_json(Path(path).read_text())


__all__ = [
    "KINDS",
    "Cue",
    "detect_kind",
    "doc_id_for",
    "document_from_cues",
    "document_from_markdown",
    "group_cues",
    "ingest",
    "load_audio",
    "load_document",
    "load_markdown",
    "load_pdf_deck",
    "load_pdf_paper",
    "load_pptx",
    "load_transcript",
    "load_youtube",
    "pdf_is_deck",
    "save_document",
    "video_id",
    "whisper_transcriber",
]
