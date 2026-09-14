# ADR 0005: LLM access through an LLMBackend adapter with a Claude CLI default

## Status

Accepted (2026-09-14)

## Context

The project must work as a harness for people's own agents and must run on this machine, which has a Claude Code login but no API key. Tests must be deterministic.

## Decision

`llm.LLMBackend` is a protocol with `complete(request) -> Response`, supporting text, JSON-schema structured output, and image inputs. Implementations: `ClaudeCliBackend` (spawns `claude -p` with `--output-format json`, `--json-schema`, and `--allowedTools Read` for images), `AnthropicBackend` (SDK, used when `ANTHROPIC_API_KEY` is set), and `FakeBackend` (scripted responses keyed by request tag). Backend selection lives in `pipeline` config; prompts live in planning and generation; no other context imports vendor SDKs. Every call is logged to the run directory with prompt hash, model, duration, and usage.

## Consequences

- **Benefit:** zero-config on subscription logins; swappable providers; replayable tests.
- **Tradeoff:** CLI calls are slower than SDK calls and cannot stream mid-generation.
- **Follow-up:** add an OpenAI-compatible backend if users ask.
