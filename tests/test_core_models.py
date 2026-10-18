import json

import pytest
from pydantic import ValidationError

from manim_engineer.core import (
    TEX_PACKAGE_ALLOWLIST,
    AnimationPlan,
    Archetype,
    ArchetypeChoice,
    Beat,
    Budgets,
    Concept,
    Equation,
    Finding,
    Modality,
    Provenance,
    Severity,
    SourceSpan,
    parse_macro_definitions,
    parse_tex_packages,
    select_definitions,
    source_preamble_tex,
)


def _plan(**over):
    base = dict(
        plan_id="plan_test",
        concept=Concept(
            concept_id="softmax_temperature",
            title="Softmax temperature",
            one_line="Dividing logits by T flattens or sharpens the distribution.",
            claim="Lower temperature sharpens softmax.",
        ),
        archetype=ArchetypeChoice(primary=Archetype.FUNCTION_PLOT, confidence=0.8),
        beats=[
            Beat(beat_id="b1_intro", purpose="show logits", duration_s=3),
            Beat(beat_id="b2_sweep", purpose="sweep T", duration_s=5),
        ],
    )
    base.update(over)
    return AnimationPlan(**base)


def test_plan_round_trips_through_json():
    p = _plan()
    data = json.loads(p.model_dump_json(by_alias=True))
    p2 = AnimationPlan.model_validate(data)
    assert p2 == p
    assert p2.scene_class == "SoftmaxTemperatureScene"
    assert p2.total_duration_s == pytest.approx(3 + 0.5 + 5 + 0.5)


def test_duplicate_beat_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate beat ids"):
        _plan(beats=[Beat(beat_id="b1_x", purpose="a"), Beat(beat_id="b1_x", purpose="b")])


def test_beat_id_format_enforced():
    with pytest.raises(ValidationError, match="beat_id"):
        Beat(beat_id="intro", purpose="a")


def test_budget_beats_and_duration_enforced():
    with pytest.raises(ValidationError, match="exceed max_beats"):
        _plan(budgets=Budgets(max_beats=1))
    with pytest.raises(ValidationError, match="exceeds 1.6x"):
        _plan(
            budgets=Budgets(target_duration_s=3),
            beats=[Beat(beat_id="b1_a", purpose="a", duration_s=10)],
        )


def test_3d_requires_budget_flag():
    with pytest.raises(ValidationError, match="allow_3d"):
        _plan(archetype=ArchetypeChoice(primary=Archetype.SURFACE_3D))


def test_source_span_needs_exactly_one_locator():
    SourceSpan(modality=Modality.SLIDES, doc_id="d", slide_index=3)
    SourceSpan(modality=Modality.AUDIO, doc_id="d", t_start_s=1, t_end_s=2)
    with pytest.raises(ValidationError):
        SourceSpan(modality=Modality.SLIDES, doc_id="d")
    with pytest.raises(ValidationError):
        SourceSpan(modality=Modality.SLIDES, doc_id="d", slide_index=1, para_id="p1")
    with pytest.raises(ValidationError):
        SourceSpan(modality=Modality.AUDIO, doc_id="d", t_start_s=5, t_end_s=2)


def test_span_labels():
    assert SourceSpan(modality=Modality.SLIDES, doc_id="d", slide_index=14).label() == "slide 14"
    assert (
        SourceSpan(modality=Modality.AUDIO, doc_id="d", t_start_s=61, t_end_s=125).label()
        == "01:01–02:05"
    )


def test_markdown_mirror_mentions_beats_and_claim():
    md = _plan().to_markdown()
    assert "# Softmax temperature" in md
    assert "`b2_sweep`" in md
    assert "Lower temperature sharpens softmax." in md


def test_equation_defaults_to_unsourced():
    e = Equation(label="eq1", latex="a=b")
    assert e.verbatim is False and e.para_id == "" and e.env == ""


def test_finding_one_line_includes_fix():
    f = Finding(
        gate="overlap",
        severity=Severity.FATAL,
        message="A and B overlap",
        fix="shift B down 0.5",
        beat_id="b1_intro",
    )
    assert f.blocking
    assert "[fatal] overlap [b1_intro]: A and B overlap  → shift B down 0.5" == f.one_line()


def _macro_names(tex: str) -> list[str]:
    return [d.name for d in parse_macro_definitions(tex).definitions]


def test_macro_parser_reads_every_definition_form():
    tex = r"""
\newcommand{\R}{\mathbb{R}}
\newcommand\E{\mathbb{E}}
\renewcommand*{\vec}[1]{\boldsymbol{#1}}
\providecommand{\KL}[2][p]{D_{\mathrm{KL}}(#1 \| #2)}
\DeclareMathOperator*{\argmax}{arg\,max}
\def\vx{{\bm{x}}}
\def\pair#1#2{(#1, #2)}
\let\epsilon\varepsilon
"""
    assert _macro_names(tex) == ["R", "E", "vec", "KL", "argmax", "vx", "pair", "epsilon"]


def test_macro_parser_keeps_multi_line_definitions_whole():
    tex = "\\newcommand{\\loss}[1]{\n  \\mathcal{L}\\left(#1\\right)\n}\n\\newcommand{\\R}{\\mathbb{R}}\n"
    defs = parse_macro_definitions(tex).definitions
    assert [d.name for d in defs] == ["loss", "R"]
    assert defs[0].source == "\\newcommand{\\loss}[1]{\n  \\mathcal{L}\\left(#1\\right)\n}"


def test_macro_parser_drops_a_truncated_definition_and_keeps_reading():
    # what the old one-line extractor stored for a definition split across lines
    scan = parse_macro_definitions("\\newcommand{\\loss}[1]{\n\\newcommand{\\R}{\\mathbb{R}}")
    assert [d.name for d in scan.definitions] == ["R"]
    assert scan.dropped and "loss" in scan.dropped[0].source


@pytest.mark.parametrize(
    "definition",
    [
        r"\newcommand{\secret}{\input{/etc/passwd}}",
        r"\def\leak{\immediate\write18{ls}}",
        r"\newcommand{\sneaky}{\csname input\endcsname{x}}",
        r"\newcommand{\caret}{\^^69nput{x}}",
        r"\def\@internal{x}",
        r"\newcommand{\usesat}{\@ifnextchar[{a}{b}}",
        r"\let\alias\openout",
    ],
)
def test_macro_parser_drops_definitions_that_reach_files_or_the_shell(definition):
    scan = parse_macro_definitions(definition)
    assert not scan.definitions
    assert scan.dropped and scan.dropped[0].reason


def test_macro_selection_follows_dependencies_and_keeps_source_order():
    defs = parse_macro_definitions(
        r"""
\newcommand{\R}{\mathbb{R}}
\newcommand{\unused}{x}
\newcommand{\vx}{\bm{x}}
\newcommand{\inner}{\langle\vx, \vy\rangle}
\newcommand{\vy}{\bm{y}}
"""
    ).definitions
    code = 'm = MathTex(r"\\inner \\in \\R")'
    assert [d.name for d in select_definitions(defs, code)] == ["R", "vx", "inner", "vy"]


def test_macro_safe_forms_hold_whether_or_not_the_name_exists():
    defs = {
        d.name: d
        for d in parse_macro_definitions(
            r"""
\newcommand{\vec}{x}
\renewcommand{\nothere}{y}
\newcommand*{\short}{z}
\DeclareMathOperator{\det}{det}
\def\vx{{\bm{x}}}
"""
        ).definitions
    }
    assert defs["vec"].safe == r"\providecommand{\vec}{}\renewcommand{\vec}{x}"
    assert defs["nothere"].safe == r"\providecommand{\nothere}{}\renewcommand{\nothere}{y}"
    assert defs["short"].safe == r"\providecommand{\short}{}\renewcommand*{\short}{z}"
    assert defs["det"].safe == r"\let\det\relax\DeclareMathOperator{\det}{det}"
    assert defs["vx"].safe == r"\def\vx{{\bm{x}}}"


def test_package_allowlist_is_the_eight_verified_packages():
    assert TEX_PACKAGE_ALLOWLIST == {
        "amsfonts",
        "bm",
        "dsfont",
        "mathrsfs",
        "mathtools",
        "physics",
        "xcolor",
        "xspace",
    }


def test_package_scan_keeps_allowlisted_math_packages_in_order():
    scan = parse_tex_packages(
        r"""
\usepackage[utf8]{inputenc}
\usepackage{amsmath,amssymb,mathtools}
\usepackage[dvipsnames]{xcolor}
\RequirePackage{bm}
\usepackage{shellesc}
\usepackage{mathtools}
"""
    )
    assert scan.allowed == ["mathtools", "xcolor", "bm"]
    assert scan.ignored == ["inputenc", "shellesc"]


def test_provenance_accepts_only_allowlisted_packages():
    with pytest.raises(ValidationError):
        Provenance(packages=["shellesc"])
    assert Provenance(packages=["bm", "bm", "mathtools"]).packages == ["bm", "mathtools"]


def test_plans_saved_before_packages_existed_still_load():
    data = json.loads(_plan().model_dump_json())
    del data["provenance"]["packages"]
    data["schema_version"] = "1.1"
    assert AnimationPlan.model_validate(data).provenance.packages == []


def test_source_preamble_tex_lists_packages_then_safe_definitions():
    defs = parse_macro_definitions(r"\newcommand{\R}{\mathbb{R}}").definitions
    assert source_preamble_tex(["bm"], defs) == (
        "\\usepackage{bm}\n\\providecommand{\\R}{}\\renewcommand{\\R}{\\mathbb{R}}"
    )
    with pytest.raises(ValueError):
        source_preamble_tex(["shellesc"], [])


def test_markdown_mirror_lists_the_source_preamble():
    plan = _plan(
        provenance=Provenance(packages=["mathtools"], macros=r"\newcommand{\R}{\mathbb{R}}")
    )
    md = plan.to_markdown()
    assert "## Source preamble" in md
    assert "mathtools" in md and "1 macro definition" in md
