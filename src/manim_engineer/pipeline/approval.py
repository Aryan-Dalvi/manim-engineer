"""Approval pins: a reviewer's sign-off on one concept's plan and accepted code (ADR 0009).

A pin hashes the plan JSON and the accepted scene file. It holds while both are
unchanged, so a repeated run can keep the concept, and it breaks with a stated
reason as soon as either one changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

APPROVABLE_STATUSES = ("accepted", "needs_human")


class ApprovalError(Exception):
    """A concept cannot be approved, or a command cannot run, in the current approval state."""


class ApprovalPin(BaseModel):
    concept_id: str
    pin: str
    plan_sha256: str
    code_sha256: str
    accepted_code: str  # relative to the run directory
    approved_at: str
    author: str = ""
    note: str = ""
    revoked_at: str | None = None
    revoked_reason: str | None = None


class Approvals(BaseModel):
    schema_version: int = 1
    approved: dict[str, ApprovalPin] = Field(default_factory=dict)
    revoked: list[ApprovalPin] = Field(default_factory=list)


def approvals_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "review" / "approvals.json"


def load_approvals(run_dir: str | Path) -> Approvals:
    path = approvals_path(run_dir)
    if not path.exists():
        return Approvals()
    return Approvals.model_validate_json(path.read_text())


def save_approvals(run_dir: str | Path, approvals: Approvals) -> Path:
    path = approvals_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(approvals.model_dump_json(indent=1))
    # a run reading approvals while `approve` writes them must never see half a file
    os.replace(tmp, path)
    return path


def plan_sha256(plan: Any) -> str:
    # canonical form, so reformatting a hand-edited plan does not break its pin
    blob = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pin_digest(plan_digest: str, code_digest: str) -> str:
    return hashlib.sha256(f"{plan_digest}:{code_digest}".encode()).hexdigest()


def _run_relative(run_dir: Path, path: str | Path) -> str:
    try:
        return Path(path).resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def _plan_file(run_dir: Path, concept_id: str) -> Path:
    return run_dir / "plans" / f"{concept_id}.json"


def _entry(summary: dict[str, Any], concept_id: str) -> dict[str, Any] | None:
    return next((c for c in summary.get("concepts", []) if c.get("concept_id") == concept_id), None)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pin_problem(run_dir: str | Path, pin: ApprovalPin, entry: dict[str, Any] | None) -> str | None:
    """Why a pin no longer holds, or None while its plan and accepted code are unchanged."""
    run_dir = Path(run_dir)
    plan_file = _plan_file(run_dir, pin.concept_id)
    if not plan_file.exists():
        return "plan file is missing"
    try:
        plan_digest = plan_sha256(json.loads(plan_file.read_text()))
    except json.JSONDecodeError:
        return "plan JSON no longer parses"
    if plan_digest != pin.plan_sha256:
        return "plan changed since approval"
    if not entry or not entry.get("accepted_code"):
        return "run.json has no accepted animation for this concept"
    code = _run_relative(run_dir, entry["accepted_code"])
    if code != pin.accepted_code:
        return f"accepted animation replaced: {pin.accepted_code} → {code}"
    code_file = run_dir / code
    if not code_file.exists():
        return "accepted code file is missing"
    if _file_sha256(code_file) != pin.code_sha256:
        return "accepted code changed since approval"
    return None


def check_pins(
    run_dir: str | Path, summary: dict[str, Any], approvals: Approvals
) -> tuple[dict[str, ApprovalPin], dict[str, str]]:
    """Split approved concepts into pins that hold and pins that broke, with the reason."""
    held: dict[str, ApprovalPin] = {}
    broken: dict[str, str] = {}
    for cid, pin in approvals.approved.items():
        problem = pin_problem(run_dir, pin, _entry(summary, cid))
        if problem is None:
            held[cid] = pin
        else:
            broken[cid] = problem
    return held, broken


def approve_concept(
    run_dir: str | Path,
    summary: dict[str, Any],
    concept_id: str,
    author: str = "",
    note: str = "",
) -> ApprovalPin:
    run_dir = Path(run_dir)
    entry = _entry(summary, concept_id)
    if entry is None:
        raise ApprovalError(f"{concept_id} is not a concept in {run_dir}")
    status = entry.get("status")
    if (
        status not in APPROVABLE_STATUSES
        or not entry.get("accepted_code")
        or not entry.get("bundle")
    ):
        raise ApprovalError(f"{concept_id} has no accepted animation to approve (status {status})")
    plan_file = _plan_file(run_dir, concept_id)
    try:
        plan_digest = plan_sha256(json.loads(plan_file.read_text()))
    except (OSError, json.JSONDecodeError) as e:
        raise ApprovalError(f"cannot read {plan_file}: {e}") from e
    if plan_digest != plan_sha256(entry.get("plan")):
        raise ApprovalError(
            f"{plan_file} changed after this animation was rendered; re-render it with "
            f"`manim-engineer render-plan {plan_file} --out {run_dir}` and approve the result"
        )
    code = _run_relative(run_dir, entry["accepted_code"])
    code_file = run_dir / code
    if not code_file.exists():
        raise ApprovalError(f"accepted code {code_file} is missing")
    code_digest = _file_sha256(code_file)
    pin = ApprovalPin(
        concept_id=concept_id,
        pin=_pin_digest(plan_digest, code_digest),
        plan_sha256=plan_digest,
        code_sha256=code_digest,
        accepted_code=code,
        approved_at=_now(),
        author=author,
        note=note,
    )
    approvals = load_approvals(run_dir)
    approvals.approved[concept_id] = pin
    save_approvals(run_dir, approvals)
    return pin


def revoke(approvals: Approvals, concept_id: str, reason: str) -> ApprovalPin | None:
    pin = approvals.approved.pop(concept_id, None)
    if pin is None:
        return None
    revoked = pin.model_copy(update={"revoked_at": _now(), "revoked_reason": reason})
    approvals.revoked.append(revoked)
    return revoked
