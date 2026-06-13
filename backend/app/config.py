"""Configuration loader for Fraction.

Reads `config/fraction.yaml` and resolves ${ENV_VAR} placeholders from the
process environment, so users can keep secrets out of the config file.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _resolve_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    return value


class AppConfig(BaseModel):
    name: str = "Fraction"
    owner: str = "death legion team"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


class ProviderConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    models: list[str] = Field(default_factory=list)
    default: str = ""
    free: bool = False


class AgentsConfig(BaseModel):
    max_steps_per_task: int = 25
    max_parallel_subtasks: int = 4
    step_timeout_seconds: int = 180
    enable_self_critique: bool = True
    enable_replanner: bool = True


class SandboxConfig(BaseModel):
    enabled: bool = True
    runtime: str = "docker"
    image: str = "fraction-sandbox:latest"
    cpu_limit: str = "1.0"
    memory_limit: str = "1g"
    network: str = "restricted"
    default_timeout_seconds: int = 60
    max_timeout_seconds: int = 300
    workspace_mount: str = "./sandbox/workspaces"


class MemoryConfig(BaseModel):
    class ShortTerm(BaseModel):
        max_messages: int = 50

    class LongTerm(BaseModel):
        backend: str = "chroma"
        path: str = "./memory/store"
        collection: str = "fraction_memories"
        embedding_provider: str = "ollama"
        embedding_model: str = "nomic-embed-text"

    class Reflection(BaseModel):
        enabled: bool = True
        min_episodes_to_reflect: int = 5

    short_term: ShortTerm = Field(default_factory=ShortTerm)
    long_term: LongTerm = Field(default_factory=LongTerm)
    reflection: Reflection = Field(default_factory=Reflection)


class ToolsConfig(BaseModel):
    class WebSearch(BaseModel):
        enabled: bool = True
        provider: str = "duckduckgo"
        api_key: str = ""
        max_results: int = 8

    class WebFetch(BaseModel):
        enabled: bool = True
        max_bytes: int = 2_000_000
        timeout_seconds: int = 20

    class FileIO(BaseModel):
        enabled: bool = True
        allowed_paths: list[str] = Field(default_factory=list)

    class CodeExec(BaseModel):
        enabled: bool = True

    class ImageGen(BaseModel):
        enabled: bool = False
        provider: str = "openai"

    class Speech(BaseModel):
        enabled: bool = False
        provider: str = "openai"

    web_search: WebSearch = Field(default_factory=WebSearch)
    web_fetch: WebFetch = Field(default_factory=WebFetch)
    file_io: FileIO = Field(default_factory=FileIO)
    code_exec: CodeExec = Field(default_factory=CodeExec)
    image_gen: ImageGen = Field(default_factory=ImageGen)
    speech: Speech = Field(default_factory=Speech)


class FractionConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)


def load_config(path: str | Path | None = None) -> FractionConfig:
    """Load and validate the Fraction config file.

    Lookup order:
      1. Explicit `path` argument
      2. $FRACTION_CONFIG environment variable
      3. ./config/fraction.yaml
      4. ./config/fraction.yaml.example
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    if env := os.environ.get("FRACTION_CONFIG"):
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "config" / "fraction.yaml")
    candidates.append(here.parents[2] / "config" / "fraction.yaml.example")

    for c in candidates:
        if c.exists():
            raw = yaml.safe_load(c.read_text(encoding="utf-8")) or {}
            raw = _resolve_env(raw)
            return FractionConfig.model_validate(raw)

    # No file found — return sane defaults so the service can still boot.
    return FractionConfig()


# Singleton accessor ----------------------------------------------------------
_cached: FractionConfig | None = None


def get_config(reload: bool = False) -> FractionConfig:
    global _cached
    if _cached is None or reload:
        _cached = load_config()
    return _cached
