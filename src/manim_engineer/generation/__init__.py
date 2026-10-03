"""generation bounded context: plan → Manim code, with repair and revision prompts."""

from manim_engineer.generation.codegen import (
    KIT_IMPORT,
    GenerationResult,
    extract_code,
    generate,
    normalize,
    repair,
    revise,
)
from manim_engineer.generation.knowledge_pack import guess_domain, knowledge_for, list_knowledge
from manim_engineer.generation.preamble import apply_source_preamble
from manim_engineer.generation.prompts import (
    codegen_prompt,
    findings_block,
    repair_prompt,
    revise_prompt,
    system_prompt,
)
from manim_engineer.generation.templates import fallback_scene

__all__ = [
    "KIT_IMPORT",
    "GenerationResult",
    "apply_source_preamble",
    "codegen_prompt",
    "extract_code",
    "fallback_scene",
    "findings_block",
    "generate",
    "guess_domain",
    "knowledge_for",
    "list_knowledge",
    "normalize",
    "repair",
    "repair_prompt",
    "revise",
    "revise_prompt",
    "system_prompt",
]
