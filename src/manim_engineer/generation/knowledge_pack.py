"""Assemble the system-prompt knowledge for a given archetype from the vendored pack."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from manim_engineer.core import Archetype

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

CORE_FILES = ["kit-reference.md", "manimce-0.19-pitfalls.md"]
CORE_RULE_SECTIONS: dict[str, list[str]] = {
    # file -> section headings (## ...) to keep; empty list = whole file
    "rules/production-quality.md": [
        "1. Text Overlap Prevention",
        "3. Container Boundary Enforcement",
        "4. Data Visualization Minimums",
        "5. Persistent Element Lifecycle",
        "8. Dimming vs FadeOut on Dark Backgrounds",
        "9. Text Width Enforcement",
        "10. Only Animate What Visualizes Well",
        "17. Known Failure Patterns (from production audits)",
    ],
    "rules/animation-design-thinking.md": [
        "Pacing: the most common mistake is going too fast",
        "Equation decomposition strategy",
    ],
    "rules/visual-design-principles.md": [],
}
ARCHETYPE_FILES: dict[Archetype, list[str]] = {
    Archetype.EQUATION_DERIVATION: ["rules/equations.md", "rules/equation-derivations.md"],
    Archetype.FUNCTION_PLOT: ["rules/graphs-plots.md", "rules/updaters-trackers.md"],
    Archetype.GEOMETRIC: ["rules/mobjects.md", "rules/decorations.md", "rules/animations.md"],
    Archetype.FLOW_DIAGRAM: ["rules/decorations.md"],
    Archetype.TENSOR_FLOW: ["rules/decorations.md", "rules/animations.md"],
    Archetype.TIMELINE: ["rules/animations.md"],
    Archetype.COMPARISON_TABLE: [],
    Archetype.ALGORITHM_TRACE: ["rules/animations.md", "rules/decorations.md"],
    Archetype.GRAPH_NETWORK: ["rules/animations.md"],
    Archetype.MATRIX_TRANSFORM: ["rules/matrices-linalg.md", "rules/equations.md"],
    Archetype.DISTRIBUTION: ["rules/graphs-plots.md", "rules/updaters-trackers.md"],
    Archetype.NUMBER_LINE: ["rules/graphs-plots.md", "rules/updaters-trackers.md"],
    Archetype.SETS: ["rules/mobjects.md"],
    Archetype.SURFACE_3D: ["rules/graphs-plots.md"],
}
DOMAIN_FILES = {
    "ml": "domains/machine-learning.md",
    "math": "domains/mathematics.md",
    "algorithms": "domains/algorithms.md",
    "physics": "domains/physics.md",
}
MAX_FILE_CHARS = 14000
MAX_TOTAL_CHARS = 60000


@lru_cache(maxsize=64)
def _read(rel: str) -> str:
    p = KNOWLEDGE_DIR / rel
    if not p.exists():
        return ""
    text = p.read_text(errors="ignore")
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)  # drop frontmatter
    return text


def _sections(text: str, wanted: list[str]) -> str:
    if not wanted:
        return text
    out: list[str] = []
    parts = re.split(r"(?m)^(## .*)$", text)
    # parts: [pre, heading, body, heading, body, ...]
    for i in range(1, len(parts) - 1, 2):
        heading = parts[i].lstrip("# ").strip()
        if any(heading.startswith(w) for w in wanted):
            out.append(parts[i] + parts[i + 1])
    return "\n".join(out)


def guess_domain(text: str) -> str | None:
    t = text.lower()
    scores = {
        "ml": sum(
            t.count(k)
            for k in (
                "neural",
                "model",
                "token",
                "attention",
                "gradient",
                "training",
                "layer",
                "loss",
                "embedding",
                "transformer",
            )
        ),
        "math": sum(
            t.count(k)
            for k in (
                "theorem",
                "proof",
                "lemma",
                "integral",
                "derivative",
                "vector space",
                "eigen",
                "matrix",
                "limit",
            )
        ),
        "algorithms": sum(
            t.count(k)
            for k in (
                "algorithm",
                "complexity",
                "graph",
                "search",
                "sort",
                "dynamic programming",
                "recursion",
                "queue",
            )
        ),
        "physics": sum(
            t.count(k)
            for k in ("force", "energy", "velocity", "field", "wave", "quantum", "particle")
        ),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else None


def knowledge_for(
    archetype: Archetype, secondary: Archetype | None = None, domain: str | None = None
) -> str:
    """Concatenated knowledge, deduplicated by file, capped for prompt budget."""
    chunks: list[str] = []
    seen: set[str] = set()

    def add(rel: str, wanted: list[str] | None = None, cap: int = MAX_FILE_CHARS) -> None:
        if rel in seen:
            return
        seen.add(rel)
        text = _read(rel)
        if wanted is not None:
            text = _sections(text, wanted)
        text = text.strip()
        if not text:
            return
        chunks.append(f"\n\n<!-- {rel} -->\n{text[:cap]}")

    for f in CORE_FILES:
        add(f, cap=20000)
    for f, wanted in CORE_RULE_SECTIONS.items():
        add(f, wanted, cap=12000)
    for f in ARCHETYPE_FILES.get(archetype, []):
        add(f, cap=10000)
    if secondary:
        for f in ARCHETYPE_FILES.get(secondary, [])[:1]:
            add(f, cap=7000)
    if domain and domain in DOMAIN_FILES:
        add(DOMAIN_FILES[domain], cap=7000)
    text = "".join(chunks)
    return text[:MAX_TOTAL_CHARS]


def list_knowledge() -> list[str]:
    return sorted(str(p.relative_to(KNOWLEDGE_DIR)) for p in KNOWLEDGE_DIR.rglob("*.md"))
