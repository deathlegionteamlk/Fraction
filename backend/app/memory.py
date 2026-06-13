"""Memory system.

Two layers:
  - Short-term: per-session list of recent messages (capped).
  - Long-term:  vector store + structured facts, persisted to disk.

Embeddings are best-effort: if the configured embedding provider is offline,
we fall back to a hashed-bag-of-words vector so the system still works.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config

log = logging.getLogger("fraction.memory")


# ---- short-term (per-session) ----------------------------------------------


@dataclass
class ShortTermMemory:
    session_id: str
    messages: deque = field(default_factory=lambda: deque(maxlen=50))

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content, "ts": time.time()})

    def to_list(self) -> list[dict[str, str]]:
        return [{"role": m["role"], "content": m["content"]} for m in self.messages]


# ---- simple fallback embedding ---------------------------------------------


def _hash_embed(text: str, dim: int = 384) -> list[float]:
    """Deterministic, dependency-free fallback embedding (BoW + hashing)."""
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---- long-term store --------------------------------------------------------


class LongTermMemory:
    def __init__(self, path: str, collection: str = "fraction_memories"):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection = collection
        self._items: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        fp = self.path / f"{self.collection}.jsonl"
        if not fp.exists():
            return
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                self._items.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _persist(self) -> None:
        fp = self.path / f"{self.collection}.jsonl"
        with fp.open("w", encoding="utf-8") as f:
            for it in self._items:
                f.write(json.dumps(it) + "\n")

    def add(self, text: str, kind: str = "episode", metadata: dict[str, Any] | None = None) -> None:
        emb = _hash_embed(text)
        item = {
            "id": hashlib.sha1((text + str(time.time())).encode()).hexdigest()[:16],
            "text": text,
            "kind": kind,
            "metadata": metadata or {},
            "embedding": emb,
            "ts": time.time(),
        }
        self._items.append(item)
        # cap to 10k items
        if len(self._items) > 10_000:
            self._items = self._items[-10_000:]
        self._persist()

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if not self._items:
            return []
        q = _hash_embed(query)
        scored = sorted(
            ((_cosine(q, it["embedding"]), it) for it in self._items if "embedding" in it),
            key=lambda x: x[0],
            reverse=True,
        )
        return [it for _, it in scored[:k] if _cosine(q, it["embedding"]) > 0.05]

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        return list(self._items[-n:])


# ---- memory manager ---------------------------------------------------------


class MemoryManager:
    """Coordinates short-term and long-term memory for the running app."""

    def __init__(self):
        cfg = get_config().memory
        self.short: dict[str, ShortTermMemory] = {}
        self.long = LongTermMemory(cfg.long_term.path, cfg.long_term.collection)

    def session(self, sid: str) -> ShortTermMemory:
        if sid not in self.short:
            self.short[sid] = ShortTermMemory(session_id=sid)
        return self.short[sid]

    def remember_episode(self, goal: str, summary: str, success: bool) -> None:
        self.long.add(
            f"GOAL: {goal}\nOUTCOME: {'success' if success else 'failure'}\nSUMMARY: {summary}",
            kind="episode",
            metadata={"goal": goal, "success": success},
        )

    def recall(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        return self.long.search(query, k=k)

    def facts(self) -> list[dict[str, Any]]:
        """Return the most recent structured facts."""
        return [it for it in self.long.recent(50) if it.get("kind") == "fact"]

    def add_fact(self, fact: str) -> None:
        self.long.add(fact, kind="fact")
