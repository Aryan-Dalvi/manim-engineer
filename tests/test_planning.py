from manim_engineer.core import Document, Modality, Segment, SegmentKind, SourceSpan
from manim_engineer.ingest import document_from_markdown
from manim_engineer.llm import FakeBackend, LLMRequest
from manim_engineer.planning import (
    Bucketer,
    LiveReplay,
    MaturityConfig,
    Planner,
    PlannerConfig,
    bucket_document,
    plan_document,
    save_plan,
    slugify,
)

TOPIC_A = (
    "The attention score is the dot product of the query and the key vectors, scaled by the square root of the key dimension. "
    "Softmax over those scores gives the attention weights, and the weights multiply the value vectors. "
    "So attention is a weighted average of values where the weights come from query key similarity."
)
TOPIC_B = (
    "Gradient descent updates the parameters by stepping against the gradient of the loss. "
    "The learning rate scales each step; too large and the loss diverges, too small and convergence is slow. "
    "Momentum accumulates past gradients so the optimizer keeps moving through flat regions of the loss surface."
)


def _speech_doc(paragraphs: list[str], per_sentence: bool = True) -> Document:
    segs = []
    t = 0.0
    for p in paragraphs:
        pieces = [s.strip() + "." for s in p.split(". ") if s.strip()] if per_sentence else [p]
        for s in pieces:
            segs.append(
                Segment(
                    seg_id=f"s{len(segs):04d}",
                    text=s,
                    span=SourceSpan(
                        modality=Modality.TRANSCRIPT, doc_id="d", t_start_s=t, t_end_s=t + 5
                    ),
                )
            )
            t += 5
    return Document(
        doc_id="d", title="Talk", modality=Modality.TRANSCRIPT, source="x", segments=segs
    )


def test_bucketer_splits_two_topics_and_flushes():
    doc = _speech_doc([TOPIC_A, TOPIC_A, TOPIC_B, TOPIC_B])
    buckets = bucket_document(doc, MaturityConfig(min_words=40, stale_ticks=3))
    assert len(buckets) >= 2
    texts = [b.text for b in buckets]
    assert "attention" in texts[0].lower() and "gradient" in texts[-1].lower()
    # every segment lands in exactly one bucket
    ids = [s.seg_id for b in buckets for s in b.segments]
    assert len(ids) == len(set(ids)) == len(doc.segments)  # nothing dropped for dense content


def test_headings_and_slide_changes_are_boundaries():
    md = "# A\n\n" + TOPIC_A + "\n\n# B\n\n" + TOPIC_B
    doc = document_from_markdown(md, source="m.md", title="t")
    buckets = bucket_document(doc, MaturityConfig(min_words=20))
    assert [b.heading for b in buckets] == ["A", "B"]
    slides = Document(
        doc_id="s",
        title="deck",
        modality=Modality.SLIDES,
        source="x",
        segments=[
            Segment(
                seg_id=f"s{i}",
                text=TOPIC_A if i < 2 else TOPIC_B,
                kind=SegmentKind.SLIDE_TEXT,
                span=SourceSpan(modality=Modality.SLIDES, doc_id="s", slide_index=i + 1),
            )
            for i in range(4)
        ],
    )
    bs = bucket_document(slides, MaturityConfig(min_words=20))
    # slides 2 and 4 repeat slides 1 and 3 verbatim: deduplicated, so two buckets survive
    assert len(bs) == 2 and bs[0].span_label() == "slide 1" and bs[1].span_label() == "slide 3"


def test_staleness_and_dedup():
    bk = Bucketer(MaturityConfig(min_words=10, stale_ticks=2))
    doc = _speech_doc([TOPIC_A], per_sentence=False)
    bk.absorb(doc.segments[0])
    assert not bk.sweep()  # still open, not stale
    for i in range(3):
        bk.absorb(
            Segment(
                seg_id=f"x{i}",
                text="Anyway let us move on to logistics and the schedule for lunch.",
                span=SourceSpan(
                    modality=Modality.TRANSCRIPT, doc_id="d", t_start_s=100 + i, t_end_s=101 + i
                ),
            )
        )
    mature = bk.sweep()
    assert [b.segments[0].seg_id for b in mature] == ["s0000"]
    # repeat of the same concept is a duplicate
    bk.absorb(
        Segment(
            seg_id="dup",
            text=TOPIC_A,
            span=SourceSpan(modality=Modality.TRANSCRIPT, doc_id="d", t_start_s=200, t_end_s=205),
        )
    )
    flushed = bk.flush()
    assert (
        all("duplicate" in bk.verdict(b, force=True).reasons or b.words < 10 for b in flushed)
        or not flushed
    )


def _fake_backend():
    def default(req: LLMRequest):
        if req.tag.startswith("triage"):
            worth = "attention" in req.prompt.lower()
            return {
                "worth_animating": worth,
                "salience": 5 if worth else 1,
                "concept_name": "Scaled dot-product attention" if worth else "logistics",
                "reason": "mechanism" if worth else "filler",
                "archetype": "equation_derivation",
                "has_equation": True,
                "difficulty": "medium",
            }
        if req.tag.startswith("plan"):
            return {
                "concept_id": "Scaled Dot Product Attention!",
                "title": "Scaled dot-product attention",
                "one_line": "Weights come from query-key similarity.",
                "claim": "Attention is a softmax-weighted average of values.",
                "audience_level": "undergrad",
                "archetype": "equation_derivation",
                "secondary_archetype": "flow_diagram",
                "archetype_confidence": 0.9,
                "layout_template": "TOP_PERSISTENT_BOTTOM_CONTENT",
                "target_duration_s": 20,
                "symbol_ledger": [
                    {"symbol": "Q", "latex": "Q", "meaning": "queries", "color": "#58C4DD"}
                ],
                "equations": [{"label": "attn", "latex": r"\mathrm{softmax}(QK^T/\sqrt{d_k})V"}],
                "quotes": [
                    "The attention score is the dot product of the query and the key vectors."
                ],
                "beats": [
                    {
                        "beat_id": "b1_setup",
                        "purpose": "show Q K",
                        "visuals": "Q and K in main_upper",
                        "narration": "Queries and keys.",
                        "duration_s": 4,
                        "wait_after_s": 1,
                    },
                    {
                        "beat_id": "intro",
                        "purpose": "scores",
                        "visuals": "dot products",
                        "narration": "Dot products.",
                        "duration_s": 5,
                        "wait_after_s": 1,
                    },
                    {
                        "beat_id": "b3_softmax",
                        "purpose": "softmax",
                        "visuals": "bars",
                        "narration": "Softmax.",
                        "duration_s": 5,
                        "wait_after_s": 1,
                    },
                ],
                "priority": 0.9,
            }
        raise AssertionError(req.tag)

    return FakeBackend(default=default)


def test_planner_builds_valid_plan_and_normalizes_ids(tmp_path):
    doc = _speech_doc([TOPIC_A, TOPIC_A, TOPIC_B])
    plans, skipped = plan_document(
        doc, _fake_backend(), PlannerConfig(audience="undergrad"), MaturityConfig(min_words=40)
    )
    assert len(plans) == 1 and skipped
    p = plans[0]
    assert p.concept.concept_id == "scaled_dot_product_attention"
    assert [b.beat_id for b in p.beats] == ["b1_setup", "b2_intro", "b3_softmax"]
    assert p.provenance.equations[0].label == "attn"
    assert p.provenance.source_spans and p.provenance.quotes
    assert p.archetype.secondary is not None and p.symbol_ledger[0].color == "#58C4DD"
    assert p.scene_class == "ScaledDotProductAttentionScene"
    path = save_plan(p, tmp_path)
    assert path.exists() and (tmp_path / "scaled_dot_product_attention.md").exists()


def test_live_replay_processes_each_segment_once_and_emits_plan():
    doc = _speech_doc([TOPIC_A, TOPIC_A, TOPIC_B, TOPIC_B])
    live = LiveReplay(
        Planner(_fake_backend(), PlannerConfig()), doc, MaturityConfig(min_words=40, stale_ticks=3)
    )
    events = list(live.feed(doc.segments[:4]))
    events += list(live.feed(doc.segments))  # re-feeding earlier segments is a no-op
    events += list(live.finish())
    kinds = [e.kind for e in events]
    assert kinds.count("absorbed") == len(doc.segments)
    assert "planned" in kinds and len(live.state.plans) == 1
    assert live.state.watermark == len(doc.segments)


def test_slugify():
    assert slugify("Why attention divides by √d_k") == "why_attention_divides_by_d_k"
    assert slugify("123 go") == "c_123_go"
