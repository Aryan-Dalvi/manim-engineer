"""Anthropic SDK backend, used when ANTHROPIC_API_KEY is set and the package exists."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from typing import Any

from manim_engineer.llm.backend import CallLog, LLMError, LLMRequest, LLMResponse, ModelTier

DEFAULT_MODELS: dict[str, str] = {
    "fast": "claude-sonnet-5",
    "strong": "claude-opus-5",
    "vision": "claude-sonnet-5",
}


class AnthropicBackend:
    name = "anthropic"

    def __init__(
        self,
        models: dict[str, str] | None = None,
        log: CallLog | None = None,
        api_key: str | None = None,
    ):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise LLMError(
                "anthropic package not installed; use `uv sync --extra anthropic`"
            ) from e
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.models = {**DEFAULT_MODELS, **(models or {})}
        self.log = log or CallLog(None)

    @staticmethod
    def available() -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def model_for(self, tier: ModelTier) -> str:
        return self.models[tier]

    def _content(self, req: LLMRequest) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        for p in req.images:
            mime = mimetypes.guess_type(p)[0] or "image/png"
            with open(p, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
            parts.append(
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
            )
        parts.append({"type": "text", "text": req.prompt})
        return parts

    def complete(self, req: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=self.model_for(req.tier),
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            messages=[{"role": "user", "content": self._content(req)}],
        )
        if req.system:
            kwargs["system"] = req.system
        if req.json_schema is not None:
            kwargs["tools"] = [
                {
                    "name": "emit",
                    "description": "Emit the structured answer.",
                    "input_schema": req.json_schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": "emit"}
        t0 = time.time()
        try:
            msg = self.client.messages.create(**kwargs)
        except Exception as e:  # SDK exceptions are vendor types; wrap them
            self.log.record(self.name, req, None, error=str(e))
            raise LLMError(f"anthropic error: {e}") from e
        dt = time.time() - t0
        text_parts, structured = [], None
        for block in msg.content:
            if getattr(block, "type", "") == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", "") == "tool_use":
                structured = dict(block.input)
        usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}
        resp = LLMResponse(
            text="\n".join(text_parts)
            if text_parts
            else (json.dumps(structured) if structured else ""),
            structured=structured,
            model=msg.model,
            duration_s=dt,
            usage=usage,
        )
        self.log.record(self.name, req, resp)
        return resp
