from pathlib import Path

from manim_engineer.core import (
    AnimationPlan,
    Archetype,
    ArchetypeChoice,
    Beat,
    Candidate,
    Concept,
    Equation,
    Finding,
    Provenance,
    Severity,
    SymbolEntry,
)
from manim_engineer.generation import (
    apply_source_preamble,
    codegen_prompt,
    extract_code,
    fallback_scene,
    generate,
    knowledge_for,
    normalize,
    repair,
    repair_prompt,
    system_prompt,
)
from manim_engineer.llm import FakeBackend
from manim_engineer.verification import verify_tier0, verify_tier1


def _plan() -> AnimationPlan:
    return AnimationPlan(
        plan_id="plan_attn",
        concept=Concept(
            concept_id="scaled_attention",
            title="Scaled attention",
            one_line="x",
            claim="Scaling keeps softmax soft.",
            takeaway="Divide by sqrt(d_k).",
        ),
        archetype=ArchetypeChoice(
            primary=Archetype.EQUATION_DERIVATION, secondary=Archetype.FLOW_DIAGRAM
        ),
        provenance=Provenance(
            equations=[
                Equation(
                    label="attn", latex=r"\mathrm{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V"
                )
            ]
        ),
        symbol_ledger=[SymbolEntry(symbol="Q", latex="Q", meaning="queries", color="#58C4DD")],
        beats=[
            Beat(
                beat_id="b1_setup",
                purpose="Show Q and K",
                narration="Queries and keys arrive.",
                duration_s=4,
            ),
            Beat(
                beat_id="b2_scale",
                purpose="Divide by sqrt d_k",
                narration="We scale the dot products.",
                duration_s=5,
            ),
        ],
    )


def test_knowledge_pack_is_archetype_specific_and_bounded():
    eq = knowledge_for(Archetype.EQUATION_DERIVATION, None, "ml")
    plot = knowledge_for(Archetype.FUNCTION_PLOT)
    assert "kit-reference.md" in eq and "manimce-0.19-pitfalls.md" in eq
    assert "rules/equations.md" in eq and "rules/equations.md" not in plot
    assert "rules/graphs-plots.md" in plot
    assert "domains/machine-learning.md" in eq
    assert len(eq) <= 60000


def test_system_and_repair_prompts_carry_rules_ledger_and_fixes():
    p = _plan()
    sysm = system_prompt(p.scene_class, knowledge_for(p.archetype.primary))
    assert "ScaledAttentionScene(Scene)" in sysm and "next_section" in sysm
    f = Finding(
        gate="overlap",
        severity=Severity.FATAL,
        message="A and B overlap",
        fix="move B down 0.6",
        beat_id="b2_scale",
    )
    rp = repair_prompt(p, "code here", [f], notes="tb")
    assert (
        "move B down 0.6" in rp and "b2_scale" in rp and "Q = queries" in rp and r"\sqrt{d_k}" in rp
    )


def test_extract_and_normalize():
    p = _plan()
    text = "Sure:\n```python\nfrom manim import *\nconfig.frame_rate = 5\nclass Foo(Scene):\n    def construct(self):\n        self.play(ShowCreation(Square()))\n```"
    code = normalize(extract_code(text), p)
    assert code.startswith("from manim_engineer.kit import *")
    assert "from manim import *" not in code and "config.frame_rate" not in code
    assert "class ScaledAttentionScene(Scene)" in code and "Create(Square())" in code


def test_generate_and_repair_through_fake_backend():
    p = _plan()
    fb = FakeBackend(
        default=lambda r: "```python\nclass X(Scene):\n    def construct(self):\n        pass\n```"
    )
    g = generate(p, fb)
    assert "ScaledAttentionScene" in g.code and fb.requests[0].tier == "strong"
    assert "Scaled attention" in fb.requests[0].prompt
    r = repair(
        p,
        g.code,
        [Finding(gate="api", severity=Severity.FATAL, message="bad", fix="use Create")],
        fb,
    )
    assert "use Create" in fb.requests[1].prompt and r.code.startswith("from manim_engineer.kit")


def test_fallback_scene_passes_deterministic_gates(tmp_path: Path):
    p = _plan()
    code = fallback_scene(p)
    path = tmp_path / "fallback.py"
    path.write_text(code)
    cand = Candidate(plan_id=p.plan_id, attempt=1, code_path=str(path), scene_class=p.scene_class)
    t0 = verify_tier0(cand, p)
    assert t0.ok, [f.one_line() for f in t0.findings]
    t1 = verify_tier1(cand, p, inline=True)
    assert t1.ok, [f.one_line() for f in t1.findings]
    assert not [f for f in t1.findings if f.gate == "coverage"]


KL_DEFINITION = "\\newcommand{\\KL}[2]{\n  D_{\\mathrm{KL}}(#1 \\| #2)\n}"
KL_SCENE = (
    "from manim_engineer.kit import *\n\n\n"
    "class ScaledAttentionScene(Scene):\n"
    "    def construct(self):\n"
    '        self.add(MathTex(r"\\KL{p}{q} \\coloneqq \\R"))\n'
)


def _paper_plan() -> AnimationPlan:
    p = _plan()
    p.provenance = Provenance(
        packages=["mathtools"],
        macros="\n".join(
            [r"\newcommand{\R}{\mathbb{R}}", KL_DEFINITION, r"\newcommand{\unused}{u}"]
        ),
    )
    return p


def _header(code: str) -> str:
    return code.split("class ")[0]


def test_normalize_writes_the_source_preamble_the_scene_uses():
    code = normalize(KL_SCENE, _paper_plan())
    assert code.startswith("from manim_engineer.kit import *\n")
    header = _header(code)
    assert "use_source_preamble(" in header and "'mathtools'" in header
    assert r"\newcommand{\R}{\mathbb{R}}" in header and r"D_{\mathrm{KL}}" in header
    assert r"\unused" not in header
    compile(code, "scene.py", "exec")


def test_normalize_replaces_a_header_the_model_edited():
    first = normalize(KL_SCENE, _paper_plan())
    edited = first.replace("'mathtools'", "'bm'").replace(r"D_{\mathrm{KL}}", r"\input{x}")
    assert normalize(edited, _paper_plan()) == first


def test_plans_without_a_source_preamble_get_no_header():
    assert apply_source_preamble(KL_SCENE, _plan()) == KL_SCENE
    assert "use_source_preamble" not in normalize(KL_SCENE, _plan())


def test_fallback_scene_carries_the_source_preamble(tmp_path: Path):
    p = _paper_plan()
    p.provenance.equations = [Equation(label="kl", latex=r"\KL{p}{q} \coloneqq 0", verbatim=True)]
    code = fallback_scene(p)
    assert "use_source_preamble(" in _header(code) and r"D_{\mathrm{KL}}" in _header(code)
    path = tmp_path / "fallback.py"
    path.write_text(code)
    cand = Candidate(plan_id=p.plan_id, attempt=1, code_path=str(path), scene_class=p.scene_class)
    t0 = verify_tier0(cand, p)
    assert t0.ok, [f.one_line() for f in t0.findings]


def test_prompts_explain_the_source_preamble_only_when_there_is_one():
    assert "use_source_preamble" in codegen_prompt(_paper_plan())
    assert "use_source_preamble" not in codegen_prompt(_plan())
