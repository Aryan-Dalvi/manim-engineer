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


# The environment and argument separator each Manim TeX class compiles with by default.
_TEX_DEFAULTS: dict[str, tuple[str | None, str | None]] = {
    "MathTex": ("align*", " "),
    "SingleStringMathTex": ("align*", None),  # one string, never split into parts
    "Tex": ("center", ""),
    "Title": ("center", ""),
    "BulletedList": (None, ""),
}
_TEX_CALLS = set(_TEX_DEFAULTS)
_UNKNOWN = object()


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


def _keyword(node: ast.Call, name: str, default: object) -> object:
    for kw in node.keywords:
        if kw.arg == name:
            try:
                return ast.literal_eval(kw.value)
            except (ValueError, TypeError, SyntaxError):
                return _UNKNOWN
    return default


def _tex_parts(strings: list[str], isolate: list[str]) -> list[str]:
    """MathTex._break_up_tex_strings: {{ }} groups and isolated substrings become parts."""
    pieces = [p for s in strings for p in re.split("{{(.*?)}}", s)]
    if isolate:
        pattern = "|".join(f"({re.escape(s)})" for s in isolate)
        pieces = [p for s in pieces for p in re.split(pattern, s)]
    return [p for p in pieces if p]


def tex_compile_jobs(tree: ast.Module) -> list[tuple[int, str, str, str | None]]:
    """(line, class, expression, environment) for every document Manim typesets for a TeX call.

    MathTex typesets the joined string and then each part on its own, so Tier 0 does
    too. A call that brings its own tex_template, or computes its environment,
    separator or isolated substrings at runtime, is left to the Tier 1 probe.
    """
    jobs: list[tuple[int, str, str, str | None]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _TEX_DEFAULTS
        ):
            continue
        if any(kw.arg == "tex_template" for kw in node.keywords):
            continue
        kind = node.func.id
        env_default, sep_default = _TEX_DEFAULTS[kind]
        env = _keyword(node, "tex_environment", env_default)
        sep = _keyword(node, "arg_separator", sep_default)
        isolate = _keyword(node, "substrings_to_isolate", None) or []
        color_map = _keyword(node, "tex_to_color_map", None) or {}
        if not (
            (env is None or isinstance(env, str))
            and (sep is None or isinstance(sep, str))
            and isinstance(isolate, list | tuple)
            and isinstance(color_map, dict)
            and all(isinstance(s, str) for s in [*isolate, *color_map])
        ):
            continue
        strings = [
            a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
        ]
        if not strings:
            continue
        if kind == "BulletedList":
            strings = [s + "\\\\" for s in strings]
        if sep is None:
            exprs = strings[:1]
        else:
            parts = _tex_parts(strings, [*isolate, *color_map])
            joined = [sep.join(parts)] if len(strings) == len(node.args) else []
            exprs = joined + parts
        jobs += [(node.lineno, kind, e, env) for e in exprs if e.strip()]
    return jobs


def _as_manim_typesets(expression: str) -> str:
    # Manim rewrites every string before compiling it (closes stray braces, balances
    # \left/\right, pads a trailing ^ or _). The rewrite reads no instance state, so an
    # uninitialised mobject runs Manim's own code and Tier 0 cannot drift from it.
    from manim import SingleStringMathTex

    return SingleStringMathTex.__new__(SingleStringMathTex)._get_modified_expression(expression)


def _compile_tex(
    template, expression: str, environment: str | None, workdir: Path, timeout: int
) -> str | None:
    """Typeset one expression the way Manim does: None if it compiles, else the TeX error."""
    from manim.utils.tex_file_writing import make_tex_compilation_command

    if environment:
        source = template.get_texcode_for_expression_in_env(expression, environment)
    else:
        source = template.get_texcode_for_expression(expression)
    tex = workdir / "t.tex"
    tex.write_text(source, encoding="utf-8")
    cmd = make_tex_compilation_command(template.tex_compiler, template.output_format, tex, workdir)
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if cp.returncode == 0:
        return None
    log_path = workdir / "t.log"
    log = log_path.read_text(errors="ignore") if log_path.exists() else cp.stdout
    errs = [ln for ln in log.splitlines() if ln.startswith("!")][:2]
    return " | ".join(errs) or f"{template.tex_compiler} exited {cp.returncode}"


def check_latex(tree: ast.Module, timeout: int = 40) -> list[Finding]:
    jobs = tex_compile_jobs(tree)
    if not jobs:
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
    from manim import TexTemplate

    template = TexTemplate()
    out: list[Finding] = []
    seen: set[tuple[str, str | None]] = set()
    with tempfile.TemporaryDirectory() as d:
        for lineno, kind, expression, environment in jobs:
            body = _as_manim_typesets(expression)
            if (body, environment) in seen:
                continue
            seen.add((body, environment))
            try:
                err = _compile_tex(template, body, environment, Path(d), timeout)
            except subprocess.TimeoutExpired:
                out.append(
                    Finding(
                        gate="latex",
                        severity=Severity.FATAL,
                        line=lineno,
                        message=f"{kind}({expression!r}) LaTeX timed out",
                        fix="Simplify the expression.",
                    )
                )
                continue
            if err is not None:
                out.append(
                    Finding(
                        gate="latex",
                        severity=Severity.FATAL,
                        line=lineno,
                        message=f"{kind}({expression!r}) does not compile: {err}",
                        fix="Fix the TeX: use only commands Manim's preamble defines (amsmath, amssymb), escape %, use raw strings; use Text() for plain words.",
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
