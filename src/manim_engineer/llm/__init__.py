"""llm bounded context: provider adapters behind one LLMBackend protocol (ADR 0005)."""

from __future__ import annotations

from pathlib import Path

from manim_engineer.llm.anthropic_sdk import AnthropicBackend
from manim_engineer.llm.backend import (
    CallLog,
    LLMBackend,
    LLMError,
    LLMRequest,
    LLMResponse,
    ModelTier,
)
from manim_engineer.llm.claude_cli import ClaudeCliBackend
from manim_engineer.llm.fake import FakeBackend

BACKEND_NAMES = ("claude-cli", "anthropic", "fake")


def select_backend(
    name: str | None = None,
    models: dict[str, str] | None = None,
    log_dir: Path | None = None,
    effort: dict[str, str] | None = None,
) -> LLMBackend:
    """Pick a backend: explicit name, else Claude CLI if installed, else Anthropic SDK if keyed."""
    log = CallLog(log_dir)
    if name == "fake":
        return FakeBackend(log=log)
    if name == "anthropic":
        return AnthropicBackend(models=models, log=log)
    if name == "claude-cli":
        return ClaudeCliBackend(models=models, log=log, effort=effort)
    if name is not None:
        raise LLMError(f"unknown backend {name!r}; choose from {BACKEND_NAMES}")
    if ClaudeCliBackend.available():
        return ClaudeCliBackend(models=models, log=log, effort=effort)
    if AnthropicBackend.available():
        return AnthropicBackend(models=models, log=log)
    raise LLMError(
        "no LLM backend available: install the Claude CLI or set ANTHROPIC_API_KEY (or use --backend fake)"
    )


__all__ = [
    "BACKEND_NAMES",
    "AnthropicBackend",
    "CallLog",
    "ClaudeCliBackend",
    "FakeBackend",
    "LLMBackend",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "ModelTier",
    "select_backend",
]
