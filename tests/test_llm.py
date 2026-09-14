import json
from pathlib import Path

import pytest

from manim_engineer.llm import (
    CallLog,
    ClaudeCliBackend,
    FakeBackend,
    LLMError,
    LLMRequest,
    select_backend,
)


def test_fake_backend_scripts_by_tag_and_logs(tmp_path: Path):
    log = CallLog(tmp_path / "llm")
    fb = FakeBackend(responses={"plan": [{"a": 1}, {"a": 2}], "text": ["hello"]}, log=log)
    r1 = fb.complete(LLMRequest(prompt="p", tag="plan", json_schema={"type": "object"}))
    r2 = fb.complete(LLMRequest(prompt="p", tag="plan"))
    r3 = fb.complete(LLMRequest(prompt="p", tag="text"))
    assert r1.structured == {"a": 1} and r2.structured == {"a": 2}
    assert r3.text == "hello"
    assert len(list((tmp_path / "llm").glob("*.json"))) == 3
    assert log.summary()["calls"] == 3
    with pytest.raises(LLMError):
        fb.complete(LLMRequest(prompt="p", tag="plan"))


def test_fake_backend_callable_and_default():
    fb = FakeBackend(
        responses={"echo": lambda r: r.prompt.upper()}, default=lambda r: {"tag": r.tag}
    )
    assert fb.complete(LLMRequest(prompt="hi", tag="echo")).text == "HI"
    assert fb.complete(LLMRequest(prompt="hi", tag="other")).structured == {"tag": "other"}


def test_require_structured_parses_fenced_json():
    fb = FakeBackend(responses={"t": ['```json\n{"x": 1}\n```']})
    resp = fb.complete(LLMRequest(prompt="p", tag="t"))
    assert resp.require_structured() == {"x": 1}
    bad = FakeBackend(responses={"t": ["not json"]}).complete(LLMRequest(prompt="p", tag="t"))
    with pytest.raises(LLMError):
        bad.require_structured()


def test_claude_cli_argv_and_prompt(tmp_path: Path):
    be = ClaudeCliBackend(models={"strong": "opus"}, workdir=tmp_path)
    req = LLMRequest(
        prompt="do it", system="sys", tier="strong", json_schema={"type": "object"}, tag="x"
    )
    argv = be.build_argv(req, tmp_path / "sys.md")
    assert argv[:2] == ["claude", "-p"]
    assert "--model" in argv and argv[argv.index("--model") + 1] == "opus"
    assert "--json-schema" in argv and "--system-prompt-file" in argv
    assert "--tools" in argv  # no tools when no images
    img = LLMRequest(prompt="critique", images=[str(tmp_path / "a.png")], tier="vision")
    argv2 = be.build_argv(img, None)
    assert "--allowedTools" in argv2 and argv2[argv2.index("--allowedTools") + 1] == "Read"
    assert str(tmp_path / "a.png") in ClaudeCliBackend.build_prompt(img)


def test_claude_cli_parse_result():
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": '{"sum":5}',
        "structured_output": {"sum": 5},
        "total_cost_usd": 0.01,
        "duration_ms": 1000,
        "usage": {"input_tokens": 10},
        "modelUsage": {"claude-haiku-4-5-20251001": {}, "claude-opus-5": {}},
    }
    resp = ClaudeCliBackend.parse_result(json.dumps(payload), 1.0)
    assert resp.structured == {"sum": 5}
    assert resp.model == "claude-opus-5"
    assert resp.cost_usd == 0.01
    with pytest.raises(LLMError):
        ClaudeCliBackend.parse_result(json.dumps({**payload, "is_error": True}), 1.0)
    with pytest.raises(LLMError):
        ClaudeCliBackend.parse_result("garbage", 1.0)


def test_select_backend_names():
    assert select_backend("fake").name == "fake"
    with pytest.raises(LLMError):
        select_backend("nope")


@pytest.mark.live_llm
def test_claude_cli_live_structured():
    be = ClaudeCliBackend(models={"fast": "sonnet"})
    resp = be.complete(
        LLMRequest(
            prompt="Return the sum of 2 and 3.",
            tier="fast",
            json_schema={
                "type": "object",
                "properties": {"sum": {"type": "integer"}},
                "required": ["sum"],
            },
            tag="live",
        )
    )
    assert resp.structured == {"sum": 5}
