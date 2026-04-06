# GitHub Issue Triage

An AI-powered service that automatically classifies, prioritizes, and labels GitHub issues using large language models and retrieval-augmented generation (RAG).

---

## Overview

Managing GitHub issues at scale is time-consuming and inconsistent. This service hooks into GitHub webhooks to triage new issues in real time — no manual review needed for the initial pass.

When a new issue is opened, the service:

1. Retrieves relevant context from your repository docs and past issues (RAG)
2. Sends the issue to Claude for classification (falls back to keyword matching if no API key)
3. Applies labels automatically via the GitHub API
4. Posts a structured triage summary as a comment

---

## Features

- **Automated classification** — Bug, Feature Request, Documentation, Question, Other
- **Priority inference** — High, Medium, Low based on content signals
- **Label management** — Suggests and auto-creates labels, applies them to the issue
- **RAG context** — Embeds your repository docs and past issues into ChromaDB for richer LLM context
- **Webhook signature verification** — HMAC-SHA256 validation of all incoming GitHub events
- **Observability** — Structured logging, in-process metrics endpoint (`GET /metrics`)
- **Feedback loop** — Maintainers can rate triage accuracy via `POST /feedback`
- **Graceful degradation** — Every external dependency (LLM, RAG, GitHub API) degrades silently so triage always completes

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/hundehanna/Github-Issue-Triage.git
cd Github-Issue-Triage
pip install .

# 2. Configure environment
cp .env.example .env   # edit with your keys

# 3. Run
uvicorn app.main:app --reload --port 8000

# 4. Expose via ngrok (for local webhook testing)
ngrok http 8000
```

Then configure a GitHub webhook pointing to `https://<your-ngrok-url>/webhooks/github` with event type **Issues**.

See [docs/how-to.md](docs/how-to.md) for the full setup guide with examples.

---

## Example Triage Comment

When an issue is created, the bot posts:

> ## 🤖 Automated Issue Triage
>
> | Field | Value |
> |---|---|
> | **Category** | 🐛 Bug |
> | **Priority** | 🔴 High |
> | **Suggested Labels** | `bug`, `priority-high` |
>
> **Reason:** The issue describes a crash on startup with a traceback; blocking keyword indicates high priority.
>
> _This triage was performed automatically. A maintainer will review shortly._

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/webhooks/github` | GitHub webhook receiver |
| `GET` | `/metrics` | Triage metrics (counts, latency, breakdown) |
| `POST` | `/feedback/{owner}/{repo}/{issue}` | Submit maintainer feedback on triage accuracy |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | No | Enables LLM triage via Claude. Falls back to keyword matching if unset. |
| `GITHUB_TOKEN` | No | Enables posting comments and applying labels on GitHub. |
| `GITHUB_WEBHOOK_SECRET` | No | Validates HMAC-SHA256 signatures. Recommended in production. |
| `LOG_LEVEL` | No | `DEBUG` / `INFO` / `WARNING` / `ERROR` (default: `INFO`) |
| `LOG_FORMAT` | No | `text` or `json` (default: `text`) |
| `DOCS_DIR` | No | Path to Markdown docs to ingest into the RAG vector store. |

---

## Architecture

```
GitHub Repository
      │
      ▼ (webhook on issue opened)
FastAPI Backend  ──► Issue Processor
                         │
                         ├── RAG Retrieval (ChromaDB)
                         ├── LLM Service (Anthropic Claude)
                         │     └── keyword fallback
                         ├── GitHub Client (labels + comment)
                         └── Metrics
```

---

## Tech Stack

- **Backend**: Python, FastAPI
- **LLM**: Anthropic Claude (`claude-haiku-4-5`)
- **RAG**: ChromaDB vector store
- **GitHub Integration**: Webhooks + REST API via httpx
- **Testing**: pytest (137 tests)

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Documentation

- [How-To Guide](docs/how-to.md) — full setup, examples, and API reference
- [Project Spec](docs/project_spec.md) — original specification and phase breakdown

---

## Author

**Hanna Hunde**
*Software Engineer | Aspiring AI Engineer*
