import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from manim_engineer.cli import main
from manim_engineer.llm import FakeBackend, LLMRequest
from manim_engineer.pipeline import (
    RepairPolicy,
    RunConfig,
    RunDir,
    revise_run,
    run_live,
    run_pipeline,
)
from manim_engineer.pipeline.realize import realize_plan
from manim_engineer.planning import load_plan

MD = """# Softmax temperature

Softmax turns a vector of logits into probabilities. Dividing the logits by a temperature T before the softmax
changes how peaked the distribution is. The formula is the exponential of each logit over T divided by the sum
of exponentials, so every probability stays positive and they sum to one.

$$
p_i = \\frac{e^{z_i/T}}{\\sum_j e^{z_j/T}}
$$

Lower temperature sharpens the distribution toward the largest logit; higher temperature flattens it toward
uniform. This is the knob behind sampling diversity in language models: T near zero is greedy decoding and
T above one makes rare tokens more likely.
"""

GOOD_SCENE = """from manim_engineer.kit import *


class {cls}(Scene):
    def construct(self):
        self.next_section("{b1}")
        title = section_title("Softmax temperature")
        eq = MathTex(r"p_i = \\frac{{e^{{z_i/T}}}}{{\\sum_j e^{{z_j/T}}}}", font_size=EQ_SIZE)
        place(eq, "main_upper")
        self.play(Write(title), run_time=1.0)
        self.play(Write(eq), run_time=1.2)
        self.wait(1.0)
        self.next_section("{b2}")
        axes, graph, labels = plot_in_region(lambda x: x**2 / 9, [-3, 3, 1], [0, 1, 0.5], region="main_lower", x_label="z", y_label="p")
        self.play(Create(axes), run_time=1.0)
        self.play(Create(graph), run_time=1.0)
        cap = caption("Lower T sharpens the distribution")
        self.play(FadeIn(cap, shift=UP * 0.2), run_time=0.6)
        self.wait(1.5)
        fade_all(self)
"""

BAD_THEN_GOOD = {"n": 0}


def _backend(mode: str = "good") -> FakeBackend:
    def default(req: LLMRequest):
        if req.tag.startswith("triage"):
            return {
                "worth_animating": True,
                "salience": 5,
                "concept_name": "Softmax temperature",
                "reason": "mechanism with a formula",
                "archetype": "function_plot",
                "has_equation": True,
                "difficulty": "easy",
            }
        if req.tag.startswith("plan"):
            return {
                "concept_id": "softmax_temperature",
                "title": "Softmax temperature",
                "one_line": "T controls how peaked softmax is.",
                "claim": "Lower temperature sharpens the softmax distribution.",
                "audience_level": "undergrad",
                "archetype": "function_plot",
                "archetype_confidence": 0.9,
                "layout_template": "TOP_PERSISTENT_BOTTOM_CONTENT",
                "target_duration_s": 12,
                "equations": [
                    {"label": "softmax", "latex": r"p_i = \frac{e^{z_i/T}}{\sum_j e^{z_j/T}}"}
                ],
                "quotes": ["Lower temperature sharpens the distribution toward the largest logit"],
                "beats": [
                    {
                        "beat_id": "b1_formula",
                        "purpose": "show the formula",
                        "visuals": "equation in main_upper",
                        "narration": "Here is softmax with temperature.",
                        "duration_s": 3,
                        "wait_after_s": 1,
                    },
                    {
                        "beat_id": "b2_sweep",
                        "purpose": "sweep T",
                        "visuals": "curve in main_lower",
                        "narration": "Lower T sharpens it.",
                        "duration_s": 4,
                        "wait_after_s": 1.5,
                    },
                ],
                "priority": 0.9,
            }
        if (
            req.tag.startswith("codegen")
            or req.tag.startswith("repair")
            or req.tag.startswith("revise")
            or req.tag.startswith("visual_repair")
        ):
            cls = "SoftmaxTemperatureScene"
            code = GOOD_SCENE.format(cls=cls, b1="b1_formula", b2="b2_sweep")
            if mode == "bad_then_good" and req.tag.startswith("codegen"):
                # hallucinated API on the first try; the repair fixes it
                return (
                    "```python\n"
                    + code.replace("Create(graph)", "ShowCreation(graph)").replace(
                        'place(eq, "main_upper")', "eq.shift_right(3)"
                    )
                    + "\n```"
                )
            if req.tag.startswith("revise"):
                code = code.replace("Lower T sharpens the distribution", "REVISED caption")
            return "```python\n" + code + "\n```"
        if req.tag.startswith("critique"):
            return {
                "scores": {
                    "visual_relevance": 4,
                    "element_layout": 4,
                    "logical_flow": 4,
                    "clarity": 4,
                    "plan_adherence": 4,
                },
                "issues": [],
                "summary": "fine",
            }
        raise AssertionError(req.tag)

    return FakeBackend(default=default)


@pytest.mark.integration
def test_run_pipeline_end_to_end_with_fake_backend(tmp_path: Path, monkeypatch):
    src = tmp_path / "softmax.md"
    src.write_text(MD)
    out = tmp_path / "run"
    import manim_engineer.pipeline.run as runmod

    monkeypatch.setattr(runmod, "select_backend", lambda *a, **k: _backend())
    cfg = RunConfig(
        backend="fake",
        quality="l",
        workers=1,
        gif_width=480,
        gif_fps=10,
        critique=True,
        probe_pixel_height=480,
    )
    summary = run_pipeline(str(src), out, cfg, log=lambda *a: None)
    assert summary["plans"] == ["softmax_temperature"]
    c = summary["concepts"][0]
    assert c["status"] == "accepted", c
    assert Path(c["bundle_dir"], "manifest.json").exists()
    assert (out / "index.html").exists() and "Softmax temperature" in (
        out / "index.html"
    ).read_text()
    assert (out / "plans" / "softmax_temperature.json").exists()
    assert c["scores"]["clarity"] == 0.8
    names = [s["name"] for s in c["bundle"]["sections"]]
    assert names == ["b1_formula", "b2_sweep"]
    # revise flow
    monkeypatch.setattr(runmod, "select_backend", lambda *a, **k: _backend())
    r = revise_run(out, "softmax_temperature", "change the caption", cfg, log=lambda *a: None)
    assert r.status == "accepted"
    assert "REVISED caption" in Path(r.accepted_code).read_text()
    notes = json.loads(RunDir(out).notes.read_text())
    assert notes[0]["note"] == "change the caption"
    plan = load_plan(out / "plans" / "softmax_temperature.json")
    assert plan.meta.revision == 1 and plan.meta.revision_notes == ["change the caption"]


@pytest.mark.integration
def test_repair_loop_fixes_hallucinated_api(tmp_path: Path):
    from manim_engineer.core import AnimationPlan
    from manim_engineer.planning import Planner

    be = _backend("bad_then_good")
    plan_data = be.complete(LLMRequest(prompt="", tag="plan_x")).structured
    from manim_engineer.ingest import document_from_markdown
    from manim_engineer.planning import bucket_document

    doc = document_from_markdown(MD, source="m.md", title="t")
    bucket = bucket_document(doc)[0]
    plan: AnimationPlan = Planner(be).build_plan(plan_data, bucket, doc, None)
    cfg = RunConfig(
        quality="l",
        critique=False,
        probe_pixel_height=480,
        repair=RepairPolicy(deterministic_attempts=2),
    )
    r = realize_plan(plan, tmp_path, be, cfg, log=lambda *a: None)
    assert r.status == "accepted"
    kinds = [a["kind"] for a in [vars(a) for a in r.attempts]]
    assert kinds == ["generate", "repair"]
    first = r.attempts[0]
    assert first.tier0_ok is False and any(
        f["gate"] in ("legacy_api", "api") for f in first.findings
    )
    assert r.attempts[1].tier1_ok is True and not r.used_fallback


@pytest.mark.integration
def test_live_replay_pipeline(tmp_path: Path, monkeypatch):
    src = tmp_path / "softmax.md"
    src.write_text(MD)
    import manim_engineer.pipeline.run as runmod

    monkeypatch.setattr(runmod, "select_backend", lambda *a, **k: _backend())
    cfg = RunConfig(
        backend="fake",
        quality="l",
        workers=1,
        critique=False,
        probe_pixel_height=480,
        gif_width=320,
        gif_fps=8,
    )
    summary = run_live(str(src), tmp_path / "live", cfg, chunk=2, log=lambda *a: None)
    assert summary["mode"] == "live" and summary["concepts"]
    assert summary["concepts"][0]["status"] == "accepted"
    assert any(e["event"] == "planned" for e in summary["timeline"])


def test_cli_help_lists_commands():
    res = CliRunner().invoke(main, ["--help"])
    assert res.exit_code == 0
    for cmd in ("run", "live", "plan", "render-plan", "revise", "gallery", "run-cases", "doctor"):
        assert cmd in res.output
