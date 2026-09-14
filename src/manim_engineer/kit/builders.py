"""Deterministic layout builders for the archetypes LLMs place badly.

The generator emits *what* (nodes, edges, rows, steps); these functions decide
*where*, always inside a named region, so out-of-frame and overlap failures for
box-and-arrow, timeline, table and tensor-grid content are removed by
construction (docs/PLAN.md D8).
"""

from __future__ import annotations

from collections.abc import Sequence

from manim import *  # noqa: F403

from manim_engineer.kit.helpers import (
    arrow_between,
    fit_to_region,
    labeled_box,
    region_box,
    safe_text,
)
from manim_engineer.kit.style import LABEL_SIZE, PALETTE_CYCLE, C


class FlowDiagram(VGroup):  # noqa: F405
    """Boxes plus arrows laid out on a grid of ranks.

    nodes: list of labels or (id, label) or (id, label, color)
    edges: list of (from_id, to_id) or (from_id, to_id, label)
    direction: "right" (pipeline) or "down" (stack). Rank = longest path from a source.
    """

    def __init__(
        self,
        nodes: Sequence,
        edges: Sequence = (),
        direction: str = "right",
        region: str = "main",
        box_w: float = 2.3,
        box_h: float = 0.9,
        gap: float = 0.9,
        colors: dict[str, ManimColor] | None = None,  # noqa: F405
        **kwargs,
    ):
        super().__init__(**kwargs)
        norm = []
        for n in nodes:
            if isinstance(n, str):
                norm.append((n, n, None))
            elif len(n) == 2:
                norm.append((n[0], n[1], None))
            else:
                norm.append((n[0], n[1], n[2]))
        ids = [n[0] for n in norm]
        edge_list = [(e[0], e[1], e[2] if len(e) > 2 else "") for e in edges]
        rank = _ranks(ids, [(a, b) for a, b, _ in edge_list])
        by_rank: dict[int, list[str]] = {}
        for i in ids:
            by_rank.setdefault(rank[i], []).append(i)
        self.boxes: dict[str, VGroup] = {}  # noqa: F405
        columns = []
        for r in sorted(by_rank):
            col = VGroup()  # noqa: F405
            for i in by_rank[r]:
                label = next(n[1] for n in norm if n[0] == i)
                color = (
                    (colors or {}).get(i)
                    or next((n[2] for n in norm if n[0] == i), None)
                    or PALETTE_CYCLE[r % len(PALETTE_CYCLE)]
                )
                b = labeled_box(label, width=box_w, height=box_h, color=color)
                self.boxes[i] = b
                col.add(b)
            col.arrange(DOWN if direction == "right" else RIGHT, buff=gap * 0.5)
            columns.append(col)
        grid = VGroup(*columns).arrange(RIGHT if direction == "right" else DOWN, buff=gap)  # noqa: F405
        self.add(grid)
        self.arrows: dict[tuple[str, str], Arrow] = {}  # noqa: F405
        arrows = VGroup()  # noqa: F405
        for a, b, label in edge_list:
            arr = arrow_between(self.boxes[a], self.boxes[b])
            self.arrows[(a, b)] = arr
            arrows.add(arr)
            if label:
                lab = safe_text(label, font_size=LABEL_SIZE - 4, color=C["muted"], max_width=1.6)
                lab.next_to(arr, UP if direction == "right" else RIGHT, buff=0.05)  # noqa: F405
                arrows.add(lab)
        self.add(arrows)
        fit_to_region(self, region)


def _ranks(ids: Sequence[str], edges: Sequence[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layering; cycles are broken by insertion order."""
    rank = {i: 0 for i in ids}
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for a, b in edges:
        if a in adj and b in adj:
            adj[a].append(b)
    for _ in range(len(ids)):
        changed = False
        for a in ids:
            for b in adj[a]:
                if rank[b] < rank[a] + 1 and rank[a] + 1 < len(ids):
                    rank[b] = rank[a] + 1
                    changed = True
        if not changed:
            break
    return rank


class Timeline(VGroup):  # noqa: F405
    """Horizontal sequence of steps with arrows; at most `max_visible` shown, rest elided."""

    def __init__(
        self,
        steps: Sequence[str],
        region: str = "main",
        max_visible: int = 6,
        box_w: float = 1.9,
        box_h: float = 0.8,
        colors: Sequence | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        shown = list(steps)
        elided = False
        if len(shown) > max_visible:
            shown = shown[: max_visible - 1] + [shown[-1]]
            elided = True
        self.boxes = []
        row = VGroup()  # noqa: F405
        for k, s in enumerate(shown):
            color = (colors[k] if colors and k < len(colors) else None) or PALETTE_CYCLE[
                k % len(PALETTE_CYCLE)
            ]
            b = labeled_box(s, width=box_w, height=box_h, color=color)
            self.boxes.append(b)
            row.add(b)
        row.arrange(RIGHT, buff=0.55)  # noqa: F405
        self.add(row)
        arrows = VGroup()  # noqa: F405
        for a, b in zip(self.boxes, self.boxes[1:], strict=False):
            arrows.add(arrow_between(a, b, buff=0.08))
        if elided:
            dots = safe_text("…", font_size=LABEL_SIZE + 6, color=C["muted"])
            dots.move_to(arrows[-1])
            arrows[-1].set_opacity(0)
            arrows.add(dots)
        self.add(arrows)
        fit_to_region(self, region)


class ComparisonTable(VGroup):  # noqa: F405
    """Text table capped at 4 columns x 5 rows, with an optional highlighted cell."""

    def __init__(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        region: str = "main",
        highlight: tuple[int, int] | None = None,
        max_rows: int = 5,
        max_cols: int = 4,
        **kwargs,
    ):
        super().__init__(**kwargs)
        headers = list(headers)[:max_cols]
        rows = [list(r)[:max_cols] for r in list(rows)[:max_rows]]
        self.table = Table(  # noqa: F405
            [[str(c) for c in r] for r in rows],
            col_labels=[Text(h, font_size=LABEL_SIZE, color=C["accent"]) for h in headers],  # noqa: F405
            element_to_mobject=lambda s: Text(s, font_size=LABEL_SIZE),  # noqa: F405
            include_outer_lines=False,
            line_config={"stroke_width": 1, "color": C["dim"]},
            h_buff=0.6,
            v_buff=0.35,
        )
        if highlight is not None:
            r, c = highlight
            self.table.add_highlighted_cell((r + 2, c + 1), color=C["positive"])
        self.add(self.table)
        fit_to_region(self, region)


class TensorGrid(VGroup):  # noqa: F405
    """Grid of cells (<= 6x6) with a shape label, for tensor/data-flow beats."""

    def __init__(
        self,
        rows: int,
        cols: int,
        label: str = "",
        region: str = "main",
        cell: float = 0.55,
        color=None,
        max_dim: int = 6,
        **kwargs,
    ):
        super().__init__(**kwargs)
        r, c = min(rows, max_dim), min(cols, max_dim)
        color = color or C["primary"]
        self.cells = VGroup(
            *[
                Square(side_length=cell, color=color, fill_opacity=0.25, stroke_width=1.5)
                for _ in range(r * c)
            ]
        )  # noqa: F405
        self.cells.arrange_in_grid(rows=r, cols=c, buff=0.06)
        self.add(self.cells)
        if rows > max_dim or cols > max_dim:
            label = (label + " " if label else "") + f"({rows}×{cols} shown as {r}×{c})"
        if label:
            self.label = safe_text(
                label, font_size=LABEL_SIZE, color=C["muted"], max_width=self.cells.width + 1.5
            )
            self.label.next_to(self.cells, DOWN, buff=0.2)  # noqa: F405
            self.add(self.label)
        fit_to_region(self, region)


def flow_diagram(*args, **kwargs) -> FlowDiagram:
    return FlowDiagram(*args, **kwargs)


def timeline(*args, **kwargs) -> Timeline:
    return Timeline(*args, **kwargs)


def comparison_table(*args, **kwargs) -> ComparisonTable:
    return ComparisonTable(*args, **kwargs)


def tensor_grid(*args, **kwargs) -> TensorGrid:
    return TensorGrid(*args, **kwargs)


def bullet_list(
    *items: str, region: str = "main", font_size: int = LABEL_SIZE + 2, max_items: int = 5
) -> VGroup:  # noqa: F405
    """Left-aligned bullets, width-capped, fitted to a region."""
    x, y, w, h = region_box(region)
    lines = VGroup()  # noqa: F405
    for it in list(items)[:max_items]:
        lines.add(safe_text(f"• {it}", font_size=font_size, max_width=w - 0.4))
    lines.arrange(DOWN, buff=0.3, aligned_edge=LEFT)  # noqa: F405
    return fit_to_region(lines, region)


def plot_in_region(
    func,
    x_range,
    y_range,
    region: str = "main",
    color=None,
    x_label: str = "",
    y_label: str = "",
    **axes_kw,
):
    """Axes + plot sized to a region. Returns (axes, graph, labels VGroup)."""
    x, y, w, h = region_box(region)
    axes = Axes(  # noqa: F405
        x_range=x_range,
        y_range=y_range,
        x_length=min(w - 1.2, 9.0),
        y_length=min(h - 1.0, 4.6),
        axis_config={
            "include_tip": True,
            "tip_width": 0.15,
            "tip_height": 0.15,
            "font_size": LABEL_SIZE - 2,
        },
        **axes_kw,
    )
    graph = axes.plot(func, color=color or C["primary"])
    labels = VGroup()  # noqa: F405
    if x_label:
        labels.add(
            axes.get_x_axis_label(
                MathTex(x_label, font_size=LABEL_SIZE + 4), edge=DOWN, direction=DOWN, buff=0.25
            )
        )  # noqa: F405
    if y_label:
        labels.add(
            axes.get_y_axis_label(
                MathTex(y_label, font_size=LABEL_SIZE + 4), edge=LEFT, direction=LEFT, buff=0.25
            )
        )  # noqa: F405
    g = VGroup(axes, graph, labels)  # noqa: F405
    fit_to_region(g, region)
    return axes, graph, labels


class CellGrid(VGroup):  # noqa: F405
    """Labeled grid of cells (<= 8 rows x 32 cols) for memory layouts, banks and permutations.

    labels: None (row-major index), a callable (r, c) -> str, or a 2D list of strings.
    colors: None (one color), a callable (r, c) -> color, or a 2D list of colors.
    row_labels / col_labels: optional header strings drawn left of the rows / above the columns.
    Access cells with .cell(r, c) (VGroup of square + label), .squares[r][c], .labels[r][c].
    """

    def __init__(
        self,
        rows: int,
        cols: int,
        labels=None,
        colors=None,
        region: str = "main",
        cell: float | None = None,
        row_labels: Sequence[str] | None = None,
        col_labels: Sequence[str] | None = None,
        label_font: int = LABEL_SIZE,
        fill_opacity: float = 0.35,
        max_rows: int = 8,
        max_cols: int = 32,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.rows, self.cols = min(rows, max_rows), min(cols, max_cols)
        if cell is None:
            cell = min(0.7, 12.4 / self.cols, 5.0 / self.rows)
        self.cell_size = cell

        def _label(r: int, c: int) -> str:
            if labels is None:
                return str(r * self.cols + c)
            if callable(labels):
                return str(labels(r, c))
            return str(labels[r][c])

        def _color(r: int, c: int):
            if colors is None:
                return C["primary"]
            if callable(colors):
                return colors(r, c)
            return colors[r][c]

        self.squares: list[list[Square]] = []  # noqa: F405
        self.labels: list[list[Text]] = []  # noqa: F405
        self._cells: list[list[VGroup]] = []  # noqa: F405
        body = VGroup()  # noqa: F405
        for r in range(self.rows):
            sq_row, lb_row, cell_row = [], [], []
            for c in range(self.cols):
                sq = Square(  # noqa: F405
                    side_length=cell,
                    color=_color(r, c),
                    fill_opacity=fill_opacity,
                    stroke_width=1.2,
                )
                txt = safe_text(
                    _label(r, c), font_size=label_font, color=C["text"], max_width=cell - 0.06
                )
                if txt.height > cell - 0.08:
                    txt.scale_to_fit_height(cell - 0.08)
                txt.move_to(sq)
                g = VGroup(sq, txt)  # noqa: F405
                sq_row.append(sq)
                lb_row.append(txt)
                cell_row.append(g)
                body.add(g)
            self.squares.append(sq_row)
            self.labels.append(lb_row)
            self._cells.append(cell_row)
        body.arrange_in_grid(rows=self.rows, cols=self.cols, buff=0.04)
        self.body = body
        self.add(body)
        self.headers = VGroup()  # noqa: F405
        if row_labels:
            for r, name in enumerate(list(row_labels)[: self.rows]):
                h = safe_text(str(name), font_size=label_font - 4, color=C["muted"], max_width=1.4)
                h.next_to(self._cells[r][0], LEFT, buff=0.15)  # noqa: F405
                self.headers.add(h)
        if col_labels:
            for c, name in enumerate(list(col_labels)[: self.cols]):
                h = safe_text(str(name), font_size=label_font - 4, color=C["muted"], max_width=cell)
                h.next_to(self._cells[0][c], UP, buff=0.12)  # noqa: F405
                self.headers.add(h)
        self.add(self.headers)
        fit_to_region(self, region)
        self._centers = [
            [self._cells[r][c].get_center().copy() for c in range(self.cols)]
            for r in range(self.rows)
        ]

    def cell(self, r: int, c: int) -> VGroup:  # noqa: F405
        return self._cells[r][c]

    def row(self, r: int) -> VGroup:  # noqa: F405
        return VGroup(*self._cells[r])  # noqa: F405

    def col(self, c: int) -> VGroup:  # noqa: F405
        return VGroup(*[self._cells[r][c] for r in range(self.rows)])  # noqa: F405

    def slot_center(self, r: int, c: int):
        """Original center of slot (r, c), stable even after cells have been moved."""
        return self._centers[r][c]

    def permute(self, mapping) -> list:
        """Animations moving every cell (r, c) to slot mapping(r, c); use self.play(*g.permute(f)).

        mapping: callable (r, c) -> (r2, c2) or a dict {(r, c): (r2, c2)}. Cells not mapped stay.
        """
        anims = []
        for r in range(self.rows):
            for c in range(self.cols):
                tgt = mapping(r, c) if callable(mapping) else mapping.get((r, c))
                if tgt is None:
                    continue
                r2, c2 = int(tgt[0]) % self.rows, int(tgt[1]) % self.cols
                if (r2, c2) != (r, c):
                    anims.append(self._cells[r][c].animate.move_to(self._centers[r2][c2]))
        return anims

    def highlight(self, cells: Sequence[tuple[int, int]], color=None, opacity: float = 0.7) -> list:
        """Animations that fill the given (r, c) cells with color; use self.play(*g.highlight(...))."""
        color = color or C["accent"]
        return [
            self.squares[r][c].animate.set_fill(color, opacity=opacity).set_stroke(color)
            for r, c in cells
        ]


def cell_grid(*args, **kwargs) -> CellGrid:
    return CellGrid(*args, **kwargs)
