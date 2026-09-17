import json

import pytest
from pydantic import ValidationError

from manim_engineer.core import (
    AnimationPlan,
    Archetype,
    ArchetypeChoice,
    Beat,
    Budgets,
    Concept,
    Equation,
    Finding,
    Modality,
    Severity,
    SourceSpan,
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
