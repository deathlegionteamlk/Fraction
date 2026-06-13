"""Tools available to Fraction agents.

Each tool is a plain async function with a stable name, a JSON-schema-ish
description, and a single `run(**kwargs) -> str` entrypoint. The agent loop
asks the model to pick a tool by name, then dispatches here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .config import get_config

log = logging.getLogger("fraction.tools")


# ---- tool registry ----------------------------------------------------------


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Any


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def list_for_prompt(self) -> list[dict[str, Any]]:
        """Return a JSON-serializable list of tool schemas for the model."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    async def call(self, name: str, **kwargs) -> str:
        if name not in self._tools:
            return f"[tool error: unknown tool {name!r}]"
        try:
            t = self._tools[name]
            if asyncio.iscoroutinefunction(t.func):
                return await t.func(**kwargs)
            return await asyncio.to_thread(t.func, **kwargs)
        except Exception as e:  # noqa: BLE001
            log.exception("Tool %s failed", name)
            return f"[tool error: {e}]"


# ---- tool implementations ---------------------------------------------------


async def web_search(query: str, max_results: int | None = None) -> str:
    cfg = get_config().tools.web_search
    if not cfg.enabled:
        return "web_search disabled in config"
    n = max_results or cfg.max_results
    provider = cfg.provider
    if provider == "duckduckgo":
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                hits = list(ddgs.text(query, max_results=n))
            lines = [f"- [{h['title']}]({h['href']}): {h['body']}" for h in hits]
            return "\n".join(lines) or "(no results)"
        except Exception as e:  # noqa: BLE001
            return f"[duckduckgo error: {e}]"
    return f"[web_search provider {provider!r} not implemented]"


async def web_fetch(url: str) -> str:
    cfg = get_config().tools.web_fetch
    if not cfg.enabled:
        return "web_fetch disabled in config"
    try:
        async with httpx.AsyncClient(
            timeout=cfg.timeout_seconds, follow_redirects=True
        ) as client:
            r = await client.get(url, headers={"User-Agent": "Fraction/0.1"})
            r.raise_for_status()
            if len(r.content) > cfg.max_bytes:
                r._content = r.content[: cfg.max_bytes]
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text("\n", strip=True)
            return f"URL: {url}\n\n{text[:8000]}"
    except Exception as e:  # noqa: BLE001
        return f"[web_fetch error: {e}]"


def _resolve_under(base: Path, target: str) -> Path:
    p = (base / target).resolve() if not os.path.isabs(target) else Path(target).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise ValueError(f"path {target!r} escapes allowed base {base}")
    return p


WORKSPACE_ROOT = Path(__file__).resolve().parents[2] / "workspaces"
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


async def file_write(path: str, content: str) -> str:
    cfg = get_config().tools.file_io
    if not cfg.enabled:
        return "file_io disabled"
    p = _resolve_under(WORKSPACE_ROOT, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {p}"


async def file_read(path: str) -> str:
    p = _resolve_under(WORKSPACE_ROOT, path)
    if not p.exists():
        return f"(file not found: {p})"
    return p.read_text(encoding="utf-8", errors="replace")


async def file_list(glob: str = "*") -> str:
    files = sorted(WORKSPACE_ROOT.glob(glob))
    return "\n".join(str(p.relative_to(WORKSPACE_ROOT)) for p in files) or "(empty)"


async def code_exec(language: str, code: str, timeout_seconds: int = 30) -> str:
    """Execute code locally. For production, route this to the sandbox service.

    Supported languages: python, bash, node (if installed).
    """
    cfg = get_config()
    if not cfg.tools.code_exec.enabled:
        return "code_exec disabled"

    timeout = min(timeout_seconds, cfg.sandbox.max_timeout_seconds)
    runners = {
        "python": ["python3", "-c"],
        "bash": ["bash", "-c"],
        "node": ["node", "-e"],
    }
    cmd = runners.get(language.lower())
    if not cmd:
        return f"[unsupported language: {language}]"

    if shutil.which(cmd[0]) is None and language.lower() != "python":
        return f"[{cmd[0]} not installed in this environment]"

    with tempfile.NamedTemporaryFile("w", suffix=f".{language}", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, tmp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"[timeout after {timeout}s]"
        out = stdout.decode("utf-8", "replace")[:8000]
        err = stderr.decode("utf-8", "replace")[:2000]
        rc = proc.returncode
        return f"exit={rc}\nstdout:\n{out}\nstderr:\n{err}".strip()
    finally:
        os.unlink(tmp)


# ---- build default registry --------------------------------------------------


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolDef(
        name="web_search",
        description="Search the public web for a query and return top results with snippets.",
        parameters={"query": "string", "max_results": "int?"},
        func=web_search,
    ))
    reg.register(ToolDef(
        name="web_fetch",
        description="Fetch a URL and return its main text content (scripts/styles stripped).",
        parameters={"url": "string"},
        func=web_fetch,
    ))
    reg.register(ToolDef(
        name="file_write",
        description="Write text content to a file inside the workspace.",
        parameters={"path": "string", "content": "string"},
        func=file_write,
    ))
    reg.register(ToolDef(
        name="file_read",
        description="Read a text file from the workspace.",
        parameters={"path": "string"},
        func=file_read,
    ))
    reg.register(ToolDef(
        name="file_list",
        description="List files in the workspace matching a glob.",
        parameters={"glob": "string?"},
        func=file_list,
    ))
    reg.register(ToolDef(
        name="code_exec",
        description="Run a short snippet of Python/Bash/Node locally. Use for quick calculations and data wrangling.",
        parameters={"language": "string", "code": "string", "timeout_seconds": "int?"},
        func=code_exec,
    ))
    return reg
