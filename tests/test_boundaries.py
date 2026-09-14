"""Enforce the forbidden-import policy from .beryl/agent/architecture.md."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "manim_engineer"
CONTEXTS = {
    "core",
    "llm",
    "ingest",
    "planning",
    "generation",
    "kit",
    "verification",
    "output",
    "pipeline",
}
PURE = {"core"}  # must not import manim, vendor SDKs, or subprocess
FORBIDDEN_EDGES = {
    ("planning", "generation"),
    ("generation", "verification"),
    ("kit", "llm"),
    ("kit", "planning"),
    ("kit", "generation"),
    ("kit", "verification"),
    ("kit", "output"),
    ("kit", "pipeline"),
}


def _imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_contexts_import_only_public_entry_points():
    violations = []
    for ctx in CONTEXTS:
        for py in (SRC / ctx).rglob("*.py"):
            for mod in _imports(py):
                if not mod.startswith("manim_engineer."):
                    continue
                parts = mod.split(".")
                target = parts[1] if len(parts) > 1 else ""
                if target in CONTEXTS and target != ctx and len(parts) > 2:
                    violations.append(f"{py.relative_to(SRC)} imports internal {mod}")
                if (ctx, target) in FORBIDDEN_EDGES:
                    violations.append(f"{py.relative_to(SRC)} imports forbidden context {target}")
    assert not violations, "\n".join(violations)


def test_core_is_pure():
    bad = []
    for py in (SRC / "core").rglob("*.py"):
        for mod in _imports(py):
            root = mod.split(".")[0]
            if root in {
                "manim",
                "anthropic",
                "subprocess",
                "requests",
                "yt_dlp",
                "pymupdf",
                "fitz",
            }:
                bad.append(f"{py.name} imports {mod}")
    assert not bad, bad
