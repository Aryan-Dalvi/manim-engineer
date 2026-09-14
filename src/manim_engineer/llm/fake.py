"""Scripted backend for deterministic tests and dry runs."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from manim_engineer.llm.backend import CallLog, LLMError, LLMRequest, LLMResponse, ModelTier

Responder = Callable[[LLMRequest], Any]


class FakeBackend:
    """Replies from a script keyed by request tag.

    `responses` maps tag -> list of replies (dicts become structured output,
    strings become text) or tag -> callable(request) -> reply. A tag with no
    entry falls back to `default`, then raises.
    """

    name = "fake"

    def __init__(
        self,
        responses: dict[str, list[Any] | Responder] | None = None,
        default: Responder | None = None,
        log: CallLog | None = None,
    ):
        self.responses = {
            k: (list(v) if isinstance(v, list) else v) for k, v in (responses or {}).items()
        }
        self.default = default
        self.log = log or CallLog(None)
        self.requests: list[LLMRequest] = []

    def model_for(self, tier: ModelTier) -> str:
        return f"fake-{tier}"

    def _reply(self, req: LLMRequest) -> Any:
        entry = self.responses.get(req.tag)
        if callable(entry):
            return entry(req)
        if isinstance(entry, list) and entry:
            return entry.pop(0)
        if self.default is not None:
            return self.default(req)
        raise LLMError(f"FakeBackend has no scripted reply for tag {req.tag!r}")

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        reply = self._reply(req)
        if isinstance(reply, Exception):
            self.log.record(self.name, req, None, error=str(reply))
            raise reply
        if isinstance(reply, dict):
            resp = LLMResponse(
                text=json.dumps(reply), structured=reply, model=self.model_for(req.tier)
            )
        else:
            resp = LLMResponse(text=str(reply), model=self.model_for(req.tier))
        self.log.record(self.name, req, resp)
        return resp
