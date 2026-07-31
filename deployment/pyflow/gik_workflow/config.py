"""Workflow config — one YAML per pipeline, parsed into typed objects."""
from dataclasses import dataclass, field
from typing import Optional, List
import yaml


@dataclass
class Stage:
    name: str
    title: str
    kind: str
    endpoint: Optional[str] = None   # None => stub task (Phase 3 placeholder)
    timeout: int = 300


@dataclass
class WorkflowConfig:
    suite: str
    schedule: str
    run: str
    executor: str
    stages: List[Stage] = field(default_factory=list)


def load_config(path) -> WorkflowConfig:
    raw = yaml.safe_load(open(path))
    stages = [Stage(name=s["name"], title=s["title"], kind=s["kind"],
                    endpoint=s.get("endpoint"), timeout=int(s.get("timeout", 300)))
              for s in raw["stages"]]
    return WorkflowConfig(suite=raw["suite"], schedule=str(raw.get("schedule") or ""),
                          run=str(raw["run"]), executor=raw["executor"], stages=stages)
