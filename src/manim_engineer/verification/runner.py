"""Sandboxed probe worker: child process with rlimits, compact failure records."""

from __future__ import annotations

import json
import linecache
import multiprocessing as mp
import os
import queue
import resource
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

LIMITS = {"wall_s": 180, "cpu_s": 150, "mem_gb": 6}


def _apply_limits() -> None:
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (LIMITS["cpu_s"], LIMITS["cpu_s"]))
        b = LIMITS["mem_gb"] * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (b, b))
        resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024**2, 512 * 1024**2))
    except (ValueError, OSError):  # pragma: no cover
        pass


def classify(exc: BaseException, tb_text: str) -> str:
    low = tb_text.lower()
    if "latex" in low or "dvisvgm" in low or "tex_file_writing" in low:
        return "latex"
    if isinstance(exc, AttributeError | NameError | TypeError):
        return "api"
    if isinstance(exc, SyntaxError | IndentationError | ImportError):
        return "python"
    if isinstance(exc, ValueError | IndexError | KeyError | ZeroDivisionError):
        return "value"
    return "manim_runtime"


def condense(exc: BaseException, candidate_path: str, ctx: int = 2) -> dict[str, Any]:
    frames = []
    tb = traceback.extract_tb(exc.__traceback__)
    for fr in tb:
        if os.path.abspath(fr.filename) == os.path.abspath(candidate_path):
            src = [
                f"{n:>4} | {linecache.getline(fr.filename, n).rstrip()}"
                for n in range(max(1, fr.lineno - ctx), fr.lineno + ctx + 1)
            ]
            frames.append({"line": fr.lineno, "func": fr.name, "source": "\n".join(src)})
    last = tb[-1] if tb else None
    return {
        "category": classify(exc, "".join(traceback.format_exception(exc))),
        "error": f"{type(exc).__name__}: {exc}"[:600],
        "line": frames[-1]["line"] if frames else None,
        "user_frames": frames[-2:],
        "manim_frame": f"{os.path.basename(last.filename)}:{last.lineno} in {last.name}"
        if last
        else "",
    }


def _child(path: str, cls_name: str, q: mp.Queue) -> None:  # pragma: no cover - runs in subprocess
    _apply_limits()
    try:
        from manim_engineer.verification.probe import load_scene, probe

        cls = load_scene(path, cls_name)
        frames = probe(cls)
        q.put(
            {
                "ok": True,
                "duration_s": frames[-1].t if frames else 0.0,
                "frames": [asdict(f) for f in frames],
            }
        )
    except MemoryError:
        q.put(
            {
                "ok": False,
                "category": "oom",
                "error": "memory limit exceeded while probing the scene",
                "line": None,
            }
        )
    except BaseException as e:  # noqa: BLE001
        q.put({"ok": False, **condense(e, path)})


def run_probe(path: str | Path, cls_name: str, wall_s: int | None = None) -> dict[str, Any]:
    """Probe in a sandboxed child; returns {'ok', 'frames'|'category','error',...}."""
    # spawn, not fork: a parent that loaded CUDA (faster-whisper) or a large heap must not
    # hand that address space to a child that runs under RLIMIT_AS.
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    p = ctx.Process(target=_child, args=(str(path), cls_name, q))
    p.start()
    timeout = wall_s or LIMITS["wall_s"]
    result: dict[str, Any] | None = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = q.get(timeout=1.0)
            break
        except queue.Empty:
            if not p.is_alive():
                break  # child died without reporting (MemoryError, segfault, oom-kill)
    p.join(5)
    if p.is_alive():
        p.kill()
        p.join()
        return {
            "ok": False,
            "category": "timeout",
            "error": f"probe exceeded {timeout}s wall clock",
            "line": None,
        }
    if result is None:
        return {
            "ok": False,
            "category": "crash",
            "error": f"probe worker died (exit {p.exitcode})",
            "line": None,
        }
    return result


def run_probe_inline(path: str | Path, cls_name: str) -> dict[str, Any]:
    """Same as run_probe but in-process (for tests and debugging)."""
    from manim import tempconfig

    from manim_engineer.verification.probe import load_scene, probe

    # importing a scene can set Manim's TeX template (use_source_preamble); leaving
    # tempconfig resets it, even when the import itself fails afterwards
    with tempconfig({}):
        try:
            frames = probe(load_scene(path, cls_name))
            return {
                "ok": True,
                "duration_s": frames[-1].t if frames else 0.0,
                "frames": [asdict(f) for f in frames],
            }
        except BaseException as e:  # noqa: BLE001
            return {"ok": False, **condense(e, str(path))}


def frames_from_result(result: dict[str, Any]):
    from manim_engineer.verification.probe import Box, Keyframe

    out = []
    for f in result.get("frames", []):
        boxes = [Box(**b) for b in f["boxes"]]
        out.append(
            Keyframe(
                index=f["index"],
                t=f["t"],
                run_time=f["run_time"],
                section=f["section"],
                anim=f["anim"],
                boxes=boxes,
                n_mobjects=f.get("n_mobjects", 0),
            )
        )
    return out


def dumps(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=1, default=str)
