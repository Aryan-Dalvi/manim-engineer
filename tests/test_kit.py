import pytest
from manim import MathTex, TexTemplate, config, tempconfig

import manim_engineer.kit.preamble as kit_preamble
from manim_engineer.core import TEX_PACKAGE_ALLOWLIST
from manim_engineer.kit import (
    SAFE_X,
    SAFE_Y,
    CellGrid,
    ComparisonTable,
    FlowDiagram,
    TensorGrid,
    Timeline,
    bullet_list,
    caption,
    installed_tex_packages,
    label_for,
    labeled_box,
    plot_in_region,
    safe_multiline,
    safe_text,
    section_title,
    source_tex_template,
    use_source_preamble,
    wrap_text,
)


def _inside(mob, tol=0.05):
    return (
        mob.get_left()[0] >= -SAFE_X - tol
        and mob.get_right()[0] <= SAFE_X + tol
        and mob.get_bottom()[1] >= -SAFE_Y - tol
        and mob.get_top()[1] <= SAFE_Y + tol
    )


def test_safe_text_caps_width_and_min_font():
    t = safe_text("x " * 200, font_size=10)
    assert t.width <= 12.3
    assert _inside(t)


def test_multiline_and_wrap_are_centered_and_inside():
    g = safe_multiline("one", "two two two", "three")
    assert abs(g.get_center()[0]) < 1e-6
    w = wrap_text(
        "a fairly long sentence that must wrap into several lines for the frame", max_chars=20
    )
    assert len(w) >= 3 and _inside(w)


def test_title_and_caption_land_in_regions():
    t = section_title(
        "A very long title that should still fit inside the safe frame width comfortably"
    )
    c = caption("caption text")
    assert _inside(t) and _inside(c)
    assert t.get_center()[1] > 2.5 and c.get_center()[1] < -2.5


def test_label_for_is_clamped_near_edge():
    box = labeled_box("edge").move_to([SAFE_X - 0.3, 0, 0])
    lab = label_for(box, "a long label that would poke out", direction=[1, 0, 0])
    assert _inside(lab)


@pytest.mark.parametrize("n", [3, 8, 14])
def test_flow_diagram_stays_inside_for_many_nodes(n):
    nodes = [f"n{i}" for i in range(n)]
    edges = [(f"n{i}", f"n{i + 1}") for i in range(n - 1)]
    fd = FlowDiagram(nodes, edges, direction="right")
    assert _inside(fd)
    assert set(fd.boxes) == set(nodes)
    assert len(fd.arrows) == n - 1


def test_flow_diagram_ranks_branches():
    fd = FlowDiagram(
        ["in", "a", "b", "out"], [("in", "a"), ("in", "b"), ("a", "out"), ("b", "out")]
    )
    assert fd.boxes["a"].get_center()[0] == pytest.approx(fd.boxes["b"].get_center()[0])
    assert (
        fd.boxes["in"].get_center()[0]
        < fd.boxes["a"].get_center()[0]
        < fd.boxes["out"].get_center()[0]
    )


def test_timeline_elides_and_fits():
    tl = Timeline([f"step {i}" for i in range(12)])
    assert len(tl.boxes) == 6 and _inside(tl)


def test_table_caps_and_fits():
    tb = ComparisonTable(
        ["m", "a", "b", "c", "d", "e"], [[str(i)] * 6 for i in range(9)], highlight=(0, 1)
    )
    assert _inside(tb)


def test_tensor_grid_caps_dims():
    g = TensorGrid(32, 128, label="X")
    assert len(g.cells) == 36 and _inside(g)
    assert "shown as" in g.label.original_text


def test_bullets_and_plot_fit():
    b = bullet_list(*[f"item {i} with some text" for i in range(9)])
    assert len(b) == 5 and _inside(b)
    axes, graph, labels = plot_in_region(
        lambda x: x**2, [-3, 3, 1], [0, 9, 3], x_label="x", y_label="y"
    )
    assert _inside(axes) and _inside(graph)


def test_cell_grid_labels_colors_and_fits():
    g = CellGrid(
        8,
        32,
        colors=lambda r, c: "#ff0000" if c == 0 else "#00ff00",
        row_labels=[f"r{i}" for i in range(8)],
    )
    assert g.rows == 8 and g.cols == 32 and _inside(g)
    assert g.labels[1][0].original_text == "32"
    big = CellGrid(64, 128)
    assert big.rows == 8 and big.cols == 32 and _inside(big)
    named = CellGrid(2, 4, labels=[["a", "b", "c", "d"], ["e", "f", "g", "h"]], region="left")
    assert named.labels[1][3].original_text == "h" and _inside(named)


def test_cell_grid_permute_targets_original_slots():
    g = CellGrid(4, 8)
    anims = g.permute(lambda r, c: (r, c ^ r))
    assert len(anims) == 3 * 8  # row 0 is fixed by XOR with 0
    for r in range(4):
        for c in range(8):
            target = g.slot_center(r, c ^ r)
            assert abs(target[0] - g.cell(r, c ^ r).get_center()[0]) < 1e-6
    assert len(g.highlight([(0, 0), (3, 7)])) == 2
    assert g.permute({(0, 0): (0, 0)}) == []


def _tex_config(tmp_path) -> dict:
    return {"media_dir": str(tmp_path), "tex_dir": str(tmp_path / "Tex"), "verbosity": "ERROR"}


def test_source_template_adds_installed_packages_and_safe_definitions(monkeypatch):
    monkeypatch.setattr(kit_preamble, "_kpsewhich", lambda names: frozenset({"mathtools"}) & names)
    template = source_tex_template(
        packages=["mathtools", "bm"],
        definitions=[
            r"\newcommand{\KL}{D_{\mathrm{KL}}}",
            r"\newcommand{\secret}{\input{/etc/passwd}}",
        ],
    )
    # bm is not installed in this fake, and \secret reads a file: both are left out
    assert template.preamble == (
        TexTemplate().preamble
        + "\n\\usepackage{mathtools}\n\\providecommand{\\KL}{}\\renewcommand{\\KL}{D_{\\mathrm{KL}}}"
    )


def test_use_source_preamble_applies_until_the_config_is_reset(tmp_path):
    with tempconfig(_tex_config(tmp_path)):
        use_source_preamble(definitions=[r"\newcommand{\KL}{D_{\mathrm{KL}}}"])
        MathTex(r"\KL(p \| q)")  # compiles only with the paper's definition
    assert config.tex_template.preamble == TexTemplate().preamble


def test_safe_forms_compile_where_the_source_forms_fail(tmp_path):
    # each of these stops a plain preamble: \vec and \det exist, \nothere does not
    definitions = [
        r"\newcommand{\vec}[1]{\mathbf{#1}}",
        r"\renewcommand{\nothere}{y}",
        r"\DeclareMathOperator{\det}{Det}",
    ]
    with tempconfig(_tex_config(tmp_path)):
        use_source_preamble(definitions=definitions)
        MathTex(r"\vec{x} + \det A + \nothere")


@pytest.mark.parametrize("package", sorted(TEX_PACKAGE_ALLOWLIST))
def test_every_allowlisted_package_compiles_with_manims_template(tmp_path, package):
    if package not in installed_tex_packages([package]):
        pytest.skip(f"{package}.sty is not installed here")
    with tempconfig(_tex_config(tmp_path)):
        use_source_preamble(packages=[package])
        MathTex(r"x^2 + y^2 = z^2")
