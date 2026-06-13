#!/usr/bin/env python3
"""Fraction CLI — minimal management commands for the stack.

Examples:
    python scripts/fractionctl.py config              # show the active config
    python scripts/fractionctl.py providers           # list providers + which have keys
    python scripts/fractionctl.py goal "research X"   # run a goal via the running backend
    python scripts/fractionctl.py memory              # dump long-term memory
    python scripts/fractionctl.py deliverables        # list deliverables
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

BACKEND = os.environ.get("FRACTION_BACKEND", "http://localhost:8000")


def cmd_config() -> None:
    from app.config import get_config
    cfg = get_config()
    print(json.dumps(json.loads(cfg.model_dump_json()), indent=2))


def cmd_providers() -> None:
    from app.config import get_config
    cfg = get_config()
    for name, p in cfg.providers.items():
        flag = "ON " if p.enabled else "off"
        key = "key set" if (p.api_key and "${" not in p.api_key and p.api_key != "ollama") else "no key"
        free = " (FREE)" if p.free else ""
        print(f"[{flag}] {name:14} {key:10} default={p.default:30} models={len(p.models)}{free}")


def cmd_goal(goal: str, stream: bool = True) -> None:
    import httpx
    r = httpx.post(f"{BACKEND}/api/goal", json={"goal": goal}, timeout=30)
    r.raise_for_status()
    sid = r.json()["session_id"]
    print(f"session={sid}\n")
    if not stream:
        return
    with httpx.stream("GET", f"{BACKEND}/api/stream/{sid}", timeout=None) as resp:
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            t = ev.get("type", "")
            r = ev.get("role", "")
            c = ev.get("content", "")
            if t == "message":
                print(f"[{r}] {c}")
            elif t == "plan":
                print(f"[plan] {c}")
                for s in (ev.get("data") or {}).get("plan") or []:
                    print(f"   - {s.get('title')} [{s.get('kind')}]")
            elif t == "step":
                print(f"[step] {c}")
            elif t == "result":
                print(f"[review] {c}")
            elif t == "deliverable":
                print(f"\n--- deliverable {ev['data'].get('id')} ---\n")
                print(c)
                print("\n--- end ---\n")
            elif t == "error":
                print(f"[ERROR] {c}")
            elif t == "done":
                print("[done]")


def cmd_memory() -> None:
    import httpx
    r = httpx.get(f"{BACKEND}/api/memory?limit=30", timeout=10)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


def cmd_deliverables() -> None:
    import httpx
    r = httpx.get(f"{BACKEND}/api/deliverables", timeout=10)
    r.raise_for_status()
    for it in r.json()["items"]:
        print(f"  {it['id']}  {(it['size']/1024):.1f}kb  {it['preview'][:80]}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd = sys.argv[1]
    if cmd == "config":
        cmd_config()
    elif cmd == "providers":
        cmd_providers()
    elif cmd == "goal":
        if len(sys.argv) < 3:
            print("usage: fractionctl.py goal '<goal>'"); sys.exit(2)
        cmd_goal(" ".join(sys.argv[2:]))
    elif cmd == "memory":
        cmd_memory()
    elif cmd == "deliverables":
        cmd_deliverables()
    else:
        print(f"unknown command: {cmd}"); sys.exit(2)


if __name__ == "__main__":
    main()
