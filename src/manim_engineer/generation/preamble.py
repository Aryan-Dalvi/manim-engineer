"""Write the plan's source preamble into a scene as one generated header (ADR 0010).

The header is rebuilt from the plan whenever code is normalized, so whatever the
model does to it is replaced, and it carries only the definitions the scene uses.
"""

from __future__ import annotations

import ast
import re

from manim_engineer.core import AnimationPlan, parse_macro_definitions, select_definitions

HEADER_BEGIN = "# source-preamble: generated from the plan; edits here are replaced"
HEADER_END = "# end source-preamble"
_BLOCK = re.compile(
    rf"^{re.escape(HEADER_BEGIN)}\n.*?^{re.escape(HEADER_END)}[ \t]*\n?", re.M | re.S
)
_KIT_IMPORT = re.compile(r"from manim_engineer\.kit import \*[ \t]*\n?")
_IMPORT_LINE = re.compile(r"(?:import \S|from \S+ import )")


def _strip(code: str) -> str:
    """Code without any header block, or any stray use_source_preamble(...) statement."""
    code = _BLOCK.sub("", code)
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    lines = code.splitlines(keepends=True)
    for node in reversed(tree.body):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "use_source_preamble"
        ):
            del lines[node.lineno - 1 : node.end_lineno]
    return "".join(lines)


def _literal(s: str) -> str:
    """A Python literal for s: a raw string when that is exact, so it reads as TeX."""
    if '"' not in s and "\n" not in s and not s.endswith("\\"):
        return f'r"{s}"'
    if '"""' not in s and not s.endswith(("\\", '"')):
        return f'r"""{s}"""'
    return repr(s)


def source_preamble_header(plan: AnimationPlan, code: str) -> str:
    """The header `code` needs under this plan, or "" when there is nothing to apply."""
    definitions = select_definitions(
        parse_macro_definitions(plan.provenance.macros).definitions, code
    )
    packages = plan.provenance.packages
    if not packages and not definitions:
        return ""
    lines = [HEADER_BEGIN, "use_source_preamble(", f"    packages={packages!r},"]
    if definitions:
        lines += [
            "    definitions=[",
            *(f"        {_literal(d.source)}," for d in definitions),
            "    ],",
        ]
    lines += [")", HEADER_END]
    return "\n".join(lines) + "\n"


def apply_source_preamble(code: str, plan: AnimationPlan) -> str:
    """Replace any header in `code` with the one the plan and the code call for.

    It goes after the kit import and the imports that follow it. Code for a plan
    without a source preamble comes back unchanged.
    """
    body = _strip(code)
    header = source_preamble_header(plan, body)
    if not header:
        return body
    lines = body.splitlines(keepends=True)
    at = next((i + 1 for i, ln in enumerate(lines) if _KIT_IMPORT.fullmatch(ln)), 0)
    while at < len(lines) and _IMPORT_LINE.match(lines[at]):
        at += 1
    rest = "".join(lines[at:])
    gap = "" if rest.startswith("\n") else "\n"
    return "".join(lines[:at]) + "\n" + header + gap + rest
