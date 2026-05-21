# Eval Suite

Measures triage quality on a hand-crafted set of issue scenarios. Used to
compare implementations (e.g. fixed vs semantic chunking) by running the
same cases against each variant and diffing the scorecards.

## What's in here

- `cases.yaml` — 10 labeled issue scenarios with expected triage decisions
  and (for doc-grounded cases) expected retrieval keywords
- `run_eval.py` — the runner; ingests docs, runs each case, scores, prints
  a scorecard, and saves results to `results/{ts}-{label}.json`
- `results/` — historical run output (gitignored — these are local
  measurements, not artifacts)

## Running

```bash
# Quick run with default settings
python -m tests.eval.run_eval

# Tag the run so you can compare later
python -m tests.eval.run_eval --label fixed-chunking-baseline

# Custom paths
python -m tests.eval.run_eval --cases tests/eval/cases.yaml --docs docs/
```

The eval uses whichever LLM provider is configured in `.env`
(`LLM_PROVIDER=anthropic` or `gemini`). It will call the real API and
spend real credits. Typically ~$0.01–$0.05 per full run.

## Cases.yaml schema

```yaml
- id: unique_id                # stable identifier
  title: "Issue title"
  body: |
    Multi-line issue body.
  expected:
    triage:
      # Either exact match...
      category: Bug             # one of: Bug, Feature Request, Documentation, Question, Other
      priority: High            # one of: High, Medium, Low
      # ...or accept a list:
      category_acceptable: [Bug, Documentation]
      priority_acceptable: [Low, Medium]
      # Label constraints (all optional):
      must_have_labels: [bug, priority-high]
      must_not_have_labels: [feature-request]
      must_have_labels_any_of: [bug, documentation]
    # Optional — for doc-grounded cases that test retrieval quality
    retrieval:
      must_retrieve_from: [how-to.md]   # advisory only (not scored in v1)
      expected_keywords_in_context:      # scored — checks these strings
        - GITHUB_WEBHOOK_SECRET           # appear in the retrieved context
        - HMAC
  notes: "Human-readable explanation of why this case exists"
```

## Scoring

Each case yields up to four sub-scores (each 0–1):

| Score | What it measures |
|---|---|
| `category` | 1 if `result.category` matches `expected.triage.category` (or is in `category_acceptable`), else 0 |
| `priority` | Same logic for priority |
| `labels` | Fraction of label constraints satisfied (must-have, must-not-have, any-of) |
| `retrieval` | Fraction of `expected_keywords_in_context` that appear in the retrieved RAG context (case-insensitive substring match) |

The scorecard prints:

- Per-case pass/fail on each dimension
- Aggregate pass-rates across all cases
- A "failures" section listing every case that wasn't perfect, with reasons
- Average latency for retrieval and LLM stages

## Comparing runs

After running with two different labels, the JSON output files have
identical structure, so you can diff them:

```bash
python -m tests.eval.run_eval --label baseline
# ...refactor chunking...
python -m tests.eval.run_eval --label semantic-chunking

# Compare manually, or write a small diff script
diff <(jq .summary tests/eval/results/*-baseline.json) \
     <(jq .summary tests/eval/results/*-semantic-chunking.json)
```

## What this eval IS measuring

- Whether the LLM makes correct category / priority / label decisions
- Whether RAG retrieval surfaces the right context (via keyword presence)
- End-to-end latency

## What this eval is NOT measuring

- Webhook signature verification (covered by unit tests)
- GitHub API integration (covered by unit tests, validate manually with ngrok)
- Behavior under high load (use a load testing tool)
- Anything about the `issues` collection (we'd need real past-issue data;
  not relevant to the docs-chunking refactor)
