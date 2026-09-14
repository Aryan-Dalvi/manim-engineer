"""Tier 0: static checks on a candidate scene file. No render, no scene execution.

Adapted from the validated research module in docs/research/quality-verification.md
§2. The API surface is introspected from the installed Manim, so hallucinated or
wrong-version symbols are caught with a "did you mean" fix.
"""

from __future__ import annotations

import ast
import builtins
import difflib
import inspect
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from manim_engineer.core import Finding, Severity

FORBIDDEN_IMPORTS = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "requests",
    "urllib",
    "pathlib",
    "ctypes",
    "multiprocessing",
    "importlib",
    "http",
    "ftplib",
    "pickle",
}
FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__", "input", "breakpoint"}
BANNED_LEGACY = {
    "ShowCreation": "Renamed to Create in ManimCE.",
    "ShowCreationThenFadeOut": "Removed; use Succession(Create(m), FadeOut(m)).",
    "TexMobject": "Renamed to MathTex.",
    "TextMobject": "Renamed to Tex.",
    "get_graph": "Renamed to Axes.plot(...).",
    "ApplyMethod": "Deprecated; use mob.animate.<method>().",
    "CONFIG": "ManimGL only; ManimCE uses __init__ kwargs.",
    "ShowPassingFlashAround": "Use Circumscribe or Flash.",
    "ContinualAnimation": "Removed; use updaters.",
    "LaggedStartMap(Write": "Crashes on Text groups; use LaggedStart(*[Write(m) for m in group]).",
    "frozen_frame=True": "Freezes updaters during wait; drop it or use frozen_frame=False.",
}
DYNAMIC_ATTRS = {
    "target",
    "saved_state",
    "updaters",
    "submobjects",
    "points",
    "value",
    "label",
    "rect",
    "boxes",
    "arrows",
    "cells",
    "table",
}
MODULE_ALIASES = {
    "math": "import math",
    "np": "import numpy as np",
    "numpy": "import numpy",
    "random": "import random",
    "itertools": "import itertools",
}
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".mp3", ".wav", ".mp4")
ALLOWED_IMPORT_ROOTS = {
    "manim",
    "manim_engineer",
    "numpy",
    "math",
    "random",
    "itertools",
    "functools",
    "typing",
    "dataclasses",
    "collections",
    "__future__",
}


@lru_cache(maxsize=1)
def manim_surface() -> dict[str, object]:
    import manim

    names = {n for n in dir(manim) if not n.startswith("_")}
    members: dict[str, set[str]] = {}
    for n in names:
        obj = getattr(manim, n)
        if inspect.isclass(obj):
            members[n] = {a for a in dir(obj) if not a.startswith("__")}
    try:
        from manim_engineer.kit import KIT_EXPORTS

        names |= set(KIT_EXPORTS)
    except Exception:  # pragma: no cover
        pass
    return {"names": names, "members": members, "version": manim.__version__}


def _suggest(name: str, cls: str | None = None) -> str:
    surf = manim_surface()
    pool = surf["members"].get(cls, set()) if cls else surf["names"]  # type: ignore[union-attr]
    m = difflib.get_close_matches(name, sorted(pool), n=3, cutoff=0.7)
    return (
        f"Did you mean: {', '.join(m)}?"
        if m
        else "No close match in this Manim version; use a documented ManimCE 0.19 API."
    )


def check_parse(src: str) -> tuple[ast.Module | None, list[Finding]]:
    try:
        return ast.parse(src), []
    except SyntaxError as e:
        return None, [
            Finding(
                gate="parse",
                severity=Severity.FATAL,
                line=e.lineno or 0,
                message=f"SyntaxError: {e.msg}",
                fix="Return valid Python 3.11.",
            )
        ]


def check_forbidden(tree: ast.Module, src: str) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if root in FORBIDDEN_IMPORTS or root not in ALLOWED_IMPORT_ROOTS:
                    out.append(
                        Finding(
                            gate="sandbox",
                            severity=Severity.FATAL,
                            line=node.lineno,
                            message=f"import '{a.name}' is not allowed in a scene",
                            fix="Use only manim, manim_engineer.kit, numpy, math, random, itertools.",
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_IMPORTS or root not in ALLOWED_IMPORT_ROOTS:
                out.append(
                    Finding(
                        gate="sandbox",
                        severity=Severity.FATAL,
                        line=node.lineno,
                        message=f"import from '{node.module}' is not allowed in a scene",
                        fix="Use only manim, manim_engineer.kit, numpy, math, random, itertools.",
                    )
                )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FORBIDDEN_CALLS
        ):
            out.append(
                Finding(
                    gate="sandbox",
                    severity=Severity.FATAL,
                    line=node.lineno,
                    message=f"call to '{node.func.id}(...)' is not allowed",
                    fix="Remove it; scenes must be self-contained.",
                )
            )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.lower().endswith(ASSET_SUFFIXES)
        ):
            out.append(
                Finding(
                    gate="sandbox",
                    severity=Severity.FATAL,
                    line=getattr(node, "lineno", 0),
                    message=f"external asset reference {node.value!r}",
                    fix="Draw it with Manim primitives; external files are not available.",
                )
            )
    for name, why in BANNED_LEGACY.items():
        for m in re.finditer(re.escape(name), src):
            out.append(
                Finding(
                    gate="legacy_api",
                    severity=Severity.FATAL,
                    line=src[: m.start()].count("\n") + 1,
                    message=f"'{name}' is not ManimCE 0.19 API",
                    fix=why,
                )
            )
    return out


def check_structure(tree: ast.Module, expected_class: str | None = None) -> list[Finding]:
    out: list[Finding] = []
    scenes = [
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef)
        and any(isinstance(b, ast.Name) and b.id.endswith("Scene") for b in n.bases)
    ]
    if not scenes:
        return [
            Finding(
                gate="structure",
                severity=Severity.FATAL,
                line=0,
                message="no Scene subclass defined",
                fix=f"Define `class {expected_class or 'MyScene'}(Scene)` with a construct() method.",
            )
        ]
    if expected_class and not any(s.name == expected_class for s in scenes):
        out.append(
            Finding(
                gate="structure",
                severity=Severity.FATAL,
                line=scenes[0].lineno,
                message=f"expected scene class '{expected_class}', found {[s.name for s in scenes]}",
                fix=f"Rename the class to {expected_class}.",
            )
        )
    for s in scenes:
        methods = {m.name for m in s.body if isinstance(m, ast.FunctionDef)}
        if "construct" not in methods:
            out.append(
                Finding(
                    gate="structure",
                    severity=Severity.FATAL,
                    line=s.lineno,
                    message=f"{s.name} has no construct()",
                    fix="Add def construct(self).",
                )
            )
        n_play = sum(
            1
            for n in ast.walk(s)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "play"
        )
        if n_play < 2:
            out.append(
                Finding(
                    gate="structure",
                    severity=Severity.WARN,
                    line=s.lineno,
                    message=f"{s.name} calls self.play() only {n_play} time(s)",
                    fix="Animate each beat with at least one self.play().",
                )
            )
    has_kit = any(
        isinstance(n, ast.ImportFrom) and (n.module or "").startswith("manim_engineer.kit")
        for n in tree.body
    )
    if not has_kit:
        out.append(
            Finding(
                gate="structure",
                severity=Severity.FATAL,
                line=1,
                message="scene does not import manim_engineer.kit",
                fix="Start the file with `from manim_engineer.kit import *`.",
            )
        )
    return out


def _local_names(tree: ast.Module) -> set[str]:
    local: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            local.add(node.name)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                local.update(a.arg for a in node.args.args + node.args.kwonlyargs)
                if node.args.vararg:
                    local.add(node.args.vararg.arg)
                if node.args.kwarg:
                    local.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            local.add(node.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for a in node.names:
                local.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.arg):
            local.add(node.arg)
        elif isinstance(node, ast.comprehension):
            for t in ast.walk(node.target):
                if isinstance(t, ast.Name):
                    local.add(t.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local.add(node.name)
    return local


def check_symbols(tree: ast.Module) -> list[Finding]:
    surf = manim_surface()
    names: set[str] = surf["names"]  # type: ignore[assignment]
    members: dict[str, set[str]] = surf["members"]  # type: ignore[assignment]
    out: list[Finding] = []
    local = _local_names(tree)
    assigned: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Name) and f.id in members:
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        assigned[tgt.id] = f.id
    builtin_names = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            n = node.id
            if n in local or n in names or n in builtin_names or n == "self":
                continue
            if n in MODULE_ALIASES:
                out.append(
                    Finding(
                        gate="api",
                        severity=Severity.FATAL,
                        line=node.lineno,
                        message=f"'{n}' is used but never imported",
                        fix=f"add `{MODULE_ALIASES[n]}` after the kit import",
                    )
                )
                continue
            if n[0].isupper():
                out.append(
                    Finding(
                        gate="api",
                        severity=Severity.FATAL,
                        line=node.lineno,
                        message=f"'{n}' is not exported by manim {surf['version']} or the kit",
                        fix=_suggest(n),
                    )
                )
        elif isinstance(node, ast.Attribute):
            v = node.value
            if (
                isinstance(v, ast.Attribute)
                and v.attr == "animate"
                and isinstance(v.value, ast.Name)
            ):
                v = v.value
            if not isinstance(v, ast.Name) or node.attr == "animate" or node.attr.startswith("_"):
                continue
            cls = assigned.get(v.id)
            if node.attr in DYNAMIC_ATTRS:
                continue
            if cls and node.attr not in members[cls]:
                out.append(
                    Finding(
                        gate="api",
                        severity=Severity.FATAL,
                        line=node.lineno,
                        message=f"{cls} has no attribute '{node.attr}'",
                        fix=_suggest(node.attr, cls),
                    )
                )
            elif (
                v.id == "self"
                and node.attr not in members.get("Scene", set())
                and node.attr not in members.get("ThreeDScene", set())
                and node.attr not in local
            ):
                out.append(
                    Finding(
                        gate="api",
                        severity=Severity.WARN,
                        line=node.lineno,
                        message=f"Scene has no method '{node.attr}'",
                        fix=_suggest(node.attr, "Scene"),
                    )
                )
    return out


def estimate_duration(tree: ast.Module) -> float:
    """Sum over play() of max(run_time) plus waits. Parallel animations share a play()."""
    total = 0.0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr == "play":
            rts = [1.0]
            for kw in node.keywords:
                if kw.arg == "run_time" and isinstance(kw.value, ast.Constant):
                    rts.append(float(kw.value.value))
            for a in node.args:
                if isinstance(a, ast.Call):
                    for kw in a.keywords:
                        if kw.arg == "run_time" and isinstance(kw.value, ast.Constant):
                            rts.append(float(kw.value.value))
            total += max(rts)
        elif node.func.attr in ("wait", "pause"):
            d = 1.0
            if node.args and isinstance(node.args[0], ast.Constant):
                d = float(node.args[0].value)
            for kw in node.keywords:
                if kw.arg == "duration" and isinstance(kw.value, ast.Constant):
                    d = float(kw.value.value)
            total += d
    return total


_TEX_CALLS = {"MathTex", "Tex", "Title", "BulletedList", "SingleStringMathTex"}
_TEX_TEMPLATE = r"""\documentclass[preview]{standalone}
\usepackage[english]{babel}\usepackage{amsmath}\usepackage{amssymb}\usepackage{dsfont}\usepackage{setspace}\usepackage{relsize}\usepackage{ragged2e}\usepackage{physics}\usepackage{xcolor}\usepackage{textcomp}\usepackage{microtype}
\begin{document}
%s
\end{document}
"""


def collect_tex_literals(tree: ast.Module) -> list[tuple[int, str, str]]:
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _TEX_CALLS
        ):
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.strip():
                    out.append((node.lineno, node.func.id, a.value))
    return out


def check_latex(tree: ast.Module, timeout: int = 40) -> list[Finding]:
    lits = collect_tex_literals(tree)
    if not lits:
        return []
    import shutil

    if shutil.which("latex") is None:  # pragma: no cover
        return [
            Finding(
                gate="latex",
                severity=Severity.WARN,
                line=0,
                message="latex not installed; skipping precompile",
                fix="",
            )
        ]
    out: list[Finding] = []
    seen: set[str] = set()
    with tempfile.TemporaryDirectory() as d:
        for lineno, kind, s in lits:
            body = f"$\\displaystyle {s}$" if kind in ("MathTex", "SingleStringMathTex") else s
            if body in seen:
                continue
            seen.add(body)
            f = Path(d) / "t.tex"
            f.write_text(_TEX_TEMPLATE % body)
            try:
                cp = subprocess.run(
                    [
                        "latex",
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-output-directory",
                        d,
                        str(f),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                out.append(
                    Finding(
                        gate="latex",
                        severity=Severity.FATAL,
                        line=lineno,
                        message=f"{kind}({s!r}) LaTeX timed out",
                        fix="Simplify the expression.",
                    )
                )
                continue
            if cp.returncode != 0:
                log_path = Path(d) / "t.log"
                log = log_path.read_text(errors="ignore") if log_path.exists() else cp.stdout
                errs = [ln for ln in log.splitlines() if ln.startswith("!")][:2]
                out.append(
                    Finding(
                        gate="latex",
                        severity=Severity.FATAL,
                        line=lineno,
                        message=f"{kind}({s!r}) does not compile: {' | '.join(errs)}",
                        fix="Fix the TeX (balance braces, escape %, use raw strings) or use Text() for plain words.",
                    )
                )
    return out


def run_tier0(
    path: str | Path,
    expected_class: str | None = None,
    max_duration_s: float = 90.0,
    min_duration_s: float = 3.0,
) -> list[Finding]:
    src = Path(path).read_text()
    tree, findings = check_parse(src)
    if tree is None:
        return findings
    findings += check_forbidden(tree, src)
    findings += check_structure(tree, expected_class)
    findings += check_symbols(tree)
    findings += check_latex(tree)
    dur = estimate_duration(tree)
    if dur > max_duration_s:
        findings.append(
            Finding(
                gate="duration",
                severity=Severity.WARN,
                line=0,
                message=f"estimated duration {dur:.1f}s exceeds {max_duration_s:.0f}s",
                fix="Shorten run_time/wait values or drop a beat.",
            )
        )
    if dur < min_duration_s:
        findings.append(
            Finding(
                gate="duration",
                severity=Severity.WARN,
                line=0,
                message=f"estimated duration only {dur:.1f}s",
                fix="Add waits so viewers can read each beat.",
            )
        )
    return findings
