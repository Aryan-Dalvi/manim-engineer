"""Triage and planner prompts plus their JSON schemas."""

from __future__ import annotations

from typing import Any

from manim_engineer.core import Archetype, AudienceLevel

ARCHETYPES = [a.value for a in Archetype]
LEVELS = [a.value for a in AudienceLevel]

ARCHETYPE_GUIDE = """
- equation_derivation: rewrite/derive an equation step by step (MathTex + TransformMatchingTex). Best for formulas.
- function_plot: a curve or family of curves on axes, often with a swept parameter (Axes, plot, ValueTracker).
- geometric: shapes, vectors, angles, projections, constructions (Vector, Line, Angle, Polygon).
- flow_diagram: box-and-arrow architecture or pipeline (kit.flow_diagram). Best for systems / model architectures.
- tensor_flow: shape tracking of data through stages (kit.tensor_grid + arrows).
- memory_layout: addresses, banks, tiles, index bits and permutations of labelled cells (kit.cell_grid). Best for GPU memory, caches, data layouts, swizzles.
- timeline: ordered steps/rollout/decoding loop over time (kit.timeline).
- comparison_table: methods vs metrics, ablations (kit.comparison_table).
- algorithm_trace: pseudocode with a moving highlight and a state panel.
- graph_network: nodes and edges, message passing, search (Graph with fixed layout).
- matrix_transform: matrices, linear maps, change of basis (Matrix, LinearTransformationScene).
- distribution: histograms/densities/samples (Axes + BarChart, seeded samples).
- number_line: limits, counting, intervals (NumberLine).
- sets: Venn/partition (Circle + boolean ops).
- surface_3d: 3D surfaces (only if allowed).
"""

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "worth_animating": {"type": "boolean"},
        "salience": {"type": "integer", "minimum": 1, "maximum": 5},
        "concept_name": {"type": "string"},
        "reason": {"type": "string"},
        "archetype": {"type": "string", "enum": ARCHETYPES},
        "has_equation": {"type": "boolean"},
        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
    },
    "required": [
        "worth_animating",
        "salience",
        "concept_name",
        "reason",
        "archetype",
        "difficulty",
    ],
}


def triage_prompt(bucket_text: str, doc_title: str, span_label: str, heading: str = "") -> str:
    return f"""You are triaging a passage from a talk or document titled "{doc_title}" ({span_label}{", section: " + heading if heading else ""}) to decide whether it deserves a short (10-40 s) explanatory animation.

Animate when the passage contains a mechanism, derivation, spatial relationship, sequence of steps, architecture, or comparison that a viewer would understand better by seeing it move. Do not animate greetings, logistics, motivation-only prose, lists of names, or restatements of something already obvious.

Archetypes:{ARCHETYPE_GUIDE}
Passage:
\"\"\"
{bucket_text[:6000]}
\"\"\"

Return JSON: worth_animating, salience (1 = filler, 5 = the key idea of the talk), concept_name (short noun phrase), reason (one sentence), archetype (best fit), has_equation, difficulty."""


BEAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "beat_id": {"type": "string", "description": "b<n>_<slug>, e.g. b1_setup"},
        "purpose": {"type": "string"},
        "visuals": {
            "type": "string",
            "description": "What is on screen and what moves in this beat, concretely: elements, positions (regions: title, main, main_upper, main_lower, left, right, sidebar, footer), transforms.",
        },
        "narration": {
            "type": "string",
            "description": "One or two sentences the presenter would say during this beat.",
        },
        "duration_s": {"type": "number", "minimum": 1, "maximum": 20},
        "wait_after_s": {"type": "number", "minimum": 0, "maximum": 4},
    },
    "required": ["beat_id", "purpose", "visuals", "narration", "duration_s", "wait_after_s"],
}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "concept_id": {
            "type": "string",
            "description": "lowercase slug, letters digits underscores",
        },
        "title": {"type": "string"},
        "one_line": {"type": "string"},
        "claim": {
            "type": "string",
            "description": "The single assertion this animation must convey.",
        },
        "evidence": {"type": "string"},
        "takeaway": {"type": "string"},
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "audience_level": {"type": "string", "enum": LEVELS},
        "archetype": {"type": "string", "enum": ARCHETYPES},
        "secondary_archetype": {"type": "string", "enum": ARCHETYPES + [""]},
        "archetype_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "layout_template": {
            "type": "string",
            "enum": [
                "FULL_CENTER",
                "DUAL_PANEL",
                "TOP_PERSISTENT_BOTTOM_CONTENT",
                "BUILD_UP",
                "CHART_FOCUS",
            ],
        },
        "target_duration_s": {"type": "number", "minimum": 8, "maximum": 60},
        "symbol_ledger": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "latex": {"type": "string"},
                    "meaning": {"type": "string"},
                    "color": {"type": "string"},
                },
                "required": ["symbol", "latex", "meaning"],
            },
        },
        "equations": {
            "type": "array",
            "description": "Equations used on screen, verbatim from the source when the source has them.",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "latex": {"type": "string"}},
                "required": ["label", "latex"],
            },
        },
        "quotes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-3 verbatim source sentences that ground the claim.",
        },
        "beats": {"type": "array", "minItems": 2, "maxItems": 7, "items": BEAT_SCHEMA},
        "priority": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "concept_id",
        "title",
        "one_line",
        "claim",
        "audience_level",
        "archetype",
        "archetype_confidence",
        "layout_template",
        "target_duration_s",
        "beats",
        "quotes",
        "priority",
    ],
}


def plan_prompt(
    bucket_text: str,
    doc_title: str,
    span_label: str,
    equations: list[str],
    triage_hint: str,
    audience: str,
    constraints: list[str],
    context_summary: str = "",
) -> str:
    eqs = "\n".join(f"- {e}" for e in equations) or "(none in the source)"
    cons = "\n".join(f"- {c}" for c in constraints) or "(none)"
    return f"""Design a short explanatory animation (Manim) for one concept from "{doc_title}" ({span_label}).

Triage said: {triage_hint}
Audience: {audience}
{("Context so far: " + context_summary) if context_summary else ""}

Source passage (ground truth; do not assert anything it does not support):
\"\"\"
{bucket_text[:7000]}
\"\"\"

Equations found in the source (use verbatim when relevant):
{eqs}

Archetypes:{ARCHETYPE_GUIDE}
Design rules:
- One claim per animation. Every beat must serve that claim.
- 2 to 6 beats, 10 to 40 seconds total. Each beat: what appears, what transforms, what disappears, in a named region.
- Keep on-screen text short (labels, not sentences). The narration carries the words.
- Prefer concrete values, geometry before algebra, and one visual technique per beat.
- Use the symbol ledger so a symbol has one color and one meaning across beats.
- For architectures/pipelines describe nodes and edges explicitly; for plots give ranges; for derivations give each intermediate expression in LaTeX.
- beat_id format: b1_slug, b2_slug ... in order.
Extra constraints:
{cons}

Return the plan as JSON matching the schema."""
