"""Run configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RepairPolicy:
    deterministic_attempts: int = 3  # repairs driven by Tier 0/1 findings
    visual_attempts: int = 1  # repairs driven by Tier 2 critique
    max_llm_calls_per_concept: int = 6
    abort_on_repeated_category: bool = True
    fallback_to_template: bool = True


@dataclass
class RunConfig:
    backend: str | None = None  # claude-cli | anthropic | fake | None=auto
    models: dict[str, str] = field(default_factory=dict)  # tier -> model override
    effort: dict[str, str] = field(default_factory=dict)  # tier -> low|medium|high (claude-cli)
    quality: str = "m"  # l | m | h
    max_plans: int | None = 4
    audience: str = "mixed"
    min_salience: int = 3
    constraints: list[str] = field(default_factory=list)
    allow_3d: bool = False
    critique: bool = True
    workers: int = 2
    gif_width: int = 960
    gif_fps: int = 20
    repair: RepairPolicy = field(default_factory=RepairPolicy)
    probe_pixel_height: int = 720
    input_kind: str | None = None
    max_pages: int | None = None
    title: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
