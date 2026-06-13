# Fraction — Architecture

Fraction is a multi-agent AI framework. A high-level goal ("research the
current state of quantum computing and write a summary report") flows through
a small team of specialized agents that share tools, memory, and a sandbox.

## Agent roles

| Role       | What it does                                                              |
|------------|---------------------------------------------------------------------------|
| Planner    | Decomposes the goal into 3–8 steps (JSON), each tagged `research` / `code` / `analysis` / `write` / `review`. |
| Researcher | Calls `web_search` and `web_fetch` to gather and cite sources.             |
| Coder      | Writes and runs code in the sandbox (Python/Bash/Node).                   |
| Reviewer   | Judges each step's output; asks for revisions if not on-task.             |
| Writer     | Assembles all step outputs into a final Markdown deliverable.             |
| Reflector  | Writes a 2–3 sentence reflection back to long-term memory.               |

The Orchestrator (`backend/app/agents.py`) wires these together with an
async event loop, streaming events to the UI over Server-Sent Events.

## Container layout

```
            ┌────────────┐    HTTP    ┌──────────────┐
  browser → │  frontend  │ ─────────► │   backend    │ ◄──┐
            │  (nginx)   │            │  (FastAPI)   │    │
            └────────────┘   SSE ◄──  │ Orchestrator │    │
                          :3000       │ Model router │    │
                                       └──────┬───────┘    │
                                              │            │
                                  tools &     │            │ LLM API
                                  memory      ▼            ▼
                                       ┌──────────────┐  (OpenAI, Anthropic,
                                       │   sandbox    │   Google, Groq,
                                       │  (FastAPI)   │   OpenRouter, …)
                                       │  Docker CLI  │
                                       └──────────────┘
```

- `frontend` — static SPA served by nginx; reverse-proxies `/api/*` to the
  backend. This is the only port you need to expose to the host (3000).
- `backend` — the orchestrator, model router, tools, and long-term memory.
- `sandbox` — a tiny service that runs user code in one-shot containers
  with `--network none`, tight CPU/memory limits, and a per-run timeout.
- `ollama` (optional) — local model provider; uncomment in `docker-compose.yml`.

## Memory

Two layers (`backend/app/memory.py`):

- **Short-term** — a per-session `deque` of recent messages, capped at 50.
- **Long-term** — a JSONL store of episodes and facts, with a hashed-BoW
  embedding so search works offline. A real vector backend (Chroma/Qdrant)
  can be plugged in by replacing the `LongTermMemory` class.

When a new goal starts, the planner is shown the top-3 most relevant
past episodes so the system can lean on prior experience.

## Pluggable models

`backend/app/models.py` is a thin router over OpenAI-compatible APIs. Set
`enabled: true` and an `api_key` in `config/fraction.yaml` for any
provider and it just works:

- **OpenAI** — `gpt-4o`, `gpt-4o-mini`, `o3-mini`
- **Anthropic** — `claude-sonnet-4-5`, `claude-haiku-4-5`
- **Google Gemini** — free tier via AI Studio
- **Groq** — very fast, generous free tier
- **OpenRouter** — one key, dozens of free models
- **Ollama** — fully local, no key

If a call to one provider fails, the router falls back to the next enabled
provider, so a rate-limit on one service doesn't kill the run.

## Extending Fraction

- **New tool** — register a `ToolDef` in `tools.build_default_registry()`.
  The agent's system prompt is auto-augmented with the tool list.
- **New agent role** — add a prompt in `agents.SYSTEM_PROMPTS`, dispatch
  to it from `Orchestrator._execute_step` based on `step["kind"]`.
- **Real vector store** — swap `memory.LongTermMemory` for a Chroma/Qdrant
  client; keep the `add` / `search` signatures.
- **Custom sandbox runtime** — `sandbox/server.py` is small on purpose;
  gVisor / Firecracker can be dropped in by changing `_run_in_docker`.

## Safety

- The sandbox has `network: none` and per-run CPU/memory/pid limits.
- File I/O is locked to `./workspaces` via `_resolve_under`.
- All model calls are time-bound and counted in the audit log.
- The orchestrator never lets a model action bypass the tool registry.

## License

MIT — death legion team.
