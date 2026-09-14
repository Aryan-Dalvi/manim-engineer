# ManimCE 0.19 pitfalls (this project pins ManimCE 0.19.x)

Hallucinated or wrong-version API is the top crash cause in LLM-written Manim.
The verifier introspects the installed module, so anything not in ManimCE 0.19
is rejected before render. Common traps:

- `ShowCreation` does not exist: use `Create`. `TexMobject`/`TextMobject` do not exist: use `MathTex`/`Tex`.
- `Axes.get_graph` does not exist: use `axes.plot(lambda x: ..., color=...)`.
- `ApplyMethod` is deprecated: use `mob.animate.method(...)` inside `self.play`.
- `CONFIG = {...}` dictionaries are ManimGL: pass kwargs to `__init__` instead.
- `Code(...)` was rewritten in 0.19: `Code(code_string=..., language="python", ...)`. Prefer `Text`/`MarkupText` with a monospace font for short pseudocode.
- `ManimColor.from_hex(hex_str=...)`, not `hex=`.
- `SurroundingRectangle(mob, color=..., buff=...)` — pass mobjects positionally, options as keywords.
- `Sector` has no `inner_radius`/`outer_radius`; use `AnnularSector`.
- `interpolate_color` needs `ManimColor` objects: wrap hex strings with `ManimColor("#...")` or use constants like `BLUE_C`.
- `Brace.get_text("label", font_size=24)` crashes: build `Tex("label", font_size=24)` and call `brace.put_at_tip(label)`.
- `LaggedStartMap(Write, group)` crashes on Text: use `LaggedStart(*[Write(m) for m in group], lag_ratio=0.2)`.
- `Transform(a, b)` keeps `a` in the scene; later animating `b` does nothing. Use `ReplacementTransform(a, b)` or `TransformMatchingTex`.
- `MathTex(r"$x$")` crashes (already math mode). Use `Tex(r"text with $x$")` for mixed text.
- `%` inside LaTeX starts a comment: write `50\%`.
- Always use raw strings for LaTeX: `MathTex(r"\frac{1}{2}")`.
- `Text("line one\nline two")` left-aligns lines; use `safe_multiline`.
- `.animate` returns a builder: never `VGroup.add(m.animate...)`. Use `.animate` only inside `self.play`.
- `Group.save_state()` crashes; use `VGroup`.
- Updaters do not run during `self.wait()` unless `frozen_frame=False`.
- Late-binding closures in loops: `lambda m, o=obj: m.next_to(o, UP)`.
- `self.next_section(name)` takes the name positionally; give every beat exactly one section named by its beat id.
- Do not set `config.*` inside the scene; do not import anything except `manim`, `manim_engineer.kit`, `numpy`, `math`, `random`, `itertools`.
- No external files: no `ImageMobject`, `SVGMobject`, sounds, or paths.
