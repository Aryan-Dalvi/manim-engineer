"""Audio adapter: faster-whisper (GPU if available, CPU int8 otherwise)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from manim_engineer.core import Document, Modality
from manim_engineer.ingest.common import Cue
from manim_engineer.ingest.transcript import document_from_cues

Transcriber = Callable[[Path], list[Cue]]


def whisper_transcriber(model_size: str = "base", device: str | None = None) -> Transcriber:
    def _run(path: Path) -> list[Cue]:
        from faster_whisper import WhisperModel

        attempts = (
            [(device, "float16" if device == "cuda" else "int8")]
            if device
            else [("cuda", "float16"), ("cpu", "int8")]
        )
        last: Exception | None = None
        for dev, ct in attempts:
            try:
                model = WhisperModel(model_size, device=dev, compute_type=ct)
                segs, _info = model.transcribe(str(path), vad_filter=True)
                return [
                    Cue(start=float(s.start), end=float(s.end), text=s.text.strip()) for s in segs
                ]
            except Exception as e:  # try the next device
                last = e
        raise RuntimeError(f"faster-whisper failed: {last}")

    return _run


def load_audio(
    path: str | Path,
    title: str | None = None,
    transcriber: Transcriber | None = None,
    model_size: str = "base",
) -> Document:
    path = Path(path)
    tr = transcriber or whisper_transcriber(model_size)
    cues = tr(path)
    doc = document_from_cues(
        cues,
        source=str(path),
        title=title or path.stem,
        modality=Modality.AUDIO,
        meta={"asr": "faster-whisper" if transcriber is None else "injected"},
    )
    return doc
