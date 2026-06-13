<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=4,9,16&height=220&section=header&text=Fraction&fontSize=85&fontColor=ffffff&fontAlignY=38&desc=Multi-agent%20AI%20framework.%20Self-hostable.%20MIT%20licensed.&descAlignY=60&descSize=20&animation=fadeIn" width="100%"/>

<br/>

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=20&duration=2800&pause=900&color=06B6D4&center=true&vCenter=true&multiline=true&width=720&height=80&lines=Give+it+a+goal.+Agents+plan%2C+research%2C+code%2C+review%2C+write.;Docker+sandbox.+Vector+memory.+Pluggable+models.;Open+source.+No+telemetry.+No+lock-in." alt="Typing animation"/>

<br/><br/>

[![License: MIT](https://img.shields.io/badge/License-MIT-06b6d4?style=for-the-badge)](./LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Required-0ea5e9?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![OpenAI](https://img.shields.io/badge/OpenAI-Compatible-10b981?style=for-the-badge)](https://platform.openai.com)
[![Ollama](https://img.shields.io/badge/Ollama-Supported-1a1a1a?style=for-the-badge)](https://ollama.com)
[![Built by](https://img.shields.io/badge/💀-Death%20Legion%20Team-1a1a1a?style=for-the-badge)](https://github.com/deathlegionteam)

</div>

---

## 🤔 What is Fraction?

You type a goal. Something like:

> *"Research the current state of quantum computing and write a summary report."*

Fraction doesn't hand that to a single model and hope for the best. It breaks the goal into steps, assigns each step to a specialized agent, runs them in sequence (or parallel where it makes sense), and hands you a finished deliverable at the end.

A **Planner** figures out what needs to happen. A **Researcher** browses the web to gather information. A **Coder** writes and executes code in an isolated Docker sandbox. A **Reviewer** checks the work for gaps. A **Writer** assembles everything into a final output. Agents can spawn sub-tasks when a step turns out to be bigger than expected.

The whole thing runs on your own machine. You bring API keys for whatever models you want to use — OpenAI, Anthropic, Google, Groq, Ollama, or anything OpenAI-compatible. No telemetry, no vendor lock-in, MIT licensed.

<div align="center">
<img src="https://user-images.githubusercontent.com/74038190/212284100-561aa473-3905-4a80-b561-0d28506553ee.gif" width="600"/>
</div>

---

## ✨ What's in the box

<div align="center">
<img src="https://user-images.githubusercontent.com/74038190/212257468-1e9a91f1-b626-4baa-b15d-5c385dfa7ed2.gif" width="80"/>
</div>

<table>
<tr>
<td width="50%">

### 🧠 Multi-agent orchestration
Five specialized agents — Planner, Researcher, Coder, Reviewer, Writer — each doing one thing well. The Planner coordinates; the others execute. Any agent can spawn sub-tasks when it hits something larger than expected.

### 🌐 Web UI
Chat-style interface where you type goals, watch agent activity stream in live, and download the final output when it's done. No CLI required for day-to-day use.

### 🐳 Safe code sandbox
Code runs inside a Docker-in-Docker isolated container. Network access is controlled, CPU and memory are capped, and a 60-second default timeout keeps runaway processes from causing problems.

</td>
<td width="50%">

### 🧩 Memory — short and long term
Per-session short-term memory keeps context within a task. Long-term memory (vector + structured) persists across sessions so the system can recall what it learned from past tasks.

### 🔌 Pluggable model backends
`config/fraction.yaml` is where all model config lives. Set keys for the providers you use — OpenAI, Anthropic, Google, OpenRouter, Groq, Ollama — and Fraction routes to them. The default config ships with a working local Ollama fallback so you can run it for free out of the box.

### 🔓 Fully open source
MIT license, no telemetry, no phoning home. The entire system runs on your own infrastructure. You can read every line of code that touches your data.

</td>
</tr>
</table>

---

## 🏗️ How it works

<div align="center">
<img src="https://user-images.githubusercontent.com/74038190/229223263-cf2e4b07-2615-4f87-9c38-e37600f8381a.gif" width="350"/>
</div>

```
You type a goal
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                        Fraction                          │
│                                                          │
│  ┌─────────────┐                                         │
│  │   Planner   │  breaks goal into ordered steps         │
│  └──────┬──────┘                                         │
│         │  dispatches to                                 │
│   ┌─────┼──────────────────────┐                         │
│   ▼     ▼                      ▼                         │
│  ┌──────────┐  ┌───────────┐  ┌────────────┐            │
│  │Researcher│  │  Coder    │  │  Writer    │            │
│  │web search│  │sandbox run│  │assembles   │            │
│  │+ scraping│  │+ code gen │  │final output│            │
│  └──────────┘  └───────────┘  └────────────┘            │
│         │              │              │                   │
│         └──────────────┴──────────────┘                  │
│                        │                                 │
│                ┌───────▼───────┐                         │
│                │   Reviewer    │  checks & requests fixes │
│                └───────────────┘                         │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Memory: short-term (session) + long-term (vector) │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
       │
       ▼
Finished deliverable ready to download
```

---

## 🚀 Quick start

<div align="center">
<img src="https://user-images.githubusercontent.com/74038190/212257454-16e3712e-945a-4ca2-b238-408ad0bf87e6.gif" width="80"/>
</div>

You need Docker and Docker Compose. That's the only hard dependency.

```bash
cd fraction
cp config/fraction.yaml.example config/fraction.yaml
```

Open `config/fraction.yaml` and add API keys for whatever model providers you want to use. The file ships with a working Ollama fallback and commented entries for the major cloud providers — uncomment what you need.

```bash
docker compose up --build
```

Open **http://localhost:3000**.

---

## ⚙️ Model configuration

All model config lives in `config/fraction.yaml`. Here's the shape of it:

```yaml
models:
  default: ollama/llama3       # free local fallback, works out of the box

  providers:
    openai:
      api_key: sk-...          # optional — comment out if not using
      model: gpt-4o

    anthropic:
      api_key: sk-ant-...      # optional
      model: claude-sonnet-4-6

    google:
      api_key: ...             # optional
      model: gemini-1.5-pro

    groq:
      api_key: ...             # optional — fast inference, generous free tier
      model: llama3-70b-8192

    ollama:
      base_url: http://localhost:11434
      model: llama3            # pull with: ollama run llama3
```

After editing, apply with:

```bash
docker compose restart backend
```

Fraction routes each agent to whatever backend you configure. You can assign different models to different agents — a cheaper model for the Planner, a stronger one for the Writer — by setting per-agent overrides in the same file.

---

## 🔒 The code sandbox

The Coder agent runs code in a Docker-in-Docker container with:

| Constraint | Default |
|---|---|
| Network access | Controlled (outbound limited) |
| CPU | Capped per container |
| Memory | Capped per container |
| Execution timeout | 60 seconds |
| Filesystem | Ephemeral — wiped after each run |

Code that the Coder writes never runs on your host machine. It runs inside the nested container, results come back over a socket, and the container is thrown away. If something crashes or hangs, the timeout kills it.

---

## 🧠 Memory

**Short-term** memory is per-session. Agents within a task share a scratchpad — the Researcher's findings are visible to the Writer without being passed explicitly.

**Long-term** memory survives across sessions. It's a combination of vector storage (for semantic search over past task outputs) and structured storage (for facts, preferences, and task metadata). When you run a new task, Fraction searches long-term memory for relevant context and injects it into the relevant agents.

---

## 🌐 Supported model providers

| Provider | Notes |
|---|---|
| OpenAI | GPT-4o, GPT-4 Turbo, GPT-3.5 |
| Anthropic | Claude Sonnet, Claude Haiku |
| Google | Gemini 1.5 Pro, Flash |
| OpenRouter | Routes to 100+ models, one API key |
| Groq | Fast inference, generous free tier |
| Ollama | Fully local, free, no API key needed |
| Any OpenAI-compatible endpoint | Set `base_url` in config |

Free tiers on Groq and Ollama work fine for most tasks. You don't need a paid account to get started.

---

## 📁 Project structure

```
fraction/
├── config/
│   ├── fraction.yaml.example   # copy this and add your keys
│   └── fraction.yaml           # your local config (gitignored)
├── agents/
│   ├── planner.py              # goal decomposition
│   ├── researcher.py           # web search + scraping
│   ├── coder.py                # code generation + sandbox execution
│   ├── reviewer.py             # output verification
│   └── writer.py               # final deliverable assembly
├── memory/
│   ├── short_term.py           # per-session scratchpad
│   └── long_term.py            # vector + structured persistence
├── sandbox/
│   └── docker_runner.py        # Docker-in-Docker execution
├── ui/                         # React frontend
├── docker-compose.yml
└── LICENSE
```

---

## 🤝 Contributing

<div align="center">
<img src="https://user-images.githubusercontent.com/74038190/212284115-f47cd8ff-2ffb-4b04-b5bf-4d1c14c0247f.gif" width="400"/>
</div>

New agent types, model provider integrations, memory backends, and sandbox improvements are all useful contributions. Open an issue before starting on anything that changes the agent architecture or config schema.

```bash
git clone https://github.com/deathlegionteam/fraction.git
cd fraction
cp config/fraction.yaml.example config/fraction.yaml
docker compose up --build
```

---

## 🛡️ License

MIT — see `LICENSE`. No telemetry. No vendor dependency. Runs entirely on your infrastructure.

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=4,9,16&height=100&section=footer&animation=fadeIn" width="100%"/>

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=13&duration=4000&pause=1000&color=06B6D4&center=true&vCenter=true&width=560&lines=Give+it+a+goal.+Get+back+a+deliverable.;Five+agents.+One+framework.+Your+machine.;💀+Built+by+Death+Legion+Team." alt="Footer typing"/>

</div>
