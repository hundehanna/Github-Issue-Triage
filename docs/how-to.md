# How to Use — GitHub Issue Triage

This guide explains how to set up, run, and integrate the GitHub Issue Triage service from scratch.

---

## Prerequisites

- Python 3.10+
- A GitHub repository you own (to configure webhooks)
- [ngrok](https://ngrok.com/) (for local webhook testing)
- An Anthropic API key (optional — the service falls back to keyword matching without one)
- A GitHub Personal Access Token with `repo` scope (optional — required to post comments and apply labels)

---

## 1. Installation

```bash
git clone https://github.com/hundehanna/Github-Issue-Triage.git
cd Github-Issue-Triage
pip install -r requirements.txt   # or: pip install .
```

---

## 2. Environment Variables

Create a `.env` file in the project root (never commit this):

```env
# Required for LLM triage (falls back to keywords if not set)
ANTHROPIC_API_KEY=sk-ant-...

# Required to post comments and apply labels on GitHub issues
GITHUB_TOKEN=ghp_...

# Required to verify webhook signatures from GitHub
GITHUB_WEBHOOK_SECRET=your-random-secret

# Optional: logging
LOG_LEVEL=INFO          # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT=text         # text | json
```

---

## 3. Running the Service Locally

```bash
uvicorn app.main:app --reload --port 8000
```

Verify it's running:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

---

## 4. Exposing the Service with ngrok

GitHub webhooks require a publicly accessible URL. Use ngrok to tunnel your local server:

```bash
ngrok http 8000
```

Copy the forwarding URL (e.g. `https://abc123.ngrok.io`) — you'll use it in the next step.

---

## 5. Configuring the GitHub Webhook

1. Go to your GitHub repository → **Settings** → **Webhooks** → **Add webhook**
2. Fill in the form:
   - **Payload URL**: `https://abc123.ngrok.io/webhooks/github`
   - **Content type**: `application/json`
   - **Secret**: The same value as `GITHUB_WEBHOOK_SECRET` in your `.env`
   - **Events**: Select **"Let me select individual events"** → check **Issues** only
3. Click **Add webhook**

---

## 6. Creating a Test Issue

Open a new issue in your repository. Within seconds you should see:

- Labels applied automatically (e.g. `bug`, `priority-high`)
- A triage comment posted by the bot, like:

> ## 🤖 Automated Issue Triage
>
> | Field | Value |
> |---|---|
> | **Category** | 🐛 Bug |
> | **Priority** | 🔴 High |
> | **Suggested Labels** | `bug`, `priority-high` |
>
> **Reason:** The issue describes a crash on startup, indicating a high-severity bug.
>
> _This triage was performed automatically. A maintainer will review shortly._

---

## 7. Ingesting Repository Documentation (RAG)

To give the LLM context from your repository docs, ingest your Markdown files:

```bash
python -m app.services.doc_ingestor ./docs
```

Or set the `DOCS_DIR` environment variable and it runs automatically on startup:

```env
DOCS_DIR=./docs
```

This embeds all `.md` files into the ChromaDB vector store, which the triage pipeline queries before each LLM call.

---

## 8. Viewing Metrics

The service exposes a `/metrics` endpoint with triage statistics:

```bash
curl http://localhost:8000/metrics
```

Example response:

```json
{
  "total_triaged": 42,
  "llm_used": 38,
  "keyword_fallback": 4,
  "errors": 0,
  "avg_latency_ms": 312.5,
  "by_category": {
    "Bug": 20,
    "Feature Request": 12,
    "Question": 6,
    "Documentation": 3,
    "Other": 1
  },
  "by_priority": {
    "High": 15,
    "Medium": 22,
    "Low": 5
  },
  "feedback": {
    "correct": 30,
    "incorrect": 5,
    "overridden": 7
  }
}
```

---

## 9. Submitting Maintainer Feedback

After reviewing a triage result, maintainers can submit feedback to track accuracy:

```bash
curl -X POST http://localhost:8000/feedback/myorg/myrepo/42 \
  -H "Content-Type: application/json" \
  -d '{"verdict": "correct", "note": "Correctly identified as a blocking bug"}'
```

Valid verdicts:

| Verdict | Meaning |
|---|---|
| `correct` | The triage was accurate |
| `incorrect` | The category or priority was wrong |
| `overridden` | The maintainer changed the labels/priority |

Response:

```json
{
  "repo": "myorg/myrepo",
  "issue_number": 42,
  "verdict": "correct",
  "recorded": true
}
```

---

## 10. Manual Webhook Testing (without GitHub)

You can send a test webhook payload directly:

```bash
curl -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "x-github-event: issues" \
  -d '{
    "action": "opened",
    "issue": {
      "number": 1,
      "title": "App crashes on startup",
      "body": "Getting a traceback when I run the app. This is blocking our release."
    },
    "repository": {
      "full_name": "myorg/myrepo"
    }
  }'
```

Expected response:

```json
{
  "received_event": "issues",
  "repo": "myorg/myrepo",
  "issue_number": 1,
  "issue_title": "App crashes on startup",
  "triage": {
    "repo": "myorg/myrepo",
    "issue_number": 1,
    "category": "Bug",
    "priority": "High",
    "suggested_labels": ["bug", "priority-high"],
    "reason": "Crash on startup with a traceback; blocking keyword indicates high priority."
  }
}
```

---

## 11. Running Tests

```bash
pytest tests/ -v
```

All 137 tests should pass.

---

## Environment Variable Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | No | — | Enables LLM triage. Falls back to keywords if not set. |
| `GITHUB_TOKEN` | No | — | Enables posting comments and applying labels on GitHub. |
| `GITHUB_WEBHOOK_SECRET` | No | — | Validates HMAC-SHA256 signatures from GitHub. Recommended in production. |
| `LOG_LEVEL` | No | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | No | `text` | `text` for human-readable, `json` for structured production logs |
| `DOCS_DIR` | No | — | Path to Markdown docs directory to ingest into the RAG vector store |
