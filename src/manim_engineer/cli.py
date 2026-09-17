"""Command-line interface."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click

from manim_engineer.pipeline import (
    ApprovalError,
    RunConfig,
    approve_run,
    render_plan_file,
    revise_run,
    run_live,
    run_pipeline,
    unapprove_run,
    write_index,
)


def _cfg(**kw) -> RunConfig:
    models = {}
    for tier in ("fast", "strong", "vision"):
        v = kw.pop(f"model_{tier}", None)
        if v:
            models[tier] = v
    effort = {}
    es = kw.pop("effort_strong", None)
    if es:
        effort["strong"] = es
    cfg = RunConfig(models=models, effort=effort, **{k: v for k, v in kw.items() if v is not None})
    return cfg


common = [
    click.option(
        "--backend",
        type=click.Choice(["claude-cli", "anthropic", "fake"]),
        default=None,
        help="LLM backend (default: auto)",
    ),
    click.option("--model-fast", default=None, help="model for triage"),
    click.option("--model-strong", default=None, help="model for planning and code"),
    click.option("--model-vision", default=None, help="model for critique"),
    click.option(
        "--quality", type=click.Choice(["l", "m", "h"]), default="m", help="render quality"
    ),
    click.option("--max-plans", type=int, default=4, help="max concepts to animate"),
    click.option("--audience", default="mixed"),
    click.option("--min-salience", type=int, default=3),
    click.option(
        "--constraint", "constraints", multiple=True, help="extra planner constraint (repeatable)"
    ),
    click.option(
        "--no-critique",
        "critique",
        flag_value=False,
        default=True,
        help="skip Tier 2 vision critique",
    ),
    click.option("--workers", type=int, default=2),
    click.option("--allow-3d", is_flag=True, default=False),
    click.option(
        "--kind",
        "input_kind",
        default=None,
        help="force input kind: transcript|markdown|pdf|pdf-deck|pdf-paper|pptx|audio|youtube",
    ),
    click.option("--max-pages", type=int, default=None),
    click.option("--title", default=None),
]


def add_options(opts):
    def wrap(f):
        for o in reversed(opts):
            f = o(f)
        return f

    return wrap


@click.group()
def main() -> None:
    """manim-engineer: verified Manim animations from talks, slides, papers and audio."""


@main.command()
@click.argument("source")
@click.option("--out", required=True, help="run directory (created)")
@add_options(common)
def run(source, out, constraints, **kw):
    """Ingest SOURCE, plan concepts, generate + verify + publish animations, write a gallery."""
    cfg = _cfg(constraints=list(constraints), **kw)
    run_pipeline(source, out, cfg)


@main.command()
@click.argument("source")
@click.option("--out", required=True)
@click.option("--chunk", type=int, default=3, help="segments fed per tick")
@click.option(
    "--sleep", type=float, default=0.0, help="seconds to sleep per tick (simulated live pacing)"
)
@add_options(common)
def live(source, out, chunk, sleep, constraints, **kw):
    """Replay SOURCE as a live stream; plans and animations appear as concepts mature."""
    cfg = _cfg(constraints=list(constraints), **kw)
    try:
        run_live(source, out, cfg, chunk=chunk, sleep_s=sleep)
    except ApprovalError as e:
        raise click.ClickException(str(e)) from e


@main.command("plan")
@click.argument("source")
@click.option("--out", required=True)
@add_options(common)
def plan_cmd(source, out, constraints, **kw):
    """Ingest and plan only (writes plans/*.json and *.md, no rendering)."""
    from manim_engineer.llm import select_backend
    from manim_engineer.pipeline.run import RunDir, _planner_cfg, ingest_source
    from manim_engineer.planning import plan_document, save_plan

    cfg = _cfg(constraints=list(constraints), **kw)
    rd = RunDir(out).ensure()
    backend = select_backend(cfg.backend, models=cfg.models or None, log_dir=rd.path / "llm_calls")
    doc = ingest_source(source, rd, cfg)
    plans, skipped = plan_document(doc, backend, _planner_cfg(cfg), max_plans=cfg.max_plans)
    for p in plans:
        path = save_plan(p, rd.plans)
        click.echo(f"plan: {path}")
    for b, why in skipped:
        click.echo(f"skipped {b}: {why}")


@main.command("render-plan")
@click.argument("plan_path")
@click.option("--out", required=True)
@add_options(common)
def render_plan(plan_path, out, constraints, **kw):
    """Realize one plan JSON (edit plans/<id>.json by hand, then re-render)."""
    cfg = _cfg(constraints=list(constraints), **kw)
    r = render_plan_file(plan_path, out, cfg)
    click.echo(f"{r.concept_id}: {r.status} {r.message}")


@main.command()
@click.argument("run_dir")
@click.argument("concept_id")
@click.option("--note", required=True, help="what to change")
@click.option("--author", default="")
@add_options(common)
def revise(run_dir, concept_id, note, author, constraints, **kw):
    """Apply a reviewer note to one animation and re-verify/re-publish it."""
    cfg = _cfg(constraints=list(constraints), **kw)
    r = revise_run(run_dir, concept_id, note, cfg, author=author)
    click.echo(f"{r.concept_id}: {r.status} {r.message}")


@main.command()
@click.argument("run_dir")
@click.argument("concept_id")
@click.option("--author", default="")
@click.option("--note", default="", help="why the animation is approved")
def approve(run_dir, concept_id, author, note):
    """Pin a concept's plan and accepted animation so later runs keep it."""
    try:
        pin = approve_run(run_dir, concept_id, author=author, note=note, log=lambda *a: None)
    except ApprovalError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"{concept_id}: approved (pin {pin.pin[:12]})")


@main.command()
@click.argument("run_dir")
@click.argument("concept_id")
@click.option("--author", default="")
def unapprove(run_dir, concept_id, author):
    """Remove a concept's approval pin."""
    try:
        pin = unapprove_run(run_dir, concept_id, author=author, log=lambda *a: None)
    except ApprovalError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"{concept_id}: {pin.revoked_reason}")


@main.command()
@click.argument("outputs_dir", default="outputs")
def gallery(outputs_dir):
    """Rebuild the gallery-of-galleries index for an outputs directory."""
    from manim_engineer.pipeline.gallery import write_run_gallery
    from manim_engineer.pipeline.run import RunDir

    for rj in sorted(Path(outputs_dir).glob("*/run.json")):
        write_run_gallery(rj.parent, RunDir(rj.parent).load_summary())
    p = write_index(Path(outputs_dir))
    click.echo(f"wrote {p}")


@main.command("run-cases")
@click.option("--cases-dir", default="cases")
@click.option("--out", default="outputs")
@click.option("--only", multiple=True, help="case names to run (repeatable)")
@click.option("--tier", "tiers", multiple=True, type=click.Choice(["easy", "hard", "challenging"]))
@add_options(common)
def run_cases(cases_dir, out, only, tiers, constraints, **kw):
    """Run every case in cases/ (each has case.json) and rebuild the outputs index."""
    base_cfg = _cfg(constraints=list(constraints), **kw)
    cases = sorted(Path(cases_dir).glob("*/case.json"))
    for cj in cases:
        meta = json.loads(cj.read_text())
        name = cj.parent.name
        if only and name not in only:
            continue
        if tiers and meta.get("tier") not in tiers:
            continue
        cfg = RunConfig(**{**base_cfg.to_dict(), **meta.get("config", {})})
        if isinstance(cfg.repair, dict):
            from manim_engineer.pipeline.config import RepairPolicy

            cfg.repair = RepairPolicy(**cfg.repair)
        src = meta["source"]
        if not src.startswith("http"):
            src = str(cj.parent / src)
        if meta.get("companion"):
            cfg.extra["companion"] = [str(cj.parent / x) for x in meta["companion"]]
        out_dir = Path(out) / name
        click.echo(f"=== {name} ({meta.get('tier')}): {meta.get('note', '')}")
        case_meta = {"case_tier": meta.get("tier", ""), "case_note": meta.get("note", "")}
        try:
            if meta.get("mode") == "live":
                run_live(src, out_dir, cfg, chunk=meta.get("chunk", 3), case_meta=case_meta)
            else:
                run_pipeline(src, out_dir, cfg, case_meta=case_meta)
        except Exception as e:  # keep going through the corpus
            click.echo(f"!!! {name} failed: {e}")
        write_index(Path(out))
    click.echo(f"index: {Path(out) / 'index.html'}")


@main.command()
def doctor():
    """Check tools: manim, ffmpeg, latex, backends."""
    import manim

    rows = [("manim", manim.__version__), ("python", sys.version.split()[0])]
    for tool in ("ffmpeg", "ffprobe", "latex", "dvisvgm", "claude", "node"):
        rows.append((tool, shutil.which(tool) or "missing"))
    try:
        import faster_whisper  # noqa: F401

        rows.append(("faster-whisper", "ok"))
    except ImportError:
        rows.append(("faster-whisper", "missing (uv sync --extra audio)"))
    from manim_engineer.llm import AnthropicBackend, ClaudeCliBackend

    rows.append(("backend claude-cli", "available" if ClaudeCliBackend.available() else "missing"))
    rows.append(("backend anthropic", "available" if AnthropicBackend.available() else "no key"))
    for k, v in rows:
        click.echo(f"{k:20} {v}")


if __name__ == "__main__":  # pragma: no cover
    main()
