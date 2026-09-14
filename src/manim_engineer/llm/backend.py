"""LLMBackend protocol and request/response types (ADR 0005).

Prompts belong to planning and generation; this context only moves them to a
provider and back. Every call is logged so a run can be audited or replayed.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

ModelTier = Literal["fast", "strong", "vision"]


class LLMError(RuntimeError):
    """Raised when a backend cannot produce a usable response."""


@dataclass
class LLMRequest:
    prompt: str
    system: str = ""
    tier: ModelTier = "strong"
    json_schema: dict[str, Any] | None = None
    images: list[str] = field(default_factory=list)
    tag: str = "call"
    max_tokens: int = 8000
    temperature: float = 0.0
    timeout_s: int = 600

    def prompt_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.system.encode())
        h.update(b"\x00")
        h.update(self.prompt.encode())
        if self.json_schema:
            h.update(json.dumps(self.json_schema, sort_keys=True).encode())
        for p in self.images:
            h.update(p.encode())
        return h.hexdigest()[:16]


@dataclass
class LLMResponse:
    text: str
    structured: dict[str, Any] | None = None
    model: str = ""
    duration_s: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def require_structured(self) -> dict[str, Any]:
        if self.structured is not None:
            return self.structured
        # last resort: parse text as JSON (fenced or bare)
        txt = self.text.strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            if txt.startswith("json"):
                txt = txt[4:]
        try:
            data = json.loads(txt)
        except json.JSONDecodeError as e:
            raise LLMError(f"response is not JSON: {e}: {self.text[:300]}") from e
        if not isinstance(data, dict):
            raise LLMError("structured response must be a JSON object")
        self.structured = data
        return data


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...

    def model_for(self, tier: ModelTier) -> str: ...


class CallLog:
    """Append-only JSON log of every LLM call in a run directory."""

    def __init__(self, log_dir: Path | None):
        self.log_dir = Path(log_dir) if log_dir else None
        self.calls: list[dict[str, Any]] = []
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def record(
        self, backend: str, req: LLMRequest, resp: LLMResponse | None, error: str | None = None
    ) -> None:
        entry = {
            "n": len(self.calls),
            "ts": time.time(),
            "backend": backend,
            "tag": req.tag,
            "tier": req.tier,
            "model": resp.model if resp else None,
            "prompt_hash": req.prompt_hash(),
            "duration_s": resp.duration_s if resp else None,
            "usage": resp.usage if resp else {},
            "cost_usd": resp.cost_usd if resp else None,
            "error": error,
            "images": req.images,
            "system": req.system,
            "prompt": req.prompt,
            "response": resp.text if resp else None,
            "structured": resp.structured if resp else None,
        }
        self.calls.append(entry)
        if self.log_dir:
            path = self.log_dir / f"{entry['n']:03d}_{req.tag}.json"
            path.write_text(json.dumps(entry, indent=1, default=str))

    def summary(self) -> dict[str, Any]:
        total = sum(c["duration_s"] or 0 for c in self.calls)
        cost = sum(c["cost_usd"] or 0 for c in self.calls)
        return {"calls": len(self.calls), "duration_s": round(total, 1), "cost_usd": round(cost, 4)}
