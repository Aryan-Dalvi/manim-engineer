"""Code generation, repair and revision prompts.

Several rules are adapted from makefinks/manim-generator (MIT): no scene
aggregation, no config edits, no external assets, whole-file responses.
"""

from __future__ import annotations

import json

from manim_engineer.core import AnimationPlan, Finding

SYSTEM_HEADER = """You are a senior Manim Community Edition 0.19 engineer producing short, verified explanatory animations for a presenter's slides.

Hard rules (violations are rejected automatically before render):
1. The file starts with `from manim_engineer.kit import *` and defines exactly one class `{scene_class}(Scene)` with a `construct` method. No other classes. No other imports except `numpy as np`, `math`, `random`, `itertools`.
2. Every planned beat is exactly one `self.next_section("<beat_id>")` call, in plan order, placed before that beat's first `self.play`. Section names must equal the plan's beat ids exactly.
3. Use only ManimCE 0.19 API and the kit helpers. Never use ManimGL names (ShowCreation, TexMobject, CONFIG, get_graph). Never touch `config`. Never reference files, images, SVGs or sounds.
4. Place everything with the kit: `place(mob, "region")`, `fit_to_region`, `section_title`, `caption`, `flow_diagram`, `timeline`, `comparison_table`, `tensor_grid`, `cell_grid`, `plot_in_region`, `next_to`, `arrange`. No absolute coordinates beyond |x| 6, |y| 3.4. Nothing may overlap unintentionally; FadeOut what a beat no longer needs before the next beat places something in the same region.
5. Text: labels not sentences; `safe_text`/`wrap_text`/`safe_multiline` only; font sizes >= 20. LaTeX only inside `MathTex`/`Tex` with raw strings; equations come from the plan verbatim.
6. Pacing: every `self.play` has an explicit `run_time`; after each beat's last animation `self.wait(<wait_after_s>)`. Total duration close to the plan's target. At most 3 simultaneous animations.
7. End with `fade_all(self)` unless the plan says the final frame should persist.
8. Keep the file compact: roughly 60-150 lines, no comments explaining the obvious, no helper classes. Think briefly; the plan already made the design decisions.

Respond with the complete Python file in one ```python fenced block and nothing else."""


def system_prompt(scene_class: str, knowledge: str) -> str:
    return SYSTEM_HEADER.format(scene_class=scene_class) + "\n\n# Reference material\n" + knowledge


def _plan_block(plan: AnimationPlan) -> str:
    beats = []
    for b in plan.beats:
        beats.append(
            f"- {b.beat_id} ({b.duration_s:.1f}s + wait {b.wait_after_s:.1f}s): {b.purpose}\n"
            f"    visuals: {b.visuals or '(designer choice within the archetype)'}\n"
            f"    narration: {b.narration}"
        )
    eqs = "\n".join(f"- {e.label}: `{e.latex}`" for e in plan.provenance.equations) or "(none)"
    ledger = (
        "\n".join(
            f"- {s.latex} = {s.meaning}" + (f" (color {s.color})" if s.color else "")
            for s in plan.symbol_ledger
        )
        or "(none)"
    )
    quotes = "\n".join(f"> {q}" for q in plan.provenance.quotes)
    return f"""Concept: {plan.concept.title}
One line: {plan.concept.one_line}
Claim to convey: {plan.concept.claim}
Takeaway: {plan.concept.takeaway or plan.concept.claim}
Audience: {plan.audience.level}
Archetype: {plan.archetype.primary}{(" + " + str(plan.archetype.secondary)) if plan.archetype.secondary else ""}
Layout template: {plan.layout.template}
Target duration: {plan.budgets.target_duration_s:.0f}s; max concurrent mobjects {plan.budgets.max_concurrent_mobjects}; max on-screen text {plan.budgets.on_screen_text_chars} chars
Scene class: {plan.scene_class}

Beats (section names must match these ids exactly, in this order):
{chr(10).join(beats)}

Equations from the source (use verbatim):
{eqs}

Symbol ledger (one color and meaning per symbol, everywhere):
{ledger}

Source quotes (do not assert beyond them):
{quotes}
"""


ARCHETYPE_HINTS = {
    "equation_derivation": "Build the equation as a list of MathTex substrings so TransformMatchingTex can move parts. Dim then highlight one term at a time; keep the current equation in main_upper and annotations in main_lower.",
    "function_plot": "Use plot_in_region for the axes. Sweep parameters with a ValueTracker and always_redraw; label the swept value with a DecimalNumber. Keep the legend in the emptiest corner.",
    "geometric": "Compute coordinates in Python from the construction (do not hand-type floats). Use Vector/Line/Angle/Polygon; keep labels next_to their objects.",
    "flow_diagram": "Use flow_diagram(nodes, edges, direction=...) for the boxes and arrows; reveal boxes with LaggedStart(FadeIn), then arrows, then annotate one stage at a time with dim/undim.",
    "memory_layout": "Use cell_grid(rows, cols, labels=..., colors=..., row_labels=..., col_labels=...) for the array / bank picture (at most 8 rows x 32 cols; use 8x8 for a tile, 1x32 for the banks). Color cells by bank or by source column with a small PALETTE_CYCLE lookup; show a permutation with self.play(*g.permute(lambda r, c: (r, c ^ r)), run_time=RT_TRANSFORM) and highlight the cells one warp touches with self.play(*g.highlight(cells)). State the rule and the conflict count before/after in a caption; never hand-place cells.",
    "tensor_flow": "Use tensor_grid for each stage side by side (left/main/right regions) with shape labels; animate a highlighted row or column flowing between stages.",
    "timeline": "Use timeline(steps) and reveal boxes one by one; add a caption per step in the footer and replace it with ReplacementTransform.",
    "comparison_table": "Use comparison_table(headers, rows, highlight=(r, c)); reveal rows with LaggedStart and Indicate the winning cell.",
    "algorithm_trace": "Show 5-8 lines of pseudocode as safe_text lines arranged in the left region; move a SurroundingRectangle down the lines; show a small state panel on the right.",
    "graph_network": "Use Graph(vertices, edges, layout=dict(...)) with a hand-specified layout inside the main region; Flash/Indicate vertices in sequence.",
    "matrix_transform": "Use Matrix/MathTex for the matrices; highlight rows and columns with SurroundingRectangle; optionally a NumberPlane in the left region and the matrix in the right.",
    "distribution": "Use plot_in_region for the density or BarChart for a histogram; seed numpy; show the parameter with a ValueTracker.",
    "number_line": "Use NumberLine fitted to the main region; move a Dot with a DecimalNumber label; brace intervals.",
    "sets": "Use two or three Circles with fill_opacity 0.3 and labels; Intersection/Union to highlight regions.",
    "surface_3d": "ThreeDScene with ThreeDAxes and a Surface of modest resolution; keep camera moves slow.",
}


def codegen_prompt(plan: AnimationPlan) -> str:
    hint = ARCHETYPE_HINTS.get(plan.archetype.primary, "")
    return f"""Write the Manim scene for this plan.

{_plan_block(plan)}
Archetype guidance: {hint}

Return only the complete Python file."""


def findings_block(findings: list[Finding], limit: int = 20) -> str:
    lines = []
    for f in findings[:limit]:
        loc = f" (line {f.line})" if f.line else (f" [{f.beat_id}]" if f.beat_id else "")
        lines.append(
            f"- [{f.severity}] {f.gate}{loc}: {f.message}\n    fix: {f.fix or 'see message'}"
        )
    return "\n".join(lines)


def repair_prompt(plan: AnimationPlan, code: str, findings: list[Finding], notes: str = "") -> str:
    return f"""The scene below was rejected by automatic verification. Fix every listed finding and return the whole corrected file (do not leave anything out, do not add comments about the changes).

Findings (location, observed problem, admissible fix):
{findings_block(findings)}
{("Traceback context:" + chr(10) + notes) if notes else ""}

Plan reminder:
{_plan_block(plan)}

Current file:
```python
{code}
```

Return only the complete corrected Python file."""


def revise_prompt(plan: AnimationPlan, code: str, note: str) -> str:
    return f"""A human reviewer asked for a change to this scene. Apply it faithfully while keeping every plan beat and all the hard rules. Return the whole file.

Reviewer note: {note}

Plan reminder:
{_plan_block(plan)}

Current file:
```python
{code}
```

Return only the complete revised Python file."""


def plan_json(plan: AnimationPlan) -> str:
    return json.dumps(plan.model_dump(by_alias=True), indent=1)
