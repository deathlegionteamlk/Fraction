"""Fraction sandbox service.

Runs in its own container, isolated from the backend. Exposes a single
endpoint: POST /run with {language, code, timeout}. Spins up a one-shot
sub-container (or runs in-process with strict timeouts if Docker-in-Docker
isn't available), enforces CPU/memory limits, and returns stdout/stderr.

Network: "restricted" by default — we attach the sandbox to an internal
bridge with no egress to the host network. Flip to "full" in the
backend's fraction.yaml if you want outbound HTTP.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("fraction.sandbox")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [sandbox] %(message)s")


SANDBOX_WORKSPACE = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace/_sandbox_runs"))
SANDBOX_WORKSPACE.mkdir(parents=True, exist_ok=True)

DOCKER_BIN = shutil.which("docker")


class RunRequest(BaseModel):
    language: str
    code: str
    timeout_seconds: int = 30


app = FastAPI(title="Fraction Sandbox", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "fraction-sandbox",
        "docker_available": DOCKER_BIN is not None,
        "workspace": str(SANDBOX_WORKSPACE),
    }


async def _run_in_docker(language: str, code: str, timeout: int) -> dict[str, Any]:
    if not DOCKER_BIN:
        raise RuntimeError("docker binary not available in sandbox container")

    # Write code to a tmp file
    suffix = {"python": ".py", "bash": ".sh", "node": ".js"}.get(language, ".txt")
    tmpdir = SANDBOX_WORKSPACE / uuid.uuid4().hex
    tmpdir.mkdir(parents=True, exist_ok=True)
    codefile = tmpdir / f"main{suffix}"
    codefile.write_text(code, encoding="utf-8")

    images = {
        "python": "python:3.12-alpine",
        "bash": "alpine:3.20",
        "node": "node:20-alpine",
    }
    image = images.get(language)
    if not image:
        raise ValueError(f"unsupported language: {language}")

    cmd = [
        DOCKER_BIN, "run", "--rm",
        "--network", "none",
        "--cpus", "1.0",
        "--memory", "512m",
        "--pids-limit", "128",
        "-v", f"{codefile}:/code/main{suffix}:ro",
        "-w", "/code",
        image,
        *_runner_cmd(language, suffix),
    ]

    t0 = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        rc = proc.returncode
    except asyncio.TimeoutError:
        proc.kill()  # type: ignore[possibly-undefined]
        return {
            "ok": False, "exit": -1,
            "stdout": "", "stderr": f"timeout after {timeout}s",
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "ok": rc == 0,
        "exit": rc,
        "stdout": stdout.decode("utf-8", "replace")[:20_000],
        "stderr": stderr.decode("utf-8", "replace")[:5_000],
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }


def _runner_cmd(language: str, suffix: str) -> list[str]:
    if language == "python":
        return ["python", f"/code/main{suffix}"]
    if language == "bash":
        return ["sh", f"/code/main{suffix}"]
    if language == "node":
        return ["node", f"/code/main{suffix}"]
    raise ValueError(language)


# Fallback in-process execution if Docker isn't available inside the sandbox
# (e.g. when running locally on macOS/Windows without Docker Desktop's docker
# socket mount). This is *less* isolated but keeps the system usable.


IN_PROCESS_RUNNERS = {
    "python": ["python3", "-c"],
    "bash": ["bash", "-c"],
}


async def _run_in_process(language: str, code: str, timeout: int) -> dict[str, Any]:
    runner = IN_PROCESS_RUNNERS.get(language)
    if not runner:
        raise HTTPException(400, detail=f"unsupported language in fallback mode: {language}")
    if shutil.which(runner[0]) is None:
        raise HTTPException(500, detail=f"{runner[0]} not installed in sandbox")

    t0 = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *runner, code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        rc = proc.returncode
    except asyncio.TimeoutError:
        proc.kill()  # type: ignore[possibly-undefined]
        return {
            "ok": False, "exit": -1, "stdout": "", "stderr": f"timeout after {timeout}s",
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }
    return {
        "ok": rc == 0, "exit": rc,
        "stdout": stdout.decode("utf-8", "replace")[:20_000],
        "stderr": stderr.decode("utf-8", "replace")[:5_000],
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }


@app.post("/run")
async def run_code(req: RunRequest) -> dict[str, Any]:
    timeout = min(max(req.timeout_seconds, 1), 300)
    try:
        if DOCKER_BIN and os.environ.get("SANDBOX_USE_DOCKER", "1") == "1":
            return await _run_in_docker(req.language, req.code, timeout)
        return await _run_in_process(req.language, req.code, timeout)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("sandbox run failed")
        raise HTTPException(500, detail=str(e))
