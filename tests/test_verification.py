from pathlib import Path

import pytest

from manim_engineer.core import (
    AnimationPlan,
    Archetype,
    ArchetypeChoice,
    Beat,
    Candidate,
    Concept,
    Equation,
    Provenance,
    Severity,
)
from manim_engineer.llm import FakeBackend
from manim_engineer.verification import (
    check_alignment,
    check_equation_provenance,
    critique,
    run_tier0,
    verify_tier0,
    verify_tier1,
)
from manim_engineer.verification.runner import frames_from_result, run_probe, run_probe_inline

FIX = Path(__file__).parent / "fixtures" / "scenes"


def _cand(name: str, cls: str) -> Candidate:
    return Candidate(plan_id="p", attempt=1, code_path=str(FIX / name), scene_class=cls)


def _plan(beats=("b1_intro", "b2_plot", "b3_outro")):
    return AnimationPlan(
        plan_id="p",
        concept=Concept(concept_id="softmax_t", title="Softmax T", one_line="x", claim="y"),
        archetype=ArchetypeChoice(primary=Archetype.EQUATION_DERIVATION),
        provenance=Provenance(
            equations=[Equation(label="eq1", latex=r"p_i = \frac{e^{z_i/T}}{\sum_j e^{z_j/T}}")]
        ),
        beats=[
            Beat(beat_id=b, purpose=b, duration_s=3, narration="a few words here") for b in beats
        ],
    )


def test_tier0_flags_hallucinated_legacy_forbidden_and_latex():
    findings = run_tier0(FIX / "bad_static.py", "BadStaticScene")
    gates = {f.gate for f in findings}
    assert {"sandbox", "legacy_api", "api", "latex", "structure"} <= gates
    api = [f for f in findings if f.gate == "api"]
    assert any("shift_right" in f.message and "Did you mean" in f.fix for f in api)
    assert any("ColorfulBlob" in f.message for f in api)
    assert any(f.gate == "latex" and "does not compile" in f.message for f in findings)
    assert all(f.fix for f in findings if f.severity == Severity.FATAL)


def test_tier0_passes_good_scene_and_checks_equation_provenance():
    rep = verify_tier0(_cand("good_scene.py", "GoodScene"), _plan())
    assert rep.ok, [f.one_line() for f in rep.findings]
    assert not [f for f in rep.findings if f.gate == "fidelity"]


def test_probe_good_scene_yields_keyframes_and_no_findings():
    rep = verify_tier1(_cand("good_scene.py", "GoodScene"), _plan(), inline=True)
    assert rep.ok, [f.one_line() for f in rep.findings]
    assert rep.duration_s and rep.duration_s > 5
    fatal = [f for f in rep.findings if f.severity == Severity.FATAL]
    assert not fatal


def test_probe_bad_layout_reports_overlap_out_of_frame_and_small_text():
    rep = verify_tier1(_cand("bad_layout.py", "BadLayoutScene"), None, inline=True)
    gates = {f.gate for f in rep.findings}
    assert {"overlap", "out_of_frame", "text_too_small"} <= gates
    ov = next(f for f in rep.findings if f.gate == "overlap")
    assert "minimum separation" in ov.fix and ov.beat_id == "b2_overlap"
    oof = next(f for f in rep.findings if f.gate == "out_of_frame")
    assert "shift it by" in oof.fix
    assert not rep.ok


def test_probe_runtime_error_is_condensed_and_categorized():
    res = run_probe_inline(FIX / "runtime_error.py", "RuntimeErrorScene")
    assert res["ok"] is False and res["category"] == "api"
    assert "shift_right" in res["error"] and res["line"] == 9
    assert res["user_frames"] and "shift_right" in res["user_frames"][-1]["source"]


@pytest.mark.integration
def test_probe_in_sandboxed_child_process():
    res = run_probe(FIX / "good_scene.py", "GoodScene")
    assert res["ok"], res
    frames = frames_from_result(res)
    assert [f.section for f in frames][0] == "b1_intro"


def test_alignment_missing_beat_and_order():
    res = run_probe_inline(FIX / "good_scene.py", "GoodScene")
    frames = frames_from_result(res)
    missing = check_alignment(_plan(("b1_intro", "b2_plot", "b3_outro", "b4_extra")), frames)
    assert any(
        f.gate == "coverage" and f.beat_id == "b4_extra" and f.severity == Severity.FATAL
        for f in missing
    )
    reordered = check_alignment(_plan(("b2_plot", "b1_intro", "b3_outro")), frames)
    assert any(f.gate == "order" for f in reordered)


def test_critique_maps_scores_and_issues(tmp_path: Path):
    img = tmp_path / "b1_intro.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    fb = FakeBackend(
        responses={
            "critique": [
                {
                    "scores": {
                        "visual_relevance": 4,
                        "element_layout": 3,
                        "logical_flow": 5,
                        "clarity": 4,
                        "plan_adherence": 4,
                    },
                    "issues": [
                        {
                            "beat_id": "b1_intro",
                            "severity": "warn",
                            "message": "title lingers",
                            "fix": "FadeOut title before b2",
                        }
                    ],
                    "summary": "fine",
                }
            ]
        }
    )
    rep = critique(fb, _plan(), [img])
    assert rep.tier == 2 and rep.ok
    assert rep.scores["logical_flow"] == 1.0
    assert rep.findings[0].fix == "FadeOut title before b2"
    assert fb.requests[0].images == [str(img)]


SOFTMAX = r"p_i = \frac{e^{z_i/T}}{\sum_j e^{z_j/T}}"


def _sourced_plan():
    p = _plan()
    p.provenance = Provenance(
        equations=[
            Equation(label="eq:softmax", latex=SOFTMAX, para_id="sec1.eq1", verbatim=True),
        ]
    )
    return p


def test_fidelity_blocks_when_a_source_equation_is_missing():
    findings = check_equation_provenance(_sourced_plan(), "from manim_engineer.kit import *\n")
    f = next(f for f in findings if f.gate == "fidelity")
    assert f.severity == Severity.FATAL and "eq:softmax" in f.message and f.fix


def test_fidelity_stays_advisory_without_a_source_ledger():
    # transcript input: the plan's equations are the model's own, so nothing blocks
    findings = check_equation_provenance(_plan(), "from manim_engineer.kit import *\n")
    assert findings and all(f.severity == Severity.INFO for f in findings)


def test_fidelity_flags_altered_source_equation_and_warns_on_extras():
    altered = r'MathTex(r"p_i = \frac{e^{z_i}}{\sum_j e^{z_j/T}}")'
    extra = r'MathTex(r"\lim_{n \to \infty} H(p) = \log n")'
    code = f"from manim_engineer.kit import *\nx = {altered}\ny = {extra}\n"
    findings = check_equation_provenance(_sourced_plan(), code)
    assert any(
        f.severity == Severity.FATAL and "alters source equation" in f.message for f in findings
    )
    assert any(f.severity == Severity.WARN and "not in the source" in f.message for f in findings)
    assert all(f.fix for f in findings)


def test_text_floor_scales_with_probe_resolution():
    from manim_engineer.verification.layout import check_keyframe
    from manim_engineer.verification.probe import Box, Keyframe

    def frame(h):
        return Keyframe(
            index=0,
            t=0.0,
            run_time=1.0,
            section="b1",
            anim="Write",
            boxes=[Box("t:Text", "Text", True, 1, -1.0, 0.0, 1.0, h, text="label text")],
        )

    ok = 0.2  # 27 px at 1080p, 18 px at 720p: passes the 24 px @1080p rule at both
    small = 0.15  # 20 px at 1080p: fails at both
    for ph in (1080, 720):
        assert not [
            f for f in check_keyframe(frame(ok), pixel_height=ph) if f.gate == "text_too_small"
        ]
        assert [
            f for f in check_keyframe(frame(small), pixel_height=ph) if f.gate == "text_too_small"
        ]
