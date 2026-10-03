import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from manim_engineer.cli import main
from manim_engineer.core import ArtifactBundle, SectionArtifact
from manim_engineer.llm import FakeBackend, LLMRequest
from manim_engineer.pipeline import (
    ConceptResult,
    RepairPolicy,
    RunConfig,
    RunDir,
    approve_run,
    revise_run,
    run_live,
    run_pipeline,
    unapprove_run,
)
from manim_engineer.pipeline.approval import ApprovalError, load_approvals, pin_problem
from manim_engineer.pipeline.gallery import write_run_gallery
from manim_engineer.pipeline.realize import realize_plan
from manim_engineer.planning import load_plan, save_plan

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


def _softmax_plan():
    from manim_engineer.ingest import document_from_markdown
    from manim_engineer.planning import Planner, bucket_document

    be = _backend()
    data = be.complete(LLMRequest(prompt="", tag="plan_x")).structured
    doc = document_from_markdown(MD, source="m.md", title="t")
    return Planner(be).build_plan(data, bucket_document(doc)[0], doc, None)


def _bundle(cid: str, bdir: Path) -> ArtifactBundle:
    (bdir / "sections").mkdir(parents=True, exist_ok=True)
    (bdir / "sections" / "01_b1_intro.mp4").write_bytes(b"mp4")
    return ArtifactBundle(
        plan_id=f"plan_{cid}",
        concept_id=cid,
        scene_class="Scene",
        manim_version="0.19.2",
        quality="480p15",
        width=854,
        height=480,
        fps=15.0,
        duration_s=2.0,
        master_mp4="master.mp4",
        sections=[
            SectionArtifact(
                index=1,
                name="b1_intro",
                duration_s=2.0,
                mp4="sections/01_b1_intro.mp4",
                narration=f"{cid} narration",
            )
        ],
    )


def _accepted_run(run: Path, cids: tuple[str, ...] = ("softmax_temperature",)) -> dict:
    """A run directory whose concepts were accepted by an earlier run, built without rendering."""
    rd = RunDir(run).ensure()
    concepts = []
    for cid in cids:
        plan = _softmax_plan()
        plan.concept.concept_id = cid
        plan.plan_id = f"plan_{cid}"
        save_plan(plan, rd.plans)
        code = run / "candidates" / cid / "attempt_01.py"
        code.parent.mkdir(parents=True, exist_ok=True)
        code.write_text(GOOD_SCENE.format(cls=plan.scene_class, b1="b1_formula", b2="b2_sweep"))
        bdir = run / "animations" / cid
        concepts.append(
            {
                "concept_id": cid,
                "plan_id": plan.plan_id,
                "status": "accepted",
                "accepted_code": str(code),
                "bundle_dir": str(bdir),
                "bundle": _bundle(cid, bdir).model_dump(),
                "plan": plan.model_dump(by_alias=True),
            }
        )
    summary = {
        "title": "Softmax talk",
        "source": "softmax.md",
        "plans": list(cids),
        "concepts": concepts,
    }
    rd.save_summary(summary)
    return RunDir(run).load_summary()


def _edit_first_narration(run: Path, cid: str, text: str) -> None:
    plan_path = run / "plans" / f"{cid}.json"
    data = json.loads(plan_path.read_text())
    data["beats"][0]["narration"] = text
    plan_path.write_text(json.dumps(data, indent=1))


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


def test_run_deck_holds_only_concepts_whose_approval_pin_holds(tmp_path: Path):
    run = tmp_path / "run"
    summary = _accepted_run(
        run, cids=("softmax_temperature", "temperature_sweep", "fallback_one", "broken")
    )
    by_id = {c["concept_id"]: c for c in summary["concepts"]}
    by_id["fallback_one"]["status"] = "needs_human"
    by_id["broken"].update(status="rejected", accepted_code=None, bundle=None, bundle_dir=None)
    summary["source"] = str(tmp_path / "secret-talk-notes.md")
    RunDir(run).save_summary(summary)
    for cid in ("softmax_temperature", "temperature_sweep", "fallback_one"):
        approve_run(run, cid, log=lambda *a: None)
    # an edit after approval takes the concept out of the deck and the gallery says why
    _edit_first_narration(run, "temperature_sweep", "Edited after approval.")

    write_run_gallery(run, summary)

    deck = (run / "deck.html").read_text()
    assert re.findall(r'data-concept="([^"]+)"', deck) == ["softmax_temperature", "fallback_one"]
    assert "data-needs-review" not in deck  # approval is the review
    # a local input path is never printed on a slide the audience sees
    assert "secret-talk-notes" not in deck
    gallery = (run / "index.html").read_text()
    assert 'href="deck.html"' in gallery
    assert 'class="badge approved"' in gallery
    assert "approval stale: plan changed since approval" in gallery
    assert "copyApprove('temperature_sweep')" in gallery
    assert "copyApprove('softmax_temperature')" not in gallery

    # once no pin holds, the stale deck and its link are removed
    for cid in ("softmax_temperature", "fallback_one"):
        unapprove_run(run, cid, log=lambda *a: None)
    write_run_gallery(run, summary)
    assert not (run / "deck.html").exists()
    gallery = (run / "index.html").read_text()
    assert "deck.html" not in gallery
    assert "approve a concept to build the presenter deck" in gallery
    assert "approval revoked: unapproved" in gallery


def test_cli_help_lists_commands():
    res = CliRunner().invoke(main, ["--help"])
    assert res.exit_code == 0
    for cmd in ("run", "live", "plan", "render-plan", "revise", "gallery", "run-cases", "doctor"):
        assert cmd in res.output


def test_approve_pins_the_plan_and_accepted_code(tmp_path: Path):
    run = tmp_path / "run"
    _accepted_run(run)
    pin = approve_run(
        run, "softmax_temperature", author="aryan", note="formula checked", log=lambda *a: None
    )
    stored = json.loads((run / "review" / "approvals.json").read_text())
    record = stored["approved"]["softmax_temperature"]
    assert record["pin"] == pin.pin and len(pin.pin) == 64
    assert record["accepted_code"] == "candidates/softmax_temperature/attempt_01.py"
    assert record["author"] == "aryan" and record["note"] == "formula checked"
    assert record["approved_at"].endswith("Z")
    entry = RunDir(run).load_summary()["concepts"][0]
    assert pin_problem(run, pin, entry) is None


def test_pin_breaks_with_a_reason_when_the_plan_changes(tmp_path: Path):
    run = tmp_path / "run"
    _accepted_run(run)
    pin = approve_run(run, "softmax_temperature", log=lambda *a: None)
    entry = RunDir(run).load_summary()["concepts"][0]
    plan_path = run / "plans" / "softmax_temperature.json"
    # reformatting is not an edit
    plan_path.write_text(json.dumps(json.loads(plan_path.read_text()), indent=4, sort_keys=True))
    assert pin_problem(run, pin, entry) is None
    _edit_first_narration(run, "softmax_temperature", "Start from the logits.")
    assert pin_problem(run, pin, entry) == "plan changed since approval"


def test_pin_breaks_with_a_reason_when_the_accepted_code_changes(tmp_path: Path):
    run = tmp_path / "run"
    _accepted_run(run)
    pin = approve_run(run, "softmax_temperature", log=lambda *a: None)
    entry = RunDir(run).load_summary()["concepts"][0]
    code = run / "candidates" / "softmax_temperature" / "attempt_01.py"
    replaced = dict(entry, accepted_code=str(code.with_name("attempt_02.py")))
    assert pin_problem(run, pin, replaced) == (
        "accepted animation replaced: candidates/softmax_temperature/attempt_01.py"
        " → candidates/softmax_temperature/attempt_02.py"
    )
    code.write_text(code.read_text() + "\n# touched\n")
    assert pin_problem(run, pin, entry) == "accepted code changed since approval"


def test_approve_refuses_a_concept_without_an_accepted_animation(tmp_path: Path):
    run = tmp_path / "run"
    summary = _accepted_run(run)
    summary["concepts"][0].update(status="rejected", accepted_code=None, bundle=None)
    RunDir(run).save_summary(summary)
    with pytest.raises(ApprovalError, match="no accepted animation to approve"):
        approve_run(run, "softmax_temperature", log=lambda *a: None)
    assert not (run / "review" / "approvals.json").exists()


def test_approve_refuses_when_the_plan_changed_after_rendering(tmp_path: Path):
    run = tmp_path / "run"
    _accepted_run(run)
    _edit_first_narration(run, "softmax_temperature", "Start from the logits.")
    with pytest.raises(ApprovalError, match="changed after this animation was rendered"):
        approve_run(run, "softmax_temperature", log=lambda *a: None)


def test_unapprove_records_who_revoked_the_pin(tmp_path: Path):
    run = tmp_path / "run"
    _accepted_run(run)
    approve_run(run, "softmax_temperature", log=lambda *a: None)
    unapprove_run(run, "softmax_temperature", author="aryan", log=lambda *a: None)
    approvals = load_approvals(run)
    assert approvals.approved == {}
    assert approvals.revoked[0].revoked_reason == "unapproved by aryan"
    with pytest.raises(ApprovalError, match="is not approved"):
        unapprove_run(run, "softmax_temperature", log=lambda *a: None)


def test_cli_approve_and_unapprove(tmp_path: Path):
    run = tmp_path / "run"
    _accepted_run(run)
    runner = CliRunner()
    res = runner.invoke(main, ["approve", str(run), "softmax_temperature", "--author", "aryan"])
    assert res.exit_code == 0, res.output
    assert "softmax_temperature: approved (pin " in res.output
    res = runner.invoke(main, ["approve", str(run), "nope"])
    assert res.exit_code != 0 and "nope is not a concept" in res.output
    res = runner.invoke(main, ["unapprove", str(run), "softmax_temperature"])
    assert res.exit_code == 0, res.output
    assert "softmax_temperature: unapproved" in res.output


def _rerun(tmp_path: Path, monkeypatch, run: Path):
    """Run the softmax source again into `run`, with planning faked and realization recorded."""
    import manim_engineer.pipeline.run as runmod

    src = tmp_path / "softmax.md"
    src.write_text(MD)
    realized: list[tuple[str, str]] = []

    def fake_realize(plan, run_dir, backend, cfg, log=print):
        realized.append((plan.concept.concept_id, plan.beats[0].narration))
        return ConceptResult(
            concept_id=plan.concept.concept_id,
            plan_id=plan.plan_id,
            status="rejected",
            message="not rendered in this test",
        )

    monkeypatch.setattr(runmod, "select_backend", lambda *a, **k: _backend())
    monkeypatch.setattr(runmod, "realize_plan", fake_realize)
    logs: list[str] = []
    cfg = RunConfig(backend="fake", workers=1, critique=False)
    summary = run_pipeline(str(src), run, cfg, log=logs.append)
    return summary, realized, logs


def test_rerun_skips_an_approved_concept_and_says_so(tmp_path: Path, monkeypatch):
    run = tmp_path / "run"
    _accepted_run(run)
    pin = approve_run(run, "softmax_temperature", log=lambda *a: None)
    plan_before = (run / "plans" / "softmax_temperature.json").read_text()

    summary, realized, logs = _rerun(tmp_path, monkeypatch, run)

    assert realized == []
    assert (
        f"[approval] softmax_temperature: approved {pin.approved_at} (pin {pin.pin[:12]}); skipped"
        in logs
    )
    assert summary["plans"] == ["softmax_temperature"]
    c = summary["concepts"][0]
    assert c["status"] == "accepted" and c["accepted_code"].endswith("attempt_01.py")
    assert (run / "plans" / "softmax_temperature.json").read_text() == plan_before
    assert pin_problem(run, load_approvals(run).approved["softmax_temperature"], c) is None


def test_rerun_revokes_an_edited_plan_and_renders_the_edit(tmp_path: Path, monkeypatch):
    run = tmp_path / "run"
    _accepted_run(run)
    approve_run(run, "softmax_temperature", log=lambda *a: None)
    _edit_first_narration(run, "softmax_temperature", "Start from the logits.")

    summary, realized, logs = _rerun(tmp_path, monkeypatch, run)

    assert "[approval] softmax_temperature: approval revoked: plan changed since approval" in logs
    assert (
        "[approval] softmax_temperature: re-rendering from plans/softmax_temperature.json" in logs
    )
    assert realized == [("softmax_temperature", "Start from the logits.")]
    approvals = load_approvals(run)
    assert approvals.approved == {}
    assert approvals.revoked[0].revoked_reason == "plan changed since approval"
    plan = load_plan(run / "plans" / "softmax_temperature.json")
    assert plan.beats[0].narration == "Start from the logits."


def test_rerun_keeps_approved_concepts_the_planner_did_not_return(tmp_path: Path, monkeypatch):
    run = tmp_path / "run"
    _accepted_run(run, cids=("softmax_temperature", "temperature_sweep"))
    for cid in ("softmax_temperature", "temperature_sweep"):
        approve_run(run, cid, log=lambda *a: None)

    summary, realized, logs = _rerun(tmp_path, monkeypatch, run)

    assert realized == []
    assert "[approval] temperature_sweep: kept although this run did not plan it" in logs
    assert [c["concept_id"] for c in summary["concepts"]] == [
        "softmax_temperature",
        "temperature_sweep",
    ]


def test_run_json_keeps_approved_concepts_when_realization_crashes(tmp_path: Path, monkeypatch):
    import manim_engineer.pipeline.run as runmod

    run = tmp_path / "run"
    _accepted_run(run, cids=("softmax_temperature", "temperature_sweep"))
    approve_run(run, "temperature_sweep", log=lambda *a: None)
    src = tmp_path / "softmax.md"
    src.write_text(MD)

    def crash(*a, **k):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(runmod, "select_backend", lambda *a, **k: _backend())
    monkeypatch.setattr(runmod, "realize_all", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_pipeline(str(src), run, RunConfig(backend="fake", workers=1), log=lambda *a: None)

    summary = RunDir(run).load_summary()
    assert [c["concept_id"] for c in summary["concepts"]] == ["temperature_sweep"]
    pin = load_approvals(run).approved["temperature_sweep"]
    assert pin_problem(run, pin, summary["concepts"][0]) is None


def test_live_replay_refuses_a_run_with_approved_concepts(tmp_path: Path):
    run = tmp_path / "run"
    _accepted_run(run)
    approve_run(run, "softmax_temperature", log=lambda *a: None)
    src = tmp_path / "softmax.md"
    src.write_text(MD)
    with pytest.raises(ApprovalError, match="live replay would overwrite them"):
        run_live(str(src), run, RunConfig(backend="fake", workers=1), log=lambda *a: None)
    res = CliRunner().invoke(main, ["live", str(src), "--out", str(run), "--backend", "fake"])
    assert res.exit_code != 0 and "live replay would overwrite them" in res.output


@pytest.mark.integration
def test_approved_concept_survives_a_real_rerun(tmp_path: Path, monkeypatch):
    import manim_engineer.pipeline.run as runmod

    src = tmp_path / "softmax.md"
    src.write_text(MD)
    out = tmp_path / "run"
    monkeypatch.setattr(runmod, "select_backend", lambda *a, **k: _backend())
    cfg = RunConfig(
        backend="fake",
        quality="l",
        workers=1,
        gif_width=320,
        gif_fps=8,
        critique=False,
        probe_pixel_height=480,
    )
    first = run_pipeline(str(src), out, cfg, log=lambda *a: None)
    assert first["concepts"][0]["status"] == "accepted", first["concepts"][0]
    res = CliRunner().invoke(main, ["approve", str(out), "softmax_temperature"])
    assert res.exit_code == 0, res.output
    manifest = Path(first["concepts"][0]["bundle_dir"], "manifest.json")
    stamp = manifest.stat().st_mtime_ns

    logs: list[str] = []
    second = run_pipeline(str(src), out, cfg, log=logs.append)

    assert manifest.stat().st_mtime_ns == stamp
    assert any(
        line.startswith("[approval] softmax_temperature: approved") and line.endswith("skipped")
        for line in logs
    )
    assert second["concepts"][0]["accepted_code"] == first["concepts"][0]["accepted_code"]
