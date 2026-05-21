# GitHub Issue Triage — Project Specification

## Overview

A FastAPI service that listens to GitHub webhook events and automatically classifies, prioritizes, and labels newly created issues. The triage decision is made by an LLM with retrieval-augmented context from the repository's own documentation, and the result is applied directly to the issue via the GitHub API.

The system is designed for production deployment: signature-verified webhooks, multi-provider LLM abstraction, persistent RAG storage, structured logging, and an in-process metrics surface for observability.

---

## Goals

1. **Automated classification** of issues into Bug, Feature Request, Documentation, Question, or Other.
2. **Priority inference** at High, Medium, or Low.
3. **Label suggestions** that respect the repository's existing conventions (via RAG over docs and past issues).
4. **Documented integration** that any maintainer can stand up in under 30 minutes.
5. **Measurable triage quality** through a hand-crafted eval suite that produces comparable scorecards between configurations.

---

## Architecture

```
GitHub Repository
        │
        ▼ (webhook on issue opened — HMAC-SHA256 signed)
FastAPI Backend
        │
        ├── Issue Processor
        │       ├── RAG Retrieval (ChromaDB)
        │       ├── LLM Service (LangChain → Anthropic | Gemini)
        │       │     └── Keyword fallback (always available)
        │       └── Metrics (latency, counts, errors)
        │
        └── GitHub Client
                ├── Auto-create labels with default colors
                ├── Apply labels to the issue
                └── Post formatted triage comment
```

Every external dependency (LLM, vector store, GitHub API) has a failure path. The webhook handler never returns a 5xx for an internal error — failures are logged and counted; triage either falls back to keyword matching or completes without the GitHub side-effects.

---

## Implementation by phase

The project was built in four phases. All four are complete.

### Phase 1 — Infrastructure
- FastAPI service with `/health`, `/webhooks/github`, `/metrics`, `/feedback/{owner}/{repo}/{issue}`.
- HMAC-SHA256 signature verification gated on `GITHUB_WEBHOOK_SECRET`.
- Payload parsing with strict validation (rejects missing/malformed fields).
- `GitHubClient` for label auto-creation, label application, and triage-comment posting; uses `httpx.Client` for testability.
- Structured logging (`text` or `json` via `LOG_FORMAT`).

### Phase 2 — LLM integration
- LangChain pipeline: `ChatPromptTemplate | <provider>.with_structured_output(TriageOutput)`.
- Two providers: Anthropic Claude and Google Gemini, swapped via `LLM_PROVIDER`. Model overrides via `ANTHROPIC_MODEL` / `GEMINI_MODEL`.
- Structured output via Pydantic schema with safe defaults for fields some models occasionally omit.
- Optional LangSmith tracing — auto-enabled when `LANGCHAIN_TRACING_V2=true`.
- Keyword fallback path preserved as the default when no API key is configured or the LLM call raises.

### Phase 3 — RAG
- ChromaDB vector store with two collections: `docs` (ingested at startup or via CLI) and `issues` (streamed in as triage runs).
- `python -m app.services.doc_ingestor docs/` builds the docs collection.
- **Chunking strategy:** structure-aware. `MarkdownHeaderTextSplitter` preserves section boundaries; `RecursiveCharacterTextSplitter` handles oversized sections by preferring paragraph and sentence breaks. Heading hierarchy (e.g. *"Reference > Environment Variables"*) is stored as chunk metadata.
- Retrieval surfaces the top-N most similar chunks across both collections, truncated to 1.5KB before being injected into the LLM prompt.

### Phase 4 — Evaluation & Observability
- `TriageMetrics` singleton: counts, LLM-vs-fallback split, errors, per-category and per-priority breakdowns, avg latency, feedback verdict counts.
- `/metrics` endpoint exposes the full snapshot as JSON.
- `/feedback` endpoint records maintainer verdicts (`correct`, `incorrect`, `overridden`).
- **Eval suite** (`tests/eval/`):
  - 10 labeled scenarios (4 generic triage-quality, 6 doc-grounded for RAG-quality).
  - Standalone runner that resets the vector store, re-ingests docs, runs each case, scores against expected outputs, and saves timestamped JSON for run-over-run comparison.
  - Scores: category accuracy, priority accuracy, label F1, retrieval keyword hit-rate.

---

## Eval methodology

Each case in `tests/eval/cases.yaml` specifies the issue payload plus expected triage and retrieval outputs:

```yaml
- id: q_json_logging_env_var
  title: "How do I get JSON-formatted logs for production?"
  body: |
    Running this in Kubernetes, our log aggregator expects JSON. What env
    var do I set?
  expected:
    triage:
      category: Question
      priority: Low
    retrieval:
      must_retrieve_from: [how-to.md]
      expected_keywords_in_context: [LOG_FORMAT]
```

The runner records both the triage decision and the retrieved RAG context, then scores them independently. Results land in `tests/eval/results/{timestamp}-{label}.json` so two configurations can be compared directly.

This separation matters: triage quality reflects the LLM, retrieval quality reflects the chunking and embedding strategy. Mixing them obscures which knob is doing the work.

---

## Tech stack

- **Backend:** Python 3.10+, FastAPI, Pydantic v2
- **LLM orchestration:** LangChain (`langchain-anthropic`, `langchain-google-genai`)
- **Vector store:** ChromaDB with default sentence-transformer embeddings
- **Text splitting:** `langchain-text-splitters` (`MarkdownHeaderTextSplitter`, `RecursiveCharacterTextSplitter`)
- **HTTP:** httpx for GitHub API; uvicorn for the ASGI server
- **Testing:** pytest, pytest-asyncio
- **Observability:** structured logging, in-process metrics, optional LangSmith tracing

---

## Future enhancements

| Area | Idea | Why |
|---|---|---|
| Persistent storage | Migrate `CHROMA_DB_PATH` to PostgreSQL + pgvector | Production-ready storage; replication and backups for free |
| Embedding model | Move from default MiniLM to `text-embedding-005` or similar | Better semantic similarity on technical docs |
| Eval coverage | Grow to 50+ cases sourced from real triaged issues across multiple repos | Smaller per-case noise dominates the aggregate at N=10 |
| Multi-run scoring | Average each case over N runs to separate chunking signal from LLM stochasticity | More confident A/B claims |
| Duplicate detection | Use the `issues` collection to flag potential duplicates in the triage comment | High-leverage feature for busy repos |
| Confidence scoring | Have the LLM emit a confidence value; route low-confidence triages to human review | Improves trust and feedback signal |
| Multi-tenancy | Scope retrieval by `repo` metadata for a shared deployment serving many repos | Required for a hosted product offering |

---

## Status

Production-ready as a self-hosted service for a single repository. The pipeline has been exercised end-to-end against real Gemini API calls with all four phases and the eval suite producing reproducible scorecards.
