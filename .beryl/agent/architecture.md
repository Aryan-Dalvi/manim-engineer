# Architecture

## Bounded Contexts

Python package `manim_engineer` under `src/`. Each context is a subpackage
whose `__init__.py` is its only public entry point.

| Context | Owns | Does Not Own | Public Entry Point |
| --- | --- | --- | --- |
| core | Domain models: `SourceSpan`, `Segment`, `Document`, `AnimationPlan`, `Beat`, `Finding`, `Candidate`, `ArtifactBundle`, enums; the source preamble's pure TeX parsing (`parse_macro_definitions`, `select_definitions`, `parse_tex_packages`) and the TeX package allowlist | Any I/O, any vendor type | `src/manim_engineer/core/__init__.py` |
| llm | `LLMBackend` protocol, Claude CLI / Anthropic / Fake backends, structured output, vision requests, call log | Prompt content (belongs to planning/generation) | `src/manim_engineer/llm/__init__.py` |
| ingest | Adapters from transcript/markdown/PDF/PPTX/audio/YouTube to `Document` | Deciding what to animate | `src/manim_engineer/ingest/__init__.py` |
| planning | Bucketing, triage, plan prompts, plan validation, live replay state | Code generation | `src/manim_engineer/planning/__init__.py` |
| generation | Knowledge pack, codegen and repair prompts, archetype router | Rendering, verification | `src/manim_engineer/generation/__init__.py` |
| kit | Runtime library imported by generated scenes (style contract, safe helpers, layout builders); applying the source preamble at import (`use_source_preamble`, `source_tex_template`) | Anything that talks to an LLM | `src/manim_engineer/kit/__init__.py` |
| verification | Tier 0 static, Tier 1 probe, Tier 2 frames + critique, sandbox runner, finding formatting | Deciding repair policy | `src/manim_engineer/verification/__init__.py` |
| output | Render at quality, ffmpeg derivatives, manifest, PPTX and Reveal.js deck builders, vendored Reveal.js assets | Gallery HTML, choosing which concepts a run deck includes | `src/manim_engineer/output/__init__.py` |
| pipeline | Orchestrator, run directory, repair policy, approval pins, gallery, run deck, review/revise, CLI | Domain rules of other contexts | `src/manim_engineer/pipeline/__init__.py`, `src/manim_engineer/cli.py` |

## Boundary Rules

1. A context may import only another context's public entry point.
2. Internal files of another context are forbidden imports.
3. External APIs, SDKs, and persistence details must be accessed through adapters.
4. Domain logic must not depend directly on HTTP objects, ORM records, UI state, or vendor client types.
5. Generated scene code imports `manim_engineer.kit` and `manim`; it never imports other contexts. Its only TeX configuration is the `use_source_preamble(...)` header that generation writes from the plan (ADR 0010).

## Public Interface Rule

Each context exposes one explicit public entry point:

- Python: `src/manim_engineer/<context>/__init__.py`

## Forbidden Import Policy

- `manim_engineer.core -> manim`, `anthropic`, `subprocess` (core is pure data)
- `manim_engineer.planning -> manim_engineer.generation.*`
- `manim_engineer.generation -> manim_engineer.verification.*` (repair shaping consumes `Finding` from core only)
- `manim_engineer.kit -> manim_engineer.llm`
- any context -> `manim_engineer.<other>.<internal module>`

Enforced by `tests/test_boundaries.py`.
