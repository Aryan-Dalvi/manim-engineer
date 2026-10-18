"""The source preamble at scene runtime: one TeX template for every compile in a scene.

Generation writes `use_source_preamble(...)` right after the kit import, from the
plan (ADR 0010). Importing the scene sets Manim's template, so the probe, the
render and anyone running the file by hand typeset with it. Tier 0 builds its
template with `source_tex_template`, so the precompile matches.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from manim import TexTemplate, config

from manim_engineer.core import (
    TEX_PACKAGE_ALLOWLIST,
    parse_macro_definitions,
    source_preamble_tex,
)


@cache
def _kpsewhich(names: frozenset[str]) -> frozenset[str]:
    """The packages among `names` this machine's TeX can find; one call, cached."""
    exe = shutil.which("kpsewhich")
    if not names or exe is None:
        return frozenset()
    try:
        cp = subprocess.run(
            [exe, *sorted(f"{n}.sty" for n in names)], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    # one line per file found; a missing file prints nothing
    return names & {Path(line.strip()).stem for line in cp.stdout.splitlines() if line.strip()}


def installed_tex_packages(
    packages: Sequence[str] = tuple(sorted(TEX_PACKAGE_ALLOWLIST)),
) -> list[str]:
    """The allowlisted packages among `packages` that this machine can load, in order."""
    wanted = [p for p in dict.fromkeys(packages) if p in TEX_PACKAGE_ALLOWLIST]
    found = _kpsewhich(frozenset(wanted))
    return [p for p in wanted if p in found]


def source_tex_template(
    packages: Sequence[str] = (), definitions: Sequence[str] = ()
) -> TexTemplate:
    """Manim's default template plus the installed packages and the safe definitions.

    A package the machine lacks is left out rather than breaking every compile, and
    Tier 0 reports it. Definitions are parsed again, so one that reaches files or
    the shell is dropped here whoever wrote the header.
    """
    template = TexTemplate()
    found = parse_macro_definitions("\n".join(definitions)).definitions
    extra = source_preamble_tex(installed_tex_packages(packages), found)
    if extra:
        template.add_to_preamble(extra)
    return template


def use_source_preamble(packages: Sequence[str] = (), definitions: Sequence[str] = ()) -> None:
    """Typeset every Tex and MathTex in this scene with the source's packages and macros."""
    config.tex_template = source_tex_template(packages, definitions)
