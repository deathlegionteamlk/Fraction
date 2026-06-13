# Fraction

**An advanced multi-agent AI framework by the death legion team.**

Fraction is a fully open-source, self-hostable system that turns a single high-level goal
("research the current state of quantum computing and write a summary report") into a
coordinated run of specialized agents — planners, researchers, coders, reviewers, and
writers — that use tools, browse the web, run code in a sandbox, and produce a final
deliverable you can download.

## Highlights

- **Multi-agent orchestration** — A Planner breaks the goal into steps; a Researcher
  browses the web; a Coder writes/runs code in an isolated sandbox; a Reviewer checks
  the work; a Writer assembles the final deliverable. Agents can spawn sub-tasks.
- **Web UI** — Chat-style interface to give goals, watch progress live, and grab outputs.
- **Safe sandbox** — Code runs in a Docker-in-Docker isolated container with network
  controls, CPU/memory limits, and a 60-second default timeout.
- **Memory** — Short-term (per-session) and long-term (vector + structured) memory so
  the system learns from past tasks.
- **Pluggable models** — Bring your own keys for OpenAI, Anthropic, Google, OpenRouter,
  Groq, Ollama, or any OpenAI-compatible endpoint. Free tiers work great.
- **Fully open source** — MIT licensed, no telemetry, no vendor lock-in.

## Quick start (Docker)

```bash
cd fraction
cp config/fraction.yaml.example config/fraction.yaml
# edit config/fraction.yaml and add your API keys
docker compose up --build
```

Then open **http://localhost:3000**.

## Adding API keys

All model configuration lives in **`config/fraction.yaml`**. Open it, set the keys for
the providers you want to use, and restart `docker compose restart backend`. The default
config ships with a working Ollama/local fallback and commented-out entries for the major
cloud providers.

## License

MIT — see `LICENSE`.
