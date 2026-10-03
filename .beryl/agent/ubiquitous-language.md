# Ubiquitous Language

## Project Terms

| Business Term | Technical Symbol | Definition | Constraints | Avoid |
| --- | --- | --- | --- | --- |
| Source Span | `SourceSpan` | Where a piece of content came from: modality, document id, and exactly one of time range, slide index, or paragraph id | Exactly one locator group populated | `Ref`, `Pointer` |
| Segment | `Segment` | One unit of normalized input text with a `SourceSpan`, a kind (speech, slide text, notes, body, equation, code) | Every adapter emits only Segments | `Chunk` (reserved for planner windows) |
| Document | `Document` | The normalized result of ingesting one input: segments plus assets and metadata | Immutable after ingestion | `Transcript` (only one modality) |
| Equation Ledger | `Document.meta["equation_ledger"]` | Display equations extracted from a source document with their label, `para_id` and environment | Only adapters that read real source markup produce one | `Formula list` |
| Verbatim Equation | `Equation.verbatim` | An equation carried from the source document rather than written by a model | The fidelity gate blocks only on these | `Quoted equation` |
| Bucket | `Bucket` | A growing set of segments believed to describe one concept | Mutable; bounded; owned by planning | `Cluster` |
| Maturity | `mature(bucket)` | Scored predicate deciding a bucket has enough concrete content to plan | Combines mass, cohesion, boundary, archetype confidence, concreteness, staleness, dedup | Single threshold |
| Concept | `concept_id` | A stable slug for one animatable idea | Deduplicated by fingerprint | `Topic` |
| Animation Plan | `AnimationPlan` | Typed, editable specification of one animation: provenance, claim, archetype, beats, layout, budgets, symbol ledger, review criteria | JSON on disk; validated before generation | `Storyboard` (prose) |
| Beat | `Beat` | One step of an animation: what appears, transforms, disappears, is emphasized, plus narration and duration | Beat id equals the Manim section name | `Scene` (Manim class) |
| Archetype | `Archetype` | The visual family a plan uses (equation derivation, plot, geometric, flow diagram, timeline, table, algorithm trace, graph, matrix, distribution, number line, sets, memory layout, 3D) | One primary, at most one secondary | `Style` (reserved for palette/theme) |
| Kit | `manim_engineer.kit` | Runtime library imported by generated scenes: style contract, safe helpers, deterministic layout builders | Generated code must import it | `Utils` |
| Candidate | `Candidate` | One generated scene file plus its class name and attempt number | Immutable; findings attach to it | `Draft` |
| Finding | `Finding` | One verification result: gate, severity, location, observed value, admissible fix | Every finding carries a fix | `Error` (too narrow) |
| Tier 0 | `verification.static` | Parse, sandbox lint, structure, API existence, LaTeX precompile, duration bound | No render, no Manim scene execution | |
| Tier 1 | `verification.probe` | Execute `construct()` with rendering disabled and check bounding boxes at each animation boundary | Sandboxed child process with limits | `Dry run` |
| Tier 2 | `verification.critique` | Low-res render, per-beat frames, contact sheet, VLM scores | Advisory and ranking, never sole gate for geometry | |
| Repair Budget | `RepairPolicy` | Max attempts per finding class and abort rule on repeated category | Deterministic: 3; visual: 2; total calls: 5 | `TryAgainLoop` |
| Artifact Bundle | `ArtifactBundle` | Published outputs for one plan: master MP4, sections, GIFs, stills, manifest | `manifest.json` is the contract | `Export` |
| Run | `outputs/<run>/` | One pipeline execution over one input, with gallery | Self-contained directory | `Job` |
| Review Note | `ReviewNote` | Human feedback attached to a concept in a run | Consumed by `revise` | `Comment` |
| Backend | `LLMBackend` | Adapter that completes text or structured output and reads images | Claude CLI, Anthropic SDK, Fake | `Client` |

## Beryl Terms

| Business Term | Technical Symbol | Definition | Constraints | Avoid |
| --- | --- | --- | --- | --- |
| Design Concept | `DesignConcept` | The shared organizing model guiding architecture and implementation choices. | Must be coherent across contexts. | `Idea`, `GeneralModel` |
| Design Tree | `DesignTree` | Living map of open and settled decisions. | Updated when design moves. | `PlanDump` |
| Bounded Context | `BoundedContext` | A domain boundary with explicit ownership and language. | Owns its internal model and API. | `Module` (too generic) |
| Feedback Loop | `FeedbackLoop` | Generate-check-fix cycle using deterministic tools. | Must include real tool output. | `TryAgainLoop` |
| Success Check | `SuccessCheck` | Pre-coding acceptance condition that proves a plan, redirect, feature slice, or bug fix worked. | Must name the expected artifact, deterministic command, generated output or browser evidence when applicable, and at least one user-visible behavior. | Vague done criteria such as `LooksGood` |
| Commit Boundary | `CommitBoundary` | Proposed repo-history unit for implementation work. | Must have one purpose, expected files, and a validating check command. | Large mixed commit |
| Generated Output | `GeneratedOutput` | Built artifact users receive. | Verify generated output, not source alone. | Source-only verification |
| Affected Test Gate | `.beryl/scripts/check-affected.sh` | Commit and manual check step that maps changed files to related tests or full-test fallback. | Deterministic, run through `check.sh`. | Ad hoc local test picking |
| Full Test Fallback | `FULL_TEST_CMD` | Complete project test command used when a change is too broad. | Configured in `.beryl/agent/affected-tests.conf`. | Silent skip |
| Vertical Slice | `VerticalSlice` | Smallest end-to-end behavior change through one boundary. | Must be testable in isolation. | `BigRefactor` |
| Adapter | `Adapter` | Boundary object that isolates external systems from domain logic. | Domain must not depend on vendor details. | `ServiceHelper` |
| ADR | `ADR` | Architecture Decision Record for durable decisions. | Required for lasting boundary changes. | `RandomNote` |
