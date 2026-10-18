"""Code generation, extraction and normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass

from manim_engineer.core import AnimationPlan, Finding
from manim_engineer.generation.knowledge_pack import guess_domain, knowledge_for
from manim_engineer.generation.preamble import apply_source_preamble
from manim_engineer.generation.prompts import (
    codegen_prompt,
    repair_prompt,
    revise_prompt,
    system_prompt,
)
from manim_engineer.llm import LLMBackend, LLMRequest

KIT_IMPORT = "from manim_engineer.kit import *"
LEGACY_FIXES = {
    r"\bShowCreation\b": "Create",
    r"\bTexMobject\b": "MathTex",
    r"\bTextMobject\b": "Tex",
    r"\bShowCreationThenFadeOut\b": "Create",
}


@dataclass
class GenerationResult:
    code: str
    model: str
    prompt_hash: str
    raw: str


def extract_code(text: str) -> str:
    """Take the largest ```python block, else the whole text."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, flags=re.S)
    if blocks:
        return max(blocks, key=len).strip("\n") + "\n"
    return text.strip("\n") + "\n"


def normalize(code: str, plan: AnimationPlan) -> str:
    """Cheap deterministic fixes: kit import first, legacy names, class name, config edits,
    and the plan's source preamble written in after the imports."""
    for pat, rep in LEGACY_FIXES.items():
        code = re.sub(pat, rep, code)
    lines = [ln for ln in code.splitlines() if not re.match(r"^\s*config\.[a-z_]+\s*=", ln)]
    code = "\n".join(lines) + "\n"
    code = re.sub(r"^\s*from manim import \*\s*$", "", code, flags=re.M)
    if KIT_IMPORT not in code:
        code = KIT_IMPORT + "\n\n" + code.lstrip("\n")
    else:
        # move the kit import to the very top (after a docstring if any)
        body = code.replace(KIT_IMPORT, "", 1)
        code = KIT_IMPORT + "\n" + body.lstrip("\n")
    # auto-insert stdlib/numpy imports the model used but forgot
    for alias, stmt in (
        ("math", "import math"),
        ("np", "import numpy as np"),
        ("random", "import random"),
        ("itertools", "import itertools"),
    ):
        if re.search(rf"(?<![\w.]){alias}\.", code) and not re.search(
            rf"^\s*(import {alias}\b|import numpy as np|from {alias} import)", code, flags=re.M
        ):
            code = code.replace(KIT_IMPORT + "\n", KIT_IMPORT + "\n" + stmt + "\n", 1)
    # rename the first Scene subclass to the expected name
    m = re.search(r"^class\s+(\w+)\s*\((\w*Scene)\)\s*:", code, flags=re.M)
    if m and m.group(1) != plan.scene_class:
        code = code.replace(f"class {m.group(1)}(", f"class {plan.scene_class}(", 1)
        code = re.sub(rf"\b{m.group(1)}\b", plan.scene_class, code)
    return apply_source_preamble(code, plan)


def _knowledge(plan: AnimationPlan) -> str:
    domain = guess_domain(
        " ".join(
            [plan.concept.title, plan.concept.claim, plan.concept.one_line]
            + [b.purpose for b in plan.beats]
        )
    )
    return knowledge_for(plan.archetype.primary, plan.archetype.secondary, domain)


def generate(plan: AnimationPlan, backend: LLMBackend, tag: str = "codegen") -> GenerationResult:
    req = LLMRequest(
        system=system_prompt(plan.scene_class, _knowledge(plan)),
        prompt=codegen_prompt(plan),
        tier="strong",
        tag=f"{tag}_{plan.concept.concept_id}",
        max_tokens=12000,
    )
    resp = backend.complete(req)
    code = normalize(extract_code(resp.text), plan)
    return GenerationResult(
        code=code, model=resp.model, prompt_hash=req.prompt_hash(), raw=resp.text
    )


def repair(
    plan: AnimationPlan,
    code: str,
    findings: list[Finding],
    backend: LLMBackend,
    notes: str = "",
    tag: str = "repair",
) -> GenerationResult:
    req = LLMRequest(
        system=system_prompt(plan.scene_class, _knowledge(plan)),
        prompt=repair_prompt(plan, code, findings, notes),
        tier="strong",
        tag=f"{tag}_{plan.concept.concept_id}",
        max_tokens=12000,
    )
    resp = backend.complete(req)
    new_code = normalize(extract_code(resp.text), plan)
    return GenerationResult(
        code=new_code, model=resp.model, prompt_hash=req.prompt_hash(), raw=resp.text
    )


def revise(
    plan: AnimationPlan, code: str, note: str, backend: LLMBackend, tag: str = "revise"
) -> GenerationResult:
    req = LLMRequest(
        system=system_prompt(plan.scene_class, _knowledge(plan)),
        prompt=revise_prompt(plan, code, note),
        tier="strong",
        tag=f"{tag}_{plan.concept.concept_id}",
        max_tokens=12000,
    )
    resp = backend.complete(req)
    return GenerationResult(
        code=normalize(extract_code(resp.text), plan),
        model=resp.model,
        prompt_hash=req.prompt_hash(),
        raw=resp.text,
    )
