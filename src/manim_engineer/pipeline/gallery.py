"""Static HTML galleries: one per run, plus an index across runs."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from jinja2 import Template

RUN_TEMPLATE = Template(
    r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ title }} · manim-engineer</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#0f1115;--card:#171a21;--ink:#e6e6e6;--mute:#9aa4b2;--acc:#58c4dd;--ok:#83c167;--warn:#f9e04c;--bad:#fc6255;--line:#262b35}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:24px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:0}a{color:var(--acc)}
.meta{color:var(--mute);font-size:13px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:0 0 20px}
.badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);margin-left:8px;vertical-align:middle}
.accepted{color:var(--ok);border-color:var(--ok)}.needs_human{color:var(--warn);border-color:var(--warn)}.rejected{color:var(--bad);border-color:var(--bad)}
.row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.gif{max-width:100%;border-radius:8px;border:1px solid var(--line);background:#000}
.main{flex:2 1 520px}.side{flex:1 1 300px;font-size:13px}
.sections{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.sec{width:200px;font-size:12px;color:var(--mute)}.sec img{width:100%;border-radius:6px;border:1px solid var(--line)}
details{margin-top:8px}summary{cursor:pointer;color:var(--mute)}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
pre{background:#0b0d11;padding:10px;border-radius:8px;overflow:auto;max-height:280px}
.find{margin:4px 0;padding:6px 8px;border-left:3px solid var(--line);background:#12151b;font-size:12px}
.find.fatal{border-color:var(--bad)}.find.warn{border-color:var(--warn)}.find.info{border-color:var(--mute)}
.scores{display:flex;gap:10px;flex-wrap:wrap}.score{background:#12151b;padding:4px 8px;border-radius:6px}
textarea{width:100%;min-height:70px;background:#0b0d11;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px}
button{background:var(--acc);color:#000;border:0;border-radius:8px;padding:6px 12px;cursor:pointer;font-weight:600}
.links a{margin-right:12px}.claim{margin:6px 0 10px}
.skipped{color:var(--mute);font-size:13px}
</style></head><body>
<h1>{{ title }}</h1>
<div class="meta">source: <code>{{ source }}</code> · modality {{ modality }} · {{ n_segments }} segments · backend {{ backend }} · {{ llm.calls }} LLM calls, {{ llm.duration_s }} s · wall {{ elapsed_s }} s · {{ accepted }} accepted / {{ needs_human }} needs review / {{ rejected }} rejected</div>

{% for c in concepts %}
<div class="card" id="{{ c.concept_id }}">
  <h2>{{ c.title }} <span class="badge {{ c.status }}">{{ c.status }}</span> <span class="badge">{{ c.archetype }}</span> <span class="badge">{{ c.duration }}</span></h2>
  <div class="claim"><b>Claim:</b> {{ c.claim }}</div>
  <div class="meta">sources: {{ c.sources }} · concept id <code>{{ c.concept_id }}</code> · attempts {{ c.n_attempts }}{% if c.used_fallback %} · <b>template fallback</b>{% endif %}</div>
  <div class="row">
    <div class="main">
      {% if c.full_gif %}<img class="gif" src="{{ c.full_gif }}" alt="{{ c.title }}">{% elif c.thumb %}<img class="gif" src="{{ c.thumb }}">{% else %}<div class="skipped">no animation produced</div>{% endif %}
      <div class="sections">
      {% for s in c.sections %}<div class="sec">{% if s.png %}<a href="{{ s.gif or s.mp4 }}"><img src="{{ s.png }}"></a>{% endif %}<div><b>{{ s.name }}</b> {{ s.duration }}s</div><div>{{ s.narration }}</div></div>{% endfor %}
      </div>
    </div>
    <div class="side">
      {% if c.scores %}<div class="scores">{% for k, v in c.scores.items() %}<span class="score">{{ k }} {{ v }}</span>{% endfor %}</div>{% endif %}
      {% if c.critique %}<p>{{ c.critique }}</p>{% endif %}
      <div class="links">{% if c.plan_md %}<a href="{{ c.plan_md }}">plan.md</a>{% endif %}{% if c.plan_json %}<a href="{{ c.plan_json }}">plan.json</a>{% endif %}{% if c.code %}<a href="{{ c.code }}">scene.py</a>{% endif %}{% if c.deck %}<a href="{{ c.deck }}">deck.pptx</a>{% endif %}{% if c.mp4 %}<a href="{{ c.mp4 }}">master.mp4</a>{% endif %}</div>
      <details><summary>{{ c.findings|length }} finding(s) on the accepted candidate</summary>{% for f in c.findings %}<div class="find {{ f.severity }}">[{{ f.gate }}{% if f.beat_id %} {{ f.beat_id }}{% endif %}] {{ f.message }}{% if f.fix %} — <i>{{ f.fix }}</i>{% endif %}</div>{% endfor %}</details>
      {% if c.history %}<details><summary>attempt history</summary>{% for h in c.history %}<div class="find">#{{ h.attempt }} {{ h.kind }}{% if h.model %} ({{ h.model }}){% endif %}: tier0 {{ h.tier0_ok }}, tier1 {{ h.tier1_ok }}{% if h.tier2_ok is not none %}, tier2 {{ h.tier2_ok }}{% endif %} · {{ h.n_fatal }} fatal · <a href="{{ h.code }}">code</a></div>{% endfor %}</details>{% endif %}
      <details open><summary>your feedback</summary>
        <textarea data-cid="{{ c.concept_id }}" placeholder="e.g. make the arrows blue and slow down the last beat"></textarea>
        <div style="margin-top:6px"><button onclick="copyCmd('{{ c.concept_id }}')">copy revise command</button> <span class="meta" id="msg-{{ c.concept_id }}"></span></div>
      </details>
    </div>
  </div>
</div>
{% endfor %}

{% if skipped %}<div class="card"><h2>Skipped passages</h2>{% for s in skipped %}<div class="skipped">{{ s.0 }}: {{ s.1 }}</div>{% endfor %}</div>{% endif %}
<script>
function copyCmd(cid){const t=document.querySelector('textarea[data-cid="'+cid+'"]').value.trim();if(!t){document.getElementById('msg-'+cid).textContent='type a note first';return;}
const cmd='manim-engineer revise "{{ run_dir }}" '+cid+' --note '+JSON.stringify(t);navigator.clipboard.writeText(cmd).then(()=>{document.getElementById('msg-'+cid).textContent='copied: '+cmd;});}
</script>
</body></html>
"""
)

INDEX_TEMPLATE = Template(
    r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>manim-engineer outputs</title>
<style>body{margin:0;background:#0f1115;color:#e6e6e6;font:15px/1.5 system-ui,sans-serif;padding:24px}a{color:#58c4dd}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}.card{background:#171a21;border:1px solid #262b35;border-radius:12px;padding:14px}
img{width:100%;border-radius:8px;background:#000}.meta{color:#9aa4b2;font-size:13px}h1{font-size:22px}</style></head><body>
<h1>manim-engineer outputs</h1><p class="meta">{{ runs|length }} run(s). Open a run to review its animations; leave notes and use the copied <code>revise</code> command to iterate.</p>
<div class="grid">{% for r in runs %}<div class="card"><a href="{{ r.href }}"><b>{{ r.name }}</b></a><div class="meta">{{ r.title }} · {{ r.tier }} · {{ r.accepted }} accepted / {{ r.needs_human }} review / {{ r.rejected }} rejected</div>{% if r.thumb %}<a href="{{ r.href }}"><img src="{{ r.thumb }}"></a>{% endif %}<div class="meta">{{ r.note }}</div></div>{% endfor %}</div>
</body></html>
"""
)


def _rel(base: Path, p: str | Path | None) -> str | None:
    if not p:
        return None
    try:
        return str(Path(p).resolve().relative_to(base.resolve()))
    except ValueError:
        return str(p)


def write_run_gallery(run_dir: Path, summary: dict[str, Any]) -> Path:
    run_dir = Path(run_dir)
    concepts = []
    for c in summary.get("concepts", []):
        bundle = c.get("bundle") or {}
        bdir = Path(c["bundle_dir"]) if c.get("bundle_dir") else None
        plan = c.get("plan") or {}
        secs = []
        for s in bundle.get("sections", []):
            secs.append(
                {
                    "name": s["name"],
                    "duration": round(s.get("duration_s", 0), 1),
                    "narration": html.escape(s.get("narration", "")),
                    "png": _rel(run_dir, bdir / s["png"]) if bdir and s.get("png") else None,
                    "gif": _rel(run_dir, bdir / s["gif"]) if bdir and s.get("gif") else None,
                    "mp4": _rel(run_dir, bdir / s["mp4"]) if bdir else None,
                }
            )
        history = []
        for a in c.get("attempts", []):
            history.append(
                {
                    "attempt": a["attempt"],
                    "kind": a["kind"],
                    "model": a.get("model", ""),
                    "tier0_ok": a.get("tier0_ok"),
                    "tier1_ok": a.get("tier1_ok"),
                    "tier2_ok": a.get("tier2_ok"),
                    "n_fatal": sum(
                        1 for f in a.get("findings", []) if f.get("severity") == "fatal"
                    ),
                    "code": _rel(run_dir, a.get("code_path")),
                }
            )
        spans = plan.get("provenance", {}).get("source_spans", [])
        labels = []
        for s in spans[:4]:
            if s.get("slide_index") is not None:
                labels.append(f"slide {s['slide_index']}")
            elif s.get("para_id"):
                labels.append(s["para_id"])
            elif s.get("t_start_s") is not None:
                labels.append(f"{int(s['t_start_s']) // 60:02d}:{int(s['t_start_s']) % 60:02d}")
        concepts.append(
            {
                "concept_id": c["concept_id"],
                "title": html.escape(plan.get("concept", {}).get("title", c["concept_id"])),
                "claim": html.escape(plan.get("concept", {}).get("claim", "")),
                "archetype": plan.get("archetype", {}).get("primary", ""),
                "status": c.get("status", ""),
                "duration": f"{bundle.get('duration_s', 0):.0f}s" if bundle else "",
                "sources": ", ".join(labels) + (" …" if len(spans) > 4 else ""),
                "n_attempts": len(c.get("attempts", [])),
                "used_fallback": c.get("used_fallback"),
                "full_gif": _rel(run_dir, bdir / bundle["full_gif"])
                if bdir and bundle.get("full_gif")
                else None,
                "thumb": _rel(run_dir, bdir / bundle["thumbnail"])
                if bdir and bundle.get("thumbnail")
                else None,
                "mp4": _rel(run_dir, bdir / bundle["master_mp4"])
                if bdir and bundle.get("master_mp4")
                else None,
                "deck": _rel(run_dir, bdir / bundle["pptx"])
                if bdir and bundle.get("pptx")
                else None,
                "sections": secs,
                "scores": {k: round(v * 5, 1) for k, v in (c.get("scores") or {}).items()},
                "critique": html.escape(c.get("critique_summary", "")),
                "plan_md": _rel(run_dir, run_dir / "plans" / f"{c['concept_id']}.md"),
                "plan_json": _rel(run_dir, run_dir / "plans" / f"{c['concept_id']}.json"),
                "code": _rel(run_dir, c.get("accepted_code")),
                "findings": [
                    {
                        "gate": f.get("gate"),
                        "severity": f.get("severity"),
                        "beat_id": f.get("beat_id"),
                        "message": html.escape(str(f.get("message", ""))),
                        "fix": html.escape(str(f.get("fix", ""))),
                    }
                    for f in c.get("final_findings", [])
                ],
                "history": history,
            }
        )
    order = {"accepted": 0, "needs_human": 1, "rejected": 2}
    concepts.sort(key=lambda c: order.get(c["status"], 3))
    out = RUN_TEMPLATE.render(
        title=html.escape(summary.get("title", run_dir.name)),
        source=html.escape(str(summary.get("source", ""))),
        modality=summary.get("modality", ""),
        n_segments=summary.get("n_segments", 0),
        backend=summary.get("backend", ""),
        llm=summary.get("llm", {"calls": 0, "duration_s": 0}),
        elapsed_s=summary.get("elapsed_s", 0),
        accepted=sum(1 for c in concepts if c["status"] == "accepted"),
        needs_human=sum(1 for c in concepts if c["status"] == "needs_human"),
        rejected=sum(1 for c in concepts if c["status"] == "rejected"),
        concepts=concepts,
        skipped=summary.get("skipped", []),
        run_dir=str(run_dir),
    )
    path = run_dir / "index.html"
    path.write_text(out)
    return path


def write_index(outputs_dir: Path) -> Path:
    outputs_dir = Path(outputs_dir)
    runs = []
    for run_json in sorted(outputs_dir.glob("*/run.json")):
        try:
            s = json.loads(run_json.read_text())
        except json.JSONDecodeError:
            continue
        rd = run_json.parent
        thumb = None
        for c in s.get("concepts", []):
            b = c.get("bundle") or {}
            if c.get("bundle_dir") and b.get("thumbnail"):
                thumb = _rel(outputs_dir, Path(c["bundle_dir"]) / b["thumbnail"])
                break
        st = [c.get("status") for c in s.get("concepts", [])]
        runs.append(
            {
                "name": rd.name,
                "href": f"{rd.name}/index.html",
                "title": html.escape(s.get("title", "")),
                "tier": s.get("case_tier", ""),
                "accepted": st.count("accepted"),
                "needs_human": st.count("needs_human"),
                "rejected": st.count("rejected"),
                "thumb": thumb,
                "note": html.escape(s.get("case_note", "")),
            }
        )
    path = outputs_dir / "index.html"
    path.write_text(INDEX_TEMPLATE.render(runs=runs))
    return path
