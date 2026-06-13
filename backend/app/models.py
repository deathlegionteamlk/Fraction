"""Model router.

Resolves a `model_id` to a concrete provider, sends chat-completion requests,
and handles automatic fallback across providers. Supports any OpenAI-compatible
endpoint, plus the Anthropic native format.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .config import FractionConfig, ProviderConfig, get_config

log = logging.getLogger("fraction.models")


@dataclass
class ChatMessage:
    role: str
    content: str

    def to_openai(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    model: str = ""               # e.g. "openai/gpt-4o-mini" or "groq/llama-3.3-70b-versatile"
    temperature: float = 0.4
    max_tokens: int = 2048
    json_mode: bool = False


@dataclass
class ChatResponse:
    content: str
    provider: str
    model: str
    usage: dict[str, int]
    latency_ms: int


class ModelRouter:
    """Routes chat requests to whichever provider has the requested model."""

    def __init__(self, cfg: FractionConfig | None = None):
        self.cfg = cfg or get_config()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        # Build a quick lookup: model_id -> (provider_name, ProviderConfig)
        self._index: dict[str, tuple[str, ProviderConfig]] = {}
        for name, p in self.cfg.providers.items():
            if not p.enabled:
                continue
            for m in p.models:
                self._index[m] = (name, p)
                self._index[f"{name}/{m}"] = (name, p)

    def resolve(self, model_hint: str = "") -> tuple[str, ProviderConfig]:
        """Resolve a model hint to (provider_name, ProviderConfig)."""
        # Empty hint -> global default (first enabled provider with a default)
        if not model_hint:
            for name, p in self.cfg.providers.items():
                if p.enabled and p.default:
                    return name, p
            raise RuntimeError("No enabled providers with a default model configured")

        # Exact match in index
        if model_hint in self._index:
            return self._index[model_hint]

        # Try as bare model id
        for mid, (name, p) in self._index.items():
            if mid.split("/")[-1] == model_hint:
                return name, p

        # Last resort: any enabled provider's default
        for name, p in self.cfg.providers.items():
            if p.enabled and p.default:
                log.warning("Model %r not found, falling back to %s/%s", model_hint, name, p.default)
                return name, p
        raise RuntimeError(f"Model {model_hint!r} not configured and no default available")

    async def chat(self, req: ChatRequest) -> ChatResponse:
        provider_name, provider = self.resolve(req.model)
        model_id = req.model.split("/")[-1] if "/" in req.model else (req.model or provider.default)

        # Try primary, then fallbacks
        tried: set[str] = set()
        order = [provider_name] + [n for n in self.cfg.providers if n != provider_name]
        last_err: Exception | None = None
        for name in order:
            if name in tried:
                continue
            p = self.cfg.providers.get(name)
            if not p or not p.enabled:
                continue
            tried.add(name)
            try:
                return await self._call_openai_compat(name, p, model_id, req)
            except Exception as e:  # noqa: BLE001
                log.warning("Provider %s failed: %s — trying next", name, e)
                last_err = e
        raise RuntimeError(f"All providers failed. Last error: {last_err}")

    async def _call_openai_compat(
        self, name: str, p: ProviderConfig, model_id: str, req: ChatRequest
    ) -> ChatResponse:
        url = p.base_url.rstrip("/") + "/chat/completions"
        body: dict[str, Any] = {
            "model": model_id,
            "messages": [m.to_openai() for m in req.messages],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if p.api_key and p.api_key != "ollama":
            headers["Authorization"] = f"Bearer {p.api_key}"

        t0 = time.perf_counter()
        r = await self._client.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"{name} HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return ChatResponse(
            content=content,
            provider=name,
            model=model_id,
            usage=data.get("usage", {}),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[str]:
        """Yield text chunks. Falls back to non-streaming chat if a provider can't stream."""
        try:
            resp = await self.chat(req)
            for chunk in resp.content.split(" "):
                yield chunk + " "
                await asyncio.sleep(0)
        except Exception as e:  # noqa: BLE001
            yield f"[stream error: {e}]"

    async def close(self) -> None:
        await self._client.aclose()


# -----------------------------------------------------------------------------


def resolve_for_role(role: str, router: ModelRouter, cfg: FractionConfig) -> str:
    """Pick a model string for a given agent role, honoring role overrides."""
    override = cfg.roles.get(role, "").strip()
    if override:
        return override
    # else empty -> router uses default
    return ""
