"""Claude CLI backend: drives `claude -p` headlessly with the user's login.

Verified on this machine: `--output-format json` returns a result object,
`--json-schema` yields `structured_output`, and `--allowedTools Read` lets the
model open PNG files for vision critique. No API key required.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from manim_engineer.llm.backend import CallLog, LLMError, LLMRequest, LLMResponse, ModelTier

DEFAULT_MODELS: dict[str, str] = {"fast": "sonnet", "strong": "opus", "vision": "sonnet"}
# Extended thinking is on by default in the CLI; "low" cuts codegen latency 3-4x with no MCP context.
DEFAULT_EFFORT: dict[str, str] = {"fast": "low", "strong": "low", "vision": "low"}
NO_MCP = '{"mcpServers":{}}'


class ClaudeCliBackend:
    name = "claude-cli"

    def __init__(
        self,
        models: dict[str, str] | None = None,
        log: CallLog | None = None,
        executable: str = "claude",
        retries: int = 2,
        workdir: Path | None = None,
        effort: dict[str, str] | None = None,
    ):
        self.models = {**DEFAULT_MODELS, **(models or {})}
        self.effort = {**DEFAULT_EFFORT, **(effort or {})}
        self.log = log or CallLog(None)
        self.executable = executable
        self.retries = retries
        self.workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="me-claude-"))
        self.workdir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def available(executable: str = "claude") -> bool:
        return shutil.which(executable) is not None

    def model_for(self, tier: ModelTier) -> str:
        return self.models[tier]

    # ------------------------------------------------------------------ argv
    def build_argv(self, req: LLMRequest, system_file: Path | None) -> list[str]:
        argv = [
            self.executable,
            "-p",
            "--model",
            self.model_for(req.tier),
            "--output-format",
            "json",
            "--no-session-persistence",
            "--effort",
            self.effort.get(req.tier, "low"),
            "--strict-mcp-config",
            "--mcp-config",
            NO_MCP,
        ]
        if system_file is not None:
            argv += ["--system-prompt-file", str(system_file)]
        if req.json_schema is not None:
            argv += ["--json-schema", json.dumps(req.json_schema)]
        if req.images:
            argv += ["--allowedTools", "Read", "--max-turns", str(3 + len(req.images))]
        else:
            argv += ["--tools", "", "--max-turns", "2"]
        return argv

    @staticmethod
    def build_prompt(req: LLMRequest) -> str:
        if not req.images:
            return req.prompt
        listing = "\n".join(f"- {os.path.abspath(p)}" for p in req.images)
        return (
            "Before answering, use the Read tool to open each of these image files and look at them:\n"
            f"{listing}\n\n{req.prompt}"
        )

    # ------------------------------------------------------------------ call
    def complete(self, req: LLMRequest) -> LLMResponse:
        last_err: str | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self._once(req)
                self.log.record(self.name, req, resp)
                return resp
            except LLMError as e:
                last_err = str(e)
                if "timed out" in last_err:
                    break  # a timeout will not get better on retry
                if attempt < self.retries:
                    time.sleep(2 * (attempt + 1))
        self.log.record(self.name, req, None, error=last_err)
        raise LLMError(last_err or "claude cli failed")

    def _once(self, req: LLMRequest) -> LLMResponse:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        system_file: Path | None = None
        if req.system:
            fd, name = tempfile.mkstemp(prefix="system-", suffix=".md", dir=self.workdir)
            with os.fdopen(fd, "w") as fh:
                fh.write(req.system)
            system_file = Path(name)
        argv = self.build_argv(req, system_file)
        t0 = time.time()
        try:
            proc = subprocess.run(
                argv,
                input=self.build_prompt(req),
                capture_output=True,
                text=True,
                env=env,
                cwd=self.workdir,
                timeout=req.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude cli timed out after {req.timeout_s}s") from e
        finally:
            if system_file is not None:
                system_file.unlink(missing_ok=True)
        dt = time.time() - t0
        if proc.returncode != 0:
            raise LLMError(
                f"claude cli exit {proc.returncode}: {(proc.stderr or proc.stdout)[-800:]}"
            )
        return self.parse_result(proc.stdout, dt)

    @staticmethod
    def parse_result(stdout: str, duration_s: float) -> LLMResponse:
        try:
            data: dict[str, Any] = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"claude cli returned non-JSON: {stdout[-400:]}") from e
        if data.get("is_error") or data.get("subtype") not in (None, "success"):
            raise LLMError(
                f"claude cli error: {data.get('subtype')}: {str(data.get('result'))[:400]}"
            )
        text = data.get("result") or ""
        structured = data.get("structured_output")
        usage = data.get("usage") or {}
        model_usage = data.get("modelUsage") or {}
        model = ""
        if isinstance(model_usage, dict) and model_usage:
            # prefer the non-haiku model (haiku is used for internal bookkeeping)
            models = [m for m in model_usage if "haiku" not in m] or list(model_usage)
            model = models[0]
        return LLMResponse(
            text=text if isinstance(text, str) else json.dumps(text),
            structured=structured if isinstance(structured, dict) else None,
            model=model,
            duration_s=duration_s,
            usage=usage,
            cost_usd=data.get("total_cost_usd"),
            raw={k: v for k, v in data.items() if k not in ("result", "structured_output")},
        )
