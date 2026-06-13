# Fraction — Quickstart

## 0. Requirements

- Docker 24+ with the Compose plugin
- 4 GB RAM free (8 GB if you also run Ollama)
- One or more LLM API keys (free tiers are fine)

## 1. Get the code

```bash
git clone <your-fork-url> fraction
cd fraction
```

Or just use the directory you already have.

## 2. Add your API keys

Open **`config/fraction.yaml`** (copy it from `config/fraction.yaml.example`
if you haven't yet). For each provider you want to use, set:

```yaml
providers:
  groq:
    enabled: true
    api_key: "${GROQ_API_KEY}"
    models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    default: "llama-3.3-70b-versatile"
    free: true
```

Either:
- Put the key directly: `api_key: "gsk_..."` (gitignore already excludes this file)
- Or set it as an env var in `.env` at the repo root and reference it as `${GROQ_API_KEY}`

### Free / no-key options

- **Ollama** (fully local) — uncomment the `ollama` service in `docker-compose.yml`,
  then `docker compose up -d ollama && docker compose exec ollama ollama pull llama3.2`.
  Set `providers.ollama.enabled: true` in `fraction.yaml`.
- **Google Gemini** — get a free key at https://aistudio.google.com/apikey
- **Groq** — free tier at https://console.groq.com
- **OpenRouter** — many `:free` models, one key at https://openrouter.ai

## 3. Start the stack

```bash
docker compose up --build
```

You'll see three services come up: `fraction-backend`, `fraction-sandbox`,
`fraction-frontend`. First boot takes ~1 minute to build images.

## 4. Open the UI

Navigate to **http://localhost:3000**.

Type a goal, hit Run, and watch the planner → researchers → coder → reviewer
→ writer pipeline light up in the chat. When the writer finishes, the
deliverable opens in the right panel — copy, download, or rate it.

## 5. Try it

Some example goals to paste in:

- *Research the current state of quantum computing and write a summary report*
- *Build a Python CLI that converts CSV files to JSON, with tests, and run the tests*
- *Compare the top three open-source vector databases and recommend one for a small startup*
- *Write a tutorial on using Docker Compose for local development*

## 6. CLI

The repo ships with a small CLI for when you don't want the UI:

```bash
pip install httpx pyyaml pydantic
python scripts/fractionctl.py config       # show loaded config
python scripts/fractionctl.py providers    # show provider/key status
python scripts/fractionctl.py goal "research RAG vs fine-tuning and write a 1-page brief"
python scripts/fractionctl.py memory       # dump long-term memory
python scripts/fractionctl.py deliverables # list finished deliverables
```

## Troubleshooting

| Symptom                                | Fix                                                              |
|----------------------------------------|------------------------------------------------------------------|
| `provider X failed: HTTP 401`          | The API key is wrong or missing — re-check `config/fraction.yaml`. |
| `docker: command not found` in sandbox | Mount the host docker socket (already done in compose) or set `SANDBOX_USE_DOCKER=0` for in-process fallback. |
| `Ollama connection refused`            | Uncomment the `ollama` service in `docker-compose.yml` and pull a model. |
| Goal gets stuck on a step              | The reviewer is being too strict. Set `agents.enable_replanner: true` (default) so it auto-retries. |
| Want to wipe state                     | `rm -rf memory/store workspaces deliverables && docker compose restart backend` |
