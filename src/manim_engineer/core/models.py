"""Domain models shared by every bounded context.

Pure data: no Manim, no vendor SDKs, no I/O. Everything here round-trips through
JSON so plans, findings and manifests can live on disk and be edited by hand.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "1.1"

# --------------------------------------------------------------------------- enums


class Modality(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"
    SLIDES = "slides"
    MANUSCRIPT = "manuscript"
    TRANSCRIPT = "transcript"
    LIVE = "live"


class SegmentKind(StrEnum):
    SPEECH = "speech"
    SLIDE_TEXT = "slide_text"
    SLIDE_NOTES = "slide_notes"
    BODY = "body"
    HEADING = "heading"
    EQUATION = "equation"
    CAPTION = "caption"
    CODE = "code"


class Archetype(StrEnum):
    """Visual families. Reliability notes live in docs/research/ingestion-planning.md §4."""

    EQUATION_DERIVATION = "equation_derivation"
    FUNCTION_PLOT = "function_plot"
    GEOMETRIC = "geometric"
    FLOW_DIAGRAM = "flow_diagram"
    TENSOR_FLOW = "tensor_flow"
    MEMORY_LAYOUT = "memory_layout"
    TIMELINE = "timeline"
    COMPARISON_TABLE = "comparison_table"
    ALGORITHM_TRACE = "algorithm_trace"
    GRAPH_NETWORK = "graph_network"
    MATRIX_TRANSFORM = "matrix_transform"
    DISTRIBUTION = "distribution"
    NUMBER_LINE = "number_line"
    SETS = "sets"
    SURFACE_3D = "surface_3d"


class AudienceLevel(StrEnum):
    K12 = "k12"
    UNDERGRAD = "undergrad"
    GRAD = "grad"
    EXPERT = "expert"
    MIXED = "mixed"


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    FATAL = "fatal"


class PlanStatus(StrEnum):
    PLANNED = "planned"
    CODING = "coding"
    VERIFYING = "verifying"
    ACCEPTED = "accepted"
    NEEDS_HUMAN = "needs_human"
    REJECTED = "rejected"


# --------------------------------------------------------------------------- ingestion


class SourceSpan(BaseModel):
    """Where content came from. Exactly one locator group must be populated."""

    modality: Modality
    doc_id: str
    t_start_s: float | None = None
    t_end_s: float | None = None
    slide_index: int | None = None
    shape_ids: list[str] | None = None
    para_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    @model_validator(mode="after")
    def _exactly_one_locator(self) -> SourceSpan:
        groups = [
            self.t_start_s is not None or self.t_end_s is not None,
            self.slide_index is not None,
            self.para_id is not None,
        ]
        if sum(groups) != 1:
            raise ValueError("SourceSpan needs exactly one of time range, slide_index, para_id")
        if (
            self.t_start_s is not None
            and self.t_end_s is not None
            and self.t_end_s < self.t_start_s
        ):
            raise ValueError("t_end_s must be >= t_start_s")
        return self

    def label(self) -> str:
        if self.slide_index is not None:
            return f"slide {self.slide_index}"
        if self.para_id is not None:
            return f"{self.para_id}"
        return f"{_fmt_t(self.t_start_s)}–{_fmt_t(self.t_end_s)}"


def _fmt_t(t: float | None) -> str:
    if t is None:
        return "?"
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


class Segment(BaseModel):
    seg_id: str
    text: str
    span: SourceSpan
    kind: SegmentKind = SegmentKind.SPEECH
    speaker: str | None = None
    confidence: float = 1.0
    assets: list[str] = Field(default_factory=list)
    latex: str | None = None  # populated for EQUATION segments


class Document(BaseModel):
    doc_id: str
    title: str
    modality: Modality
    source: str
    segments: list[Segment]
    assets: dict[str, str] = Field(default_factory=dict)  # asset id -> path
    meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.segments)

    def equations(self) -> list[Segment]:
        return [s for s in self.segments if s.kind == SegmentKind.EQUATION]


# --------------------------------------------------------------------------- plans


class Concept(BaseModel):
    concept_id: str
    title: str = Field(max_length=80)
    one_line: str
    claim: str
    evidence: str = ""
    takeaway: str = ""
    prerequisites: list[str] = Field(default_factory=list)

    @field_validator("concept_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]{1,60}", v):
            raise ValueError("concept_id must be a lowercase slug")
        return v


class Equation(BaseModel):
    label: str
    latex: str
    para_id: str = ""
    env: str = ""
    # True only when read from the source document. The fidelity gate blocks on
    # these and stays advisory for equations the model supplied itself.
    verbatim: bool = False


class Provenance(BaseModel):
    source_spans: list[SourceSpan] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    equations: list[Equation] = Field(default_factory=list)
    segment_ids: list[str] = Field(default_factory=list)
    macros: str = ""  # source \newcommand definitions the equations depend on


class Audience(BaseModel):
    level: AudienceLevel = AudienceLevel.MIXED
    assumed_known: list[str] = Field(default_factory=list)
    jargon_policy: Literal["avoid", "define_on_first_use", "assume"] = "define_on_first_use"


class ArchetypeChoice(BaseModel):
    primary: Archetype
    secondary: Archetype | None = None
    confidence: float = Field(ge=0, le=1, default=0.5)
    rejected: list[dict[str, str]] = Field(default_factory=list)


class Budgets(BaseModel):
    target_duration_s: float = Field(default=20, ge=3, le=90)
    max_beats: int = Field(default=6, ge=1, le=12)
    on_screen_text_chars: int = Field(default=180, ge=20, le=600)
    max_concurrent_mobjects: int = Field(default=12, ge=1, le=40)
    max_simultaneous_animations: int = Field(default=3, ge=1, le=6)
    allow_3d: bool = False
    allow_external_assets: bool = False


class LayoutRegion(BaseModel):
    name: str
    role: Literal["persistent_header", "primary", "secondary", "annotation", "footer"]
    # normalized 0..1 box in frame coordinates, origin top-left
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class Layout(BaseModel):
    template: Literal[
        "FULL_CENTER", "DUAL_PANEL", "TOP_PERSISTENT_BOTTOM_CONTENT", "BUILD_UP", "CHART_FOCUS"
    ] = "TOP_PERSISTENT_BOTTOM_CONTENT"
    regions: list[LayoutRegion] = Field(default_factory=list)
    safe_margin_units: float = 0.5
    min_gap_units: float = 0.3


class SymbolEntry(BaseModel):
    symbol: str
    latex: str
    meaning: str
    color: str | None = None
    first_beat: str | None = None


class ElementSpec(BaseModel):
    ref: str
    kind: str  # MathTex | Text | Axes | flow_diagram | ... (kit builder or Manim class)
    content: str = ""
    region: str = "primary"
    scale: float = 1.0
    params: dict[str, Any] = Field(default_factory=dict)


class TransformSpec(BaseModel):
    from_ref: str = Field(alias="from")
    to_ref: str = Field(alias="to")
    how: str = "ReplacementTransform"
    key_map: dict[str, str] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class EmphasisSpec(BaseModel):
    ref: str
    how: str = "Indicate"
    target_part: str | None = None


class Beat(BaseModel):
    beat_id: str
    purpose: str
    visuals: str = ""  # prose description of what is on screen and what moves
    appears: list[ElementSpec] = Field(default_factory=list)
    transforms: list[TransformSpec] = Field(default_factory=list)
    disappears: list[str] = Field(default_factory=list)
    emphasis: list[EmphasisSpec] = Field(default_factory=list)
    narration: str = ""
    duration_s: float = Field(default=4, ge=0.5, le=30)
    wait_after_s: float = Field(default=0.5, ge=0, le=5)

    @field_validator("beat_id")
    @classmethod
    def _beat_slug(cls, v: str) -> str:
        if not re.fullmatch(r"b\d{1,2}_[a-z0-9_]{1,40}", v):
            raise ValueError("beat_id must look like b1_intro (b<n>_<slug>)")
        return v


class AssetSpec(BaseModel):
    asset_id: str
    kind: Literal["image", "svg"] = "image"
    source: str
    local_path: str | None = None
    required: bool = False


class Style(BaseModel):
    theme: Literal["dark", "light"] = "dark"
    palette: dict[str, str] = Field(default_factory=dict)
    font_scale: float = 1.0
    pacing: Literal["brisk", "measured", "slow"] = "measured"
    camera: Literal["static", "pan", "zoom"] = "static"


class ReviewCriterion(BaseModel):
    id: str
    check: Literal["automatic", "vlm", "human"]
    assert_: str = Field(alias="assert")

    model_config = {"populate_by_name": True}


class ReviewSpec(BaseModel):
    success_criteria: list[ReviewCriterion] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    max_repair_rounds: int = Field(default=3, ge=0, le=6)


class PlanMeta(BaseModel):
    created_at: str = ""
    planner_model: str = ""
    priority: float = Field(default=0.5, ge=0, le=1)
    status: PlanStatus = PlanStatus.PLANNED
    revision: int = 0
    revision_notes: list[str] = Field(default_factory=list)


class AnimationPlan(BaseModel):
    """The central artifact. See ADR 0003."""

    schema_version: str = SCHEMA_VERSION
    plan_id: str
    concept: Concept
    provenance: Provenance = Field(default_factory=Provenance)
    audience: Audience = Field(default_factory=Audience)
    archetype: ArchetypeChoice
    budgets: Budgets = Field(default_factory=Budgets)
    layout: Layout = Field(default_factory=Layout)
    symbol_ledger: list[SymbolEntry] = Field(default_factory=list)
    beats: list[Beat]
    assets: list[AssetSpec] = Field(default_factory=list)
    style: Style = Field(default_factory=Style)
    review: ReviewSpec = Field(default_factory=ReviewSpec)
    meta: PlanMeta = Field(default_factory=PlanMeta)

    @model_validator(mode="after")
    def _consistency(self) -> AnimationPlan:
        ids = [b.beat_id for b in self.beats]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate beat ids: {ids}")
        if not self.beats:
            raise ValueError("a plan needs at least one beat")
        if len(self.beats) > self.budgets.max_beats:
            raise ValueError(f"{len(self.beats)} beats exceed max_beats={self.budgets.max_beats}")
        total = sum(b.duration_s + b.wait_after_s for b in self.beats)
        if total > self.budgets.target_duration_s * 1.6:
            raise ValueError(
                f"beats total {total:.1f}s exceeds 1.6x target_duration_s={self.budgets.target_duration_s}"
            )
        if self.archetype.primary == Archetype.SURFACE_3D and not self.budgets.allow_3d:
            raise ValueError("surface_3d archetype requires budgets.allow_3d")
        return self

    @property
    def total_duration_s(self) -> float:
        return sum(b.duration_s + b.wait_after_s for b in self.beats)

    @property
    def scene_class(self) -> str:
        parts = re.split(r"[^a-zA-Z0-9]+", self.concept.concept_id)
        return "".join(p.capitalize() for p in parts if p) + "Scene"

    def fingerprint(self) -> str:
        text = " ".join([self.concept.title, self.concept.one_line, self.concept.claim]).lower()
        return hashlib.sha1(text.encode()).hexdigest()[:12]

    def to_markdown(self) -> str:
        c = self.concept
        lines = [
            f"# {c.title}",
            "",
            f"**{c.one_line}**",
            "",
            f"- Concept id: `{c.concept_id}`",
            f"- Archetype: {self.archetype.primary}"
            + (f" (+{self.archetype.secondary})" if self.archetype.secondary else "")
            + f", confidence {self.archetype.confidence:.2f}",
            f"- Audience: {self.audience.level}",
            f"- Target duration: {self.budgets.target_duration_s:.0f} s "
            f"(planned {self.total_duration_s:.1f} s)",
            f"- Status: {self.meta.status}",
            "",
            "## Claim",
            "",
            c.claim,
            "",
        ]
        if c.evidence:
            lines += ["## Evidence", "", c.evidence, ""]
        if c.takeaway:
            lines += ["## Takeaway", "", c.takeaway, ""]
        if self.provenance.source_spans:
            lines += ["## Sources", ""]
            for s in self.provenance.source_spans:
                lines.append(f"- {s.modality} `{s.doc_id}` at {s.label()}")
            for q in self.provenance.quotes:
                lines.append(f"> {q}")
            lines.append("")
        if self.provenance.equations:
            lines += ["## Equations", ""]
            for e in self.provenance.equations:
                lines.append(f"- `{e.label}`: `{e.latex}`")
            lines.append("")
        if self.symbol_ledger:
            lines += ["## Symbol ledger", "", "| symbol | meaning | color |", "| --- | --- | --- |"]
            for s in self.symbol_ledger:
                lines.append(f"| `{s.latex}` | {s.meaning} | {s.color or ''} |")
            lines.append("")
        lines += [
            "## Beats",
            "",
            "| # | beat | purpose | narration | duration |",
            "| --- | --- | --- | --- | --- |",
        ]
        for i, b in enumerate(self.beats, 1):
            lines.append(
                f"| {i} | `{b.beat_id}` | {b.purpose} | {b.narration} | {b.duration_s:.1f}+{b.wait_after_s:.1f} s |"
            )
        lines.append("")
        if self.meta.revision_notes:
            lines += ["## Revision notes", ""] + [f"- {n}" for n in self.meta.revision_notes] + [""]
        return "\n".join(lines)


# --------------------------------------------------------------------------- verification


class Finding(BaseModel):
    """One verification result. Every finding names an admissible fix (ADR 0004)."""

    gate: str  # parse | sandbox | structure | api | legacy_api | latex | duration | overlap | out_of_frame | text_too_small | too_small | coverage | order | duration_fit | runtime | critique
    severity: Severity
    message: str
    fix: str = ""
    line: int | None = None
    beat_id: str | None = None
    t: float | None = None
    who: list[str] = Field(default_factory=list)
    bbox: list[list[float]] = Field(default_factory=list)
    category: str | None = (
        None  # runtime failure category: api | latex | python | value | manim_runtime | timeout | oom | crash
    )

    @property
    def blocking(self) -> bool:
        return self.severity == Severity.FATAL

    def one_line(self) -> str:
        loc = ""
        if self.line is not None:
            loc = f" L{self.line}"
        elif self.beat_id:
            loc = f" [{self.beat_id}]"
        fix = f"  → {self.fix}" if self.fix else ""
        return f"[{self.severity}] {self.gate}{loc}: {self.message}{fix}"


class TierReport(BaseModel):
    tier: int
    ok: bool
    findings: list[Finding] = Field(default_factory=list)
    duration_s: float | None = None
    scores: dict[str, float] = Field(default_factory=dict)  # tier 2 rubric scores 0..1
    notes: str = ""
    elapsed_s: float = 0.0

    @property
    def fatal(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]


class Candidate(BaseModel):
    plan_id: str
    attempt: int
    code_path: str
    scene_class: str
    model: str = ""
    prompt_hash: str = ""
    reports: list[TierReport] = Field(default_factory=list)

    @property
    def passed_deterministic(self) -> bool:
        det = [r for r in self.reports if r.tier in (0, 1)]
        return bool(det) and all(r.ok for r in det)

    @property
    def all_findings(self) -> list[Finding]:
        return [f for r in self.reports for f in r.findings]


# --------------------------------------------------------------------------- output


class SectionArtifact(BaseModel):
    index: int
    name: str
    duration_s: float
    mp4: str
    gif: str | None = None
    png: str | None = None
    narration: str = ""


class ArtifactBundle(BaseModel):
    plan_id: str
    concept_id: str
    scene_class: str
    manim_version: str
    quality: str
    width: int
    height: int
    fps: float
    duration_s: float
    master_mp4: str
    pptx_mp4: str | None = None
    thumbnail: str | None = None
    last_frame: str | None = None
    full_gif: str | None = None
    sections: list[SectionArtifact] = Field(default_factory=list)
    html: str | None = None
    pptx: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ReviewNote(BaseModel):
    concept_id: str
    verdict: Literal["accept", "revise", "reject"] = "revise"
    note: str = ""
    author: str = ""
    created_at: str = ""
