"""Presenter deck as Reveal.js HTML: one slide per beat, its clip autoplaying, narration as notes.

Reveal.js 6.0.2 (MIT, https://revealjs.com) is vendored unmodified under
`assets/revealjs` and copied next to every deck, so a deck presents with no
network. Its LICENSE is part of that copy.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment

from manim_engineer.core import ArtifactBundle

REVEALJS_VERSION = "6.0.2"
ASSETS_DIR = Path(__file__).parent / "assets" / "revealjs"
ASSETS_DIRNAME = "revealjs"


@dataclass
class DeckEntry:
    title: str
    bundle: ArtifactBundle
    bundle_dir: Path
    needs_review: bool = False


# Titles and narration are model-written, so every value is escaped.
_TEMPLATE = Environment(autoescape=True).from_string(
    r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ title }}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="manim-engineer, reveal.js {{ version }}">
<link rel="stylesheet" href="{{ assets }}/reveal.css">
<style>
html,body,.reveal-viewport{background:#0f1115}
/* No Reveal theme is loaded, so set the 42px base its 6.0.2 black theme declares; em sizes would otherwise follow the browser's 16px. */
.reveal{color:#e6e6e6;font-size:42px;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.reveal h1{font-size:1.4em;font-weight:700;margin:0 0 .3em;color:#e6e6e6}
.reveal .sub{font-size:.55em;color:#9aa4b2}
.reveal video{display:block;margin:0 auto;max-width:100%;max-height:640px}
.reveal .cap{font-size:.5em;color:#9aa4b2;margin-top:.4em}
.reveal .review{color:#0f1115;background:#f9e04c;border-radius:4px;padding:.05em .4em;font-weight:600}
</style></head><body>
<div class="reveal"><div class="slides">
<section data-deck="title"><h1>{{ title }}</h1>{% if subtitle %}<p class="sub">{{ subtitle }}</p>{% endif %}</section>
{% for s in slides %}<section data-concept="{{ s.concept_id }}" data-beat="{{ s.beat }}"{% if s.needs_review %} data-needs-review="true"{% endif %}>
<video data-autoplay muted playsinline preload="auto" src="{{ s.mp4 }}"></video>
<p class="cap">{{ s.concept_title }} · {{ s.beat }}{% if s.needs_review %} <span class="review">needs review</span>{% endif %}</p>
{% if s.narration %}<aside class="notes">{{ s.narration }}</aside>{% endif %}
</section>
{% endfor %}</div></div>
<script src="{{ assets }}/reveal.js"></script>
<script src="{{ assets }}/plugin/notes.js"></script>
<script>Reveal.initialize({width:1280,height:800,hash:true,controls:true,progress:true,slideNumber:"c/t",plugins:[RevealNotes]});</script>
</body></html>
"""
)


def _href(target: Path, base: Path) -> str:
    return quote(Path(os.path.relpath(target.resolve(), base.resolve())).as_posix())


def build_revealjs(
    entries: list[DeckEntry],
    out_path: str | Path,
    title: str = "",
    subtitle: str = "",
) -> Path | None:
    """Write the deck in entry order. Returns None, writing nothing, if no clip is playable."""
    out_path = Path(out_path)
    base = out_path.parent
    slides = []
    for entry in entries:
        for sec in entry.bundle.sections:
            mp4 = Path(entry.bundle_dir) / sec.mp4
            if not mp4.is_file():
                continue
            slides.append(
                {
                    "concept_id": entry.bundle.concept_id,
                    "concept_title": entry.title,
                    "beat": sec.name,
                    "mp4": _href(mp4, base),
                    "narration": sec.narration,
                    "needs_review": entry.needs_review,
                }
            )
    if not slides:
        return None
    base.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ASSETS_DIR, base / ASSETS_DIRNAME, dirs_exist_ok=True)
    out_path.write_text(
        _TEMPLATE.render(
            title=title or "manim-engineer deck",
            subtitle=subtitle,
            slides=slides,
            assets=ASSETS_DIRNAME,
            version=REVEALJS_VERSION,
        )
    )
    return out_path
