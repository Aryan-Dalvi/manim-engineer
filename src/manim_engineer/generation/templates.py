"""Deterministic fallback scene: always renders, always inside the frame.

Used when the repair budget is exhausted (ADR 0004 §7.4 in the research):
title, then per beat a section with the equation (if any) or a wrapped
narration line and a caption. Layout-safe by construction via the kit.
"""

from __future__ import annotations

from manim_engineer.core import AnimationPlan
from manim_engineer.generation.preamble import apply_source_preamble


def _py(s: str) -> str:
    return repr(s)


def fallback_scene(plan: AnimationPlan) -> str:
    eqs = [e.latex for e in plan.provenance.equations if e.latex]
    lines: list[str] = [
        "from manim_engineer.kit import *",
        "",
        "",
        f"class {plan.scene_class}(Scene):",
        "    def construct(self):",
        f"        title = section_title({_py(plan.concept.title)})",
    ]
    for i, b in enumerate(plan.beats):
        lines.append(f"        self.next_section({_py(b.beat_id)})")
        if i == 0:
            lines.append("        self.play(Write(title), run_time=RT_WRITE)")
        else:
            lines.append("        fade_all(self)")
            lines.append("        self.add(title)")
        body_var = f"body{i}"
        if i < len(eqs):
            lines.append(f"        {body_var} = MathTex({_py(eqs[i])}, font_size=EQ_SIZE)")
            lines.append(f"        fit_to_region({body_var}, 'main_upper')")
            lines.append(f"        self.play(Write({body_var}), run_time=RT_WRITE)")
        else:
            purpose = b.purpose or b.narration or plan.concept.claim
            lines.append(
                f"        {body_var} = wrap_text({_py(purpose)}, max_chars=44, font_size=SUBTITLE_SIZE)"
            )
            lines.append(f"        place({body_var}, 'main_upper')")
            lines.append(f"        self.play(FadeIn({body_var}, shift=UP * 0.2), run_time=RT_FADE)")
        narr = b.narration or b.purpose
        if narr:
            lines.append(
                f"        note{i} = wrap_text({_py(narr[:160])}, max_chars=60, font_size=LABEL_SIZE, color=C['muted'])"
            )
            lines.append(f"        place(note{i}, 'main_lower')")
            lines.append(f"        self.play(FadeIn(note{i}, shift=UP * 0.2), run_time=RT_FADE)")
        hold = max(1.0, min(b.duration_s + b.wait_after_s - 1.8, 8.0))
        lines.append(f"        self.wait({hold:.1f})")
    lines.append(
        f"        cap = caption({_py((plan.concept.takeaway or plan.concept.claim)[:110])})"
    )
    lines.append("        self.play(FadeIn(cap, shift=UP * 0.2), run_time=RT_FADE)")
    lines.append("        self.wait(HOLD_LONG)")
    lines.append("        fade_all(self)")
    # the source equations above may need the paper's packages and macros
    return apply_source_preamble("\n".join(lines) + "\n", plan)
