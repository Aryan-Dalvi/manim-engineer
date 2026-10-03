"""Source preamble: the TeX packages and macro definitions a source's equations need.

Pure text processing: no Manim, no I/O. ingest extracts definitions with it,
generation selects the ones a scene uses, and the kit turns them into a Manim
TexTemplate, so all three agree on what a definition is. arXiv source is
third-party input, so only allowlisted packages, and definitions that cannot
reach files or the shell, get through.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

# Math-notation packages that compile on Manim's latex -> dvisvgm path. Adding one
# means adding it to the kit's compile test first.
TEX_PACKAGE_ALLOWLIST: frozenset[str] = frozenset(
    {"amsfonts", "bm", "dsfont", "mathrsfs", "mathtools", "physics", "xcolor", "xspace"}
)
# Manim's default TexTemplate loads these already; a source loading them is not news.
_MANIM_DEFAULT_PACKAGES = frozenset({"amsmath", "amssymb", "babel"})

# Primitives that read or write files, run programs, change how TeX reads input,
# or build a control sequence from characters (which would get around this list).
_DENIED = frozenset(
    {
        "input",
        "include",
        "InputIfFileExists",
        "IfFileExists",
        "openin",
        "openout",
        "read",
        "readline",
        "write",
        "immediate",
        "special",
        "catcode",
        "csname",
        "scantokens",
        "endinput",
        "usepackage",
        "RequirePackage",
        "documentclass",
        "makeatletter",
    }
)
MAX_DEFINITION_CHARS = 2000

_DEFINER = re.compile(
    r"\\(newcommand|renewcommand|providecommand|DeclareMathOperator|def|gdef|let)(?![A-Za-z@])"
)
_CONTROL = re.compile(r"\\([A-Za-z@]+|.)", re.S)
_CONTROL_WORD = re.compile(r"\\+([A-Za-z@]+)")
_PACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


@dataclass(frozen=True)
class MacroDefinition:
    """One definition as the source wrote it, plus a form safe to put in any preamble."""

    name: str  # without the backslash
    source: str
    safe: str
    uses: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DroppedDefinition:
    source: str
    reason: str


@dataclass
class MacroScan:
    definitions: list[MacroDefinition] = field(default_factory=list)
    dropped: list[DroppedDefinition] = field(default_factory=list)


@dataclass
class PackageScan:
    allowed: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def _skip_space(t: str, i: int) -> int:
    while i < len(t) and t[i].isspace():
        i += 1
    return i


def _group_end(t: str, i: int) -> int | None:
    """Index just past the brace group opening at t[i], or None if it never closes."""
    depth = 0
    while i < len(t):
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _optional_end(t: str, i: int) -> int | None:
    """Index just past the [ ] argument opening at t[i]; braces inside may hold a ]."""
    depth = 0
    i += 1
    while i < len(t):
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "]" and depth == 0:
            return i + 1
        i += 1
    return None


def _control(t: str, i: int) -> tuple[str, int] | None:
    m = _CONTROL.match(t, i)
    return (m.group(1), m.end()) if m else None


def _name_argument(t: str, i: int) -> tuple[str, int] | None:
    """`{\\name}` or `\\name`, as \\newcommand and \\DeclareMathOperator take it."""
    i = _skip_space(t, i)
    if i < len(t) and t[i] == "{":
        end = _group_end(t, i)
        if end is None:
            return None
        inner = t[i + 1 : end - 1].strip()
        cs = _control(inner, 0)
        return (cs[0], end) if cs and cs[1] == len(inner) else None
    return _control(t, i) if i < len(t) and t[i] == "\\" else None


def _parse_one(t: str, start: int, command: str, i: int) -> tuple[str, int] | None:
    """(name, end) of the definition whose definer ends at i, or None if it is malformed."""
    if command == "let":
        target = _control(t, _skip_space(t, i))
        if target is None:
            return None
        name, i = target
        i = _skip_space(t, i)
        if i < len(t) and t[i] == "=":
            i = _skip_space(t, i + 1)
        if i >= len(t):
            return None
        alias = _control(t, i)
        return (name, alias[1]) if alias else (name, i + 1)
    if command in ("def", "gdef"):
        target = _control(t, _skip_space(t, i))
        if target is None:
            return None
        name, i = target
        brace = t.find("{", i)
        if brace < 0 or "}" in t[i:brace]:
            return None
        end = _group_end(t, brace)
        return (name, end) if end else None
    i = _skip_space(t, i)
    if i < len(t) and t[i] == "*":
        i += 1
    named = _name_argument(t, i)
    if named is None:
        return None
    name, i = named
    if command != "DeclareMathOperator":
        for _ in range(2):  # [number of arguments] then [default of the first]
            i = _skip_space(t, i)
            if i < len(t) and t[i] == "[":
                end = _optional_end(t, i)
                if end is None:
                    return None
                i = end
    i = _skip_space(t, i)
    if i >= len(t) or t[i] != "{":
        return None
    end = _group_end(t, i)
    return (name, end) if end else None


def _safe_form(command: str, name: str, source: str) -> str:
    # A paper may renew a command Manim's preamble lacks, or create one it already has.
    # Neither should stop the whole preamble from compiling.
    if command in ("newcommand", "renewcommand"):
        # everything after the definer, so a * (short macro) is kept
        return f"\\providecommand{{\\{name}}}{{}}\\renewcommand{source[len(command) + 1 :]}"
    if command == "DeclareMathOperator":
        return f"\\let\\{name}\\relax{source}"
    return source


def _rejection(name: str, source: str, uses: frozenset[str]) -> str | None:
    if len(source) > MAX_DEFINITION_CHARS:
        return f"longer than {MAX_DEFINITION_CHARS} characters"
    if "^^" in source:
        return "uses a ^^ character escape"
    if "@" in name:
        return "defines a LaTeX internal (@) name"
    denied = sorted(({name} | uses) & _DENIED)
    if denied:
        return f"uses \\{denied[0]}, which can reach files or the shell"
    if any("@" in u for u in uses):
        return "uses LaTeX internal (@) commands"
    return None


def parse_macro_definitions(tex: str) -> MacroScan:
    """Every top-level definition in comment-free TeX, in source order.

    Definitions are brace-matched, so one spanning several lines is kept whole. A
    definition that never closes, or that fails the safety rules, is dropped with a
    reason. A definer inside another definition's body is part of that body.
    """
    scan = MacroScan()
    i = 0
    while (m := _DEFINER.search(tex, i)) is not None:
        command = m.group(1)
        parsed = _parse_one(tex, m.start(), command, m.end())
        if parsed is None:
            scan.dropped.append(
                DroppedDefinition(tex[m.start() : m.start() + 120], "malformed or never closed")
            )
            i = m.end()
            continue
        name, end = parsed
        source = tex[m.start() : end]
        uses = frozenset(_CONTROL_WORD.findall(source)) - {command, name}
        reason = _rejection(name, source, uses)
        if reason:
            scan.dropped.append(DroppedDefinition(source[:200], reason))
        else:
            scan.definitions.append(
                MacroDefinition(
                    name=name,
                    source=source,
                    safe=_safe_form(command, name, source),
                    uses=uses,
                )
            )
        i = end
    return scan


def select_definitions(definitions: Sequence[MacroDefinition], text: str) -> list[MacroDefinition]:
    """The definitions `text` uses, plus the ones those use, in source order."""
    by_name: dict[str, list[MacroDefinition]] = {}
    for d in definitions:
        by_name.setdefault(d.name, []).append(d)
    needed: set[str] = set()
    pending = [n for n in set(_CONTROL_WORD.findall(text)) if n in by_name]
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        needed.add(name)
        for d in by_name[name]:
            pending += [u for u in d.uses if u in by_name and u not in needed]
    return [d for d in definitions if d.name in needed]


def parse_tex_packages(tex: str) -> PackageScan:
    """Packages a preamble loads: allowlisted ones to keep, others reported as ignored."""
    scan = PackageScan()
    for m in _PACKAGE.finditer(tex):
        for raw in m.group(1).split(","):
            name = raw.strip()
            if not name or name in scan.allowed or name in scan.ignored:
                continue
            if name in TEX_PACKAGE_ALLOWLIST:
                scan.allowed.append(name)
            elif name not in _MANIM_DEFAULT_PACKAGES:
                scan.ignored.append(name)
    return scan


def source_preamble_tex(packages: Iterable[str], definitions: Iterable[MacroDefinition]) -> str:
    """Lines to append to Manim's default preamble: packages, then safe definitions."""
    packages = list(dict.fromkeys(packages))
    outside = [p for p in packages if p not in TEX_PACKAGE_ALLOWLIST]
    if outside:
        raise ValueError(f"TeX packages not in the allowlist: {outside}")
    lines = [f"\\usepackage{{{p}}}" for p in packages]
    lines += [d.safe for d in definitions]
    return "\n".join(lines)
