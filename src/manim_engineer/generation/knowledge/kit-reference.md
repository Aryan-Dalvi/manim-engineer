# manim_engineer.kit reference

Every generated scene starts with `from manim_engineer.kit import *`, which also
imports all of `manim`. Use these helpers instead of absolute coordinates.

## Regions (name → what it is for)

| region | purpose | size (world units) |
| --- | --- | --- |
| `title` | persistent header, one line | 13.2 × 0.9 at y≈3.25 |
| `main` | the primary content | 13.2 × 5.4 centered slightly below origin |
| `main_upper` / `main_lower` | split main vertically | 13.2 × 2.6 each |
| `left` / `right` | dual panel | 6.2 × 5.4 each |
| `stage` / `sidebar` | wide stage plus a narrow annotation column | 9.8 × 5.4 and 3.6 × 5.4 |
| `footer` | caption / takeaway, one line | 13.2 × 0.8 at y≈-3.3 |

Frame is 14.2 × 8 world units. Safe area: |x| ≤ 6.6, |y| ≤ 3.7. Never place
anything with absolute coordinates beyond that; use the helpers below.

## Placement helpers

- `place(mob, "region")` — move a mobject to a region's center (scales down if it does not fit).
- `fit_to_region(mob, "region", margin=0.15)` — scale to fit and center.
- `region_center("region")` — the center point of a region (numpy array).
- `clamp_to_safe(mob)` — push a mobject back inside the safe area.
- `label_for(mob, "text", direction=DOWN)` — small label next_to a mobject, clamped to the frame.

## Text helpers (never use raw `Text` for anything longer than a few words)

- `safe_text("one line", font_size=BODY_SIZE, color=C["text"], max_width=12.2)` — width-capped single line.
- `safe_multiline("line one", "line two")` — centered multi-line block (VGroup).
- `wrap_text("long sentence …", max_chars=48)` — greedy wrap into a centered block.
- `section_title("Title")` — a title already placed in the `title` region.
- `caption("takeaway")` — a caption already placed in the `footer` region. Reveal with `FadeIn(cap, shift=UP*0.2)`.
- `labeled_box("Encoder", width=2.4, height=0.9, color=C["primary"])` — rounded box with a fitted label; `box.rect`, `box.label`.

Font sizes: `TITLE_SIZE=44`, `SUBTITLE_SIZE=32`, `BODY_SIZE=28`, `LABEL_SIZE=22`, `EQ_SIZE=42`, `EQ_SMALL=30`. Minimum `MIN_FONT_SIZE=20`.

## Deterministic layout builders (use these for diagrams; they never overflow)

- `flow_diagram(nodes, edges, direction="right"|"down", region="main")`
  - `nodes`: `["Input", "Encoder", "Decoder"]` or `[("enc", "Encoder", C["primary"]), ...]`
  - `edges`: `[("enc", "dec")]` or `[("enc", "dec", "context")]`
  - returns a `FlowDiagram` (VGroup) with `.boxes[id]` and `.arrows[(a, b)]` so you can animate parts: `self.play(LaggedStart(*[FadeIn(b) for b in fd.boxes.values()], lag_ratio=0.2))`.
- `timeline(["t=0", "t=1", "t=2", ...], region="main", max_visible=6)` — steps with arrows; `.boxes` list.
- `comparison_table(headers, rows, region="main", highlight=(row, col))` — `.table` is a Manim `Table`.
- `tensor_grid(rows, cols, label="B×T", region="left")` — grid of cells (capped at 6×6) with a label; `.cells`.
- `cell_grid(rows, cols, labels=None, colors=None, region="main", row_labels=None, col_labels=None)` — labelled grid of cells (≤ 8×32) for memory layouts, banks, tiles and permutations. `labels`/`colors` may be a callable `(r, c) -> str|color` or a 2D list; default label is the row-major index. `.cell(r, c)`, `.row(r)`, `.col(c)`, `.squares[r][c]`, `.labels[r][c]`, `.slot_center(r, c)`. `self.play(*g.permute(lambda r, c: (r, c ^ r)))` moves every cell to its target slot; `self.play(*g.highlight([(0, 3), (1, 3)], C["accent"]))` fills cells.
- `bullet_list("point one", "point two", region="right")` — ≤5 width-capped bullets.
- `plot_in_region(f, x_range, y_range, region="main", x_label="x", y_label="y")` → `(axes, graph, labels)` sized to the region.

## Lifecycle and emphasis

- `fade_all(self)` — FadeOut everything on screen (use between beats when the layout changes).
- `dim(self, *mobs)` / `undim(self, *mobs)` — set opacity to `DIM_OPACITY` (0.15) and back.
- `arrow_between(a, b)` — arrow from the nearest edges of two mobjects.
- Timing constants: `RT_WRITE=1.2`, `RT_FADE=0.6`, `RT_TRANSFORM=1.5`, `HOLD_SHORT=0.6`, `HOLD_MEDIUM=1.5`, `HOLD_LONG=2.5`.
- Palette: `C["primary"]`, `C["secondary"]`, `C["accent"]`, `C["positive"]`, `C["negative"]`, `C["muted"]`, `C["text"]`; `PALETTE_CYCLE` for series.

## Scene skeleton

```python
from manim_engineer.kit import *


class ConceptScene(Scene):
    def construct(self):
        self.next_section("b1_setup")  # section name == beat id, every beat
        title = section_title("What we are showing")
        self.play(Write(title), run_time=RT_WRITE)
        eq = MathTex(r"y = Wx + b", font_size=EQ_SIZE)
        place(eq, "main_upper")
        self.play(Write(eq), run_time=RT_WRITE)
        self.wait(HOLD_MEDIUM)

        self.next_section("b2_transform")
        fd = flow_diagram(["x", "W", "y"], [("x", "W"), ("W", "y")], region="main_lower")
        self.play(LaggedStart(*[FadeIn(b) for b in fd.boxes.values()], lag_ratio=0.2), run_time=1.2)
        self.play(*[Create(a) for a in fd.arrows.values()], run_time=0.8)
        cap = caption("Linear layer: matrix multiply then add a bias")
        self.play(FadeIn(cap, shift=UP * 0.2), run_time=RT_FADE)
        self.wait(HOLD_LONG)
        fade_all(self)
```
