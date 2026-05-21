# GitHub Issue Triage

A production-style service that classifies, prioritizes, and labels new GitHub issues using an LLM with retrieval-augmented context from the repository's own documentation.

[![tests](https://img.shields.io/badge/tests-147%20passing-success)](#testing)
[![providers](https://img.shields.io/badge/LLM-Anthropic_%7C_Gemini-blue)](#configuration)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

---

## What it does

When a new issue is opened on a configured GitHub repository:

1. The webhook hits a FastAPI endpoint with HMAC-SHA256 signature verification.
2. The triage service retrieves the most semantically similar chunks of the repo's documentation from a ChromaDB vector store.
3. An LLM (Anthropic Claude or Google Gemini, swappable via env var) returns a structured `TriageOutput` with category, priority, suggested labels, and a reasoning string.
4. The service auto-creates any missing labels in the repository, applies them to the issue, and posts a formatted triage comment.
5. Metrics (counts, latency, category/priority breakdown, maintainer feedback) are tracked in-process and exposed at `/metrics`.

The pipeline degrades gracefully — if the LLM, RAG, or GitHub API is unavailable, the service falls back to keyword-based triage and continues to respond.

---

## Architecture

```
                          ┌──────────────────────────────┐
GitHub Webhook ──────────▶│  FastAPI                     │
(X-Hub-Signature-256)     │  • HMAC verification         │
                          │  • Payload parsing            │
                          └─────────────┬────────────────┘
                                        │
                          ┌─────────────▼────────────────┐
                          │  Issue Processor              │
                          │  • Latency timer              │
                          │  • Metrics + error tracking   │
                          └─────────────┬────────────────┘
                                        │
                  ┌─────────────────────┼──────────────────────┐
                  ▼                     ▼                      ▼
        ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
        │ RAG Retrieval    │  │ LLM Chain        │  │ Keyword Fallback │
        │ (ChromaDB)       │  │ (LangChain)      │  │                  │
        │ • docs + issues  │  │ • Claude/Gemini  │  │ Always available │
        │ • cosine search  │  │ • structured     │  │ Activates on     │
        │ • heading-aware  │  │   output schema  │  │ LLM/API failure  │
        └──────────────────┘  └────────┬─────────┘  └──────────────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │  GitHub Client            │
                          │  • Auto-create labels     │
                          │  • Apply labels           │
                          │  • Post triage comment    │
                          └───────────────────────────┘
```

---

## Highlights

- **Provider-agnostic LLM layer.** `LLM_PROVIDER=anthropic|gemini` swaps the underlying model with no code changes. Composed as a LangChain pipeline (`prompt | model | structured_output`).
- **LangSmith tracing.** Zero-code observability — set `LANGCHAIN_TRACING_V2=true` and every LLM call appears in the LangSmith dashboard with inputs, outputs, latency, and token counts.
- **Structure-aware document chunking.** Two-stage strategy: `MarkdownHeaderTextSplitter` preserves author-intended section boundaries; `RecursiveCharacterTextSplitter` splits oversized sections at paragraph/sentence boundaries. Heading hierarchy is preserved as chunk metadata.
- **Eval suite.** 10 labeled scenarios with expected triage decisions and retrieval keywords; standalone runner produces a scorecard and timestamped JSON for A/B comparisons.
- **Graceful degradation.** Every external dependency (LLM, vector store, GitHub API) has a failure path. The service never returns 5xx for a triage failure.
- **Webhook signature verification.** HMAC-SHA256 validation gated on `GITHUB_WEBHOOK_SECRET`.
- **Maintainer feedback loop.** `POST /feedback/{owner}/{repo}/{issue}` records correct / incorrect / overridden verdicts in the metrics surface.

---

## Eval results

The chunking strategy was refactored from fixed 512-character chunks to a structure-aware splitter. The eval suite measured the impact:

| Case | Fixed chunking | Heading-aware | Notes |
|---|---|---|---|
| `q_webhook_signature_verification` | 1.00 | 1.00 | — |
| `q_json_logging_env_var` | **0.00** | **1.00** | ★ env-var table now stays in one chunk |
| `q_docs_ingestion_command` | 1.00 | 1.00 | — |
| `q_feedback_verdicts_meaning` | 1.00 | 0.50 | regression: different chunk retrieved |
| `q_categories_supported` | 0.25 | 0.25 | — bulleted list still gets split |
| `bug_metrics_endpoint_404` | 1.00 | 1.00 | — |

Triage-quality scores (category accuracy, priority accuracy, label F1) remained essentially unchanged — the LLM was already strong at those. The retrieval column was the discriminating signal.

**Headline:** one deterministic fix on the predicted failure case, one regression discovered through measurement, and rich heading-path metadata now attached to every chunk. The eval methodology itself — reproducible, case-grained, scored — is the bigger contribution than any specific delta.

Reproduce locally:

```bash
python -m tests.eval.run_eval --label heading-aware-chunking
```

See [`tests/eval/README.md`](tests/eval/README.md) for the scoring rubric and case schema.

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `POST` | `/webhooks/github` | GitHub webhook receiver (event: `issues`, action: `opened`) |
| `GET` | `/metrics` | Aggregate triage metrics |
| `POST` | `/feedback/{owner}/{repo}/{issue}` | Submit maintainer verdict (`correct`, `incorrect`, `overridden`) |

---

## Configuration

| Variable | Description |
|---|---|
| `LLM_PROVIDER` | `anthropic` (default) or `gemini` |
| `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` | API key for the active provider |
| `ANTHROPIC_MODEL` / `GEMINI_MODEL` | Optional model override (defaults: `claude-haiku-4-5-20251001`, `gemini-2.5-flash`) |
| `GITHUB_TOKEN` | Personal access token; required to post comments and apply labels |
| `GITHUB_WEBHOOK_SECRET` | Enables HMAC-SHA256 signature verification |
| `CHROMA_DB_PATH` | Path for persistent vector store (default: ephemeral in-memory) |
| `LOG_LEVEL`, `LOG_FORMAT` | Standard `INFO`/`DEBUG`/etc., and `text`/`json` |
| `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` | Optional LangSmith tracing |

---

## Quick start

```bash
# 1. Install
pip install .

# 2. Configure (see Configuration above)
cp .env.example .env

# 3. Ingest your repo's docs into the vector store
python -m app.services.doc_ingestor docs/

# 4. Run the service
uvicorn app.main:app --port 8000

# 5. Tunnel for GitHub webhook delivery
ngrok http 8000

# 6. Configure the webhook in your repo settings
#    Payload URL: https://<ngrok>/webhooks/github
#    Content type: application/json
#    Secret: same as GITHUB_WEBHOOK_SECRET
#    Events: Issues only
```

Full setup walk-through: [`docs/how-to.md`](docs/how-to.md).

---

## Testing

```bash
# Unit tests (mocked LLM, no API costs)
pytest tests/ -q

# Eval suite (real LLM calls; ~$0.01 per run)
python -m tests.eval.run_eval --label my-experiment
```

- 147 unit tests covering webhook handling, LLM service, GitHub client, RAG retrieval, doc ingestion, metrics, and feedback.
- Tests use an autouse `conftest.py` fixture that strips LLM env vars so the test suite is deterministic regardless of local `.env` contents.

---

## Tech

Python · FastAPI · Pydantic · LangChain · ChromaDB · Anthropic Claude · Google Gemini · httpx · pytest

---

## Author

**Hanna Hunde**
*Software Engineer*
