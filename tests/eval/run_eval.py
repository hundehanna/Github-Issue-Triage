"""Eval runner for the triage pipeline.

Loads cases.yaml, runs each through the LLM + RAG pipeline against the
real docs ingested into a fresh vector store, scores the responses, and
prints a scorecard. Results are saved to tests/eval/results/{ts}.json so
you can compare runs (e.g. before vs after a chunking refactor).

NOT run by pytest — costs real LLM credits. Run explicitly:

    python -m tests.eval.run_eval
    python -m tests.eval.run_eval --label "fixed-chunking-baseline"
    python -m tests.eval.run_eval --cases tests/eval/cases.yaml --docs docs/

Exit code 0 always — this is a measurement tool, not a pass/fail test.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Load .env before importing app modules so LLM_PROVIDER, GOOGLE_API_KEY, etc. are visible
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.services import retrieval_service
from app.services.doc_ingestor import ingest_directory
from app.services.llm_service import classify_with_llm

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Setup: reset vector store and re-ingest docs
# ---------------------------------------------------------------------------

def setup_vector_store(docs_path: Path) -> int:
    """Reset the vector store and re-ingest docs. Returns chunks ingested."""
    retrieval_service._reset_client()
    # The reset gives us a fresh ephemeral client; collections are recreated empty.
    n = ingest_directory(docs_path)
    print(f"  Ingested {n} doc chunks from {docs_path}")
    return n


# ---------------------------------------------------------------------------
# Per-case execution
# ---------------------------------------------------------------------------

def run_case(case: dict, repo: str = "eval/sandbox") -> dict:
    """Run one case through retrieval + LLM. Returns raw outputs."""
    title = case["title"]
    body = case.get("body", "")

    start = time.monotonic()
    context = retrieval_service.get_context(title, body)
    retrieve_ms = (time.monotonic() - start) * 1000

    start = time.monotonic()
    result = classify_with_llm(repo, 1, title, body, context=context)
    llm_ms = (time.monotonic() - start) * 1000

    return {
        "context": context,
        "context_chars": len(context),
        "result": result.model_dump(),
        "retrieve_ms": round(retrieve_ms, 1),
        "llm_ms": round(llm_ms, 1),
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_category(expected: dict, actual: str) -> float | None:
    if "category" in expected:
        return 1.0 if actual == expected["category"] else 0.0
    if "category_acceptable" in expected:
        return 1.0 if actual in expected["category_acceptable"] else 0.0
    return None


def _score_priority(expected: dict, actual: str) -> float | None:
    if "priority" in expected:
        return 1.0 if actual == expected["priority"] else 0.0
    if "priority_acceptable" in expected:
        return 1.0 if actual in expected["priority_acceptable"] else 0.0
    return None


def _score_labels(expected: dict, actual_labels: list[str]) -> tuple[float, list[str]]:
    """Return (score 0..1, list of failure descriptions)."""
    checks: list[bool] = []
    failures: list[str] = []
    actual_set = set(actual_labels)

    for required in expected.get("must_have_labels", []):
        passed = required in actual_set
        checks.append(passed)
        if not passed:
            failures.append(f"missing required label '{required}'")

    for forbidden in expected.get("must_not_have_labels", []):
        passed = forbidden not in actual_set
        checks.append(passed)
        if not passed:
            failures.append(f"forbidden label '{forbidden}' was applied")

    any_of = expected.get("must_have_labels_any_of")
    if any_of:
        passed = any(l in actual_set for l in any_of)
        checks.append(passed)
        if not passed:
            failures.append(f"none of {any_of} present")

    if not checks:
        return 1.0, []
    return sum(checks) / len(checks), failures


def _score_retrieval(expected: dict, context: str) -> tuple[float | None, list[str]]:
    """Score retrieval quality by keyword presence. Returns (score, failures)."""
    if not expected:
        return None, []
    keywords = expected.get("expected_keywords_in_context", [])
    if not keywords:
        return None, []

    failures: list[str] = []
    hits = 0
    ctx_lower = context.lower()
    for kw in keywords:
        if kw.lower() in ctx_lower:
            hits += 1
        else:
            failures.append(f"keyword '{kw}' missing from retrieved context")

    return hits / len(keywords), failures


def score_case(case: dict, run_output: dict) -> dict:
    """Return per-case score breakdown."""
    expected = case.get("expected", {})
    triage_exp = expected.get("triage", {})
    retrieval_exp = expected.get("retrieval", {})

    result = run_output["result"]

    cat = _score_category(triage_exp, result["category"])
    pri = _score_priority(triage_exp, result["priority"])
    labels_score, label_failures = _score_labels(triage_exp, result["suggested_labels"])
    retrieval_score, retrieval_failures = _score_retrieval(retrieval_exp, run_output["context"])

    return {
        "category": cat,
        "priority": pri,
        "labels": labels_score,
        "label_failures": label_failures,
        "retrieval": retrieval_score,
        "retrieval_failures": retrieval_failures,
    }


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

def print_scorecard(results: list[dict], label: str, model_info: dict) -> dict:
    """Print aggregate scorecard. Returns a summary dict."""
    n = len(results)

    def _avg(scores: list[float | None]) -> float:
        vals = [s for s in scores if s is not None]
        return sum(vals) / len(vals) if vals else 0.0

    cat_scores = [r["scores"]["category"] for r in results]
    pri_scores = [r["scores"]["priority"] for r in results]
    label_scores = [r["scores"]["labels"] for r in results]
    retr_scores = [r["scores"]["retrieval"] for r in results]

    cat_pass = sum(1 for s in cat_scores if s == 1.0)
    pri_pass = sum(1 for s in pri_scores if s == 1.0)
    retr_count = sum(1 for s in retr_scores if s is not None)
    retr_full = sum(1 for s in retr_scores if s is not None and s == 1.0)

    # Latency averages only over successful runs (error cases have no 'run' key)
    successful = [r for r in results if "run" in r]
    n_ok = len(successful)
    avg_llm_ms = (sum(r["run"]["llm_ms"] for r in successful) / n_ok) if n_ok else 0
    avg_retr_ms = (sum(r["run"]["retrieve_ms"] for r in successful) / n_ok) if n_ok else 0
    n_errors = n - n_ok

    summary = {
        "label": label,
        "model": model_info,
        "n_cases": n,
        "category_pass_rate": cat_pass / n,
        "priority_pass_rate": pri_pass / n,
        "labels_avg": _avg(label_scores),
        "retrieval_avg": _avg(retr_scores),
        "retrieval_full_match_rate": retr_full / retr_count if retr_count else 0.0,
        "avg_llm_ms": round(avg_llm_ms, 1),
        "avg_retrieve_ms": round(avg_retr_ms, 1),
    }

    print("\n" + "=" * 60)
    print(f"  EVAL SCORECARD -- {label}")
    print(f"  Provider={model_info['provider']}  Model={model_info['model']}")
    print("=" * 60)
    print(f"  Cases run: {n}  (errors: {n_errors})")
    print(f"  Category accuracy: {cat_pass}/{n}  ({cat_pass * 100 / n:.0f}%)")
    print(f"  Priority accuracy: {pri_pass}/{n}  ({pri_pass * 100 / n:.0f}%)")
    print(f"  Label score (avg): {summary['labels_avg']:.2f}")
    if retr_count:
        print(f"  Retrieval keyword hit-rate (avg): {summary['retrieval_avg']:.2f}")
        print(f"  Retrieval full-match: {retr_full}/{retr_count} cases hit ALL keywords")
    print(f"  Avg retrieve latency: {summary['avg_retrieve_ms']:.0f} ms")
    print(f"  Avg LLM latency:      {summary['avg_llm_ms']:.0f} ms")
    print("=" * 60)

    # Per-case failures
    failed_cases = [
        r for r in results
        if r["scores"]["category"] != 1.0
        or r["scores"]["priority"] != 1.0
        or r["scores"]["labels"] != 1.0
        or (r["scores"]["retrieval"] is not None and r["scores"]["retrieval"] != 1.0)
    ]
    error_cases = [r for r in results if "error" in r]
    if error_cases:
        print("\nCases that errored:")
        for r in error_cases:
            print(f"  - {r['case_id']}: {r['error'][:100]}")

    if failed_cases:
        print("\nCases with imperfect scores:")
        for r in failed_cases:
            if "error" in r:
                continue  # already shown above
            print(f"  - {r['case_id']}")
            s = r["scores"]
            if s["category"] not in (None, 1.0):
                print(f"      category: got '{r['run']['result']['category']}'")
            if s["priority"] not in (None, 1.0):
                print(f"      priority: got '{r['run']['result']['priority']}'")
            for f in s["label_failures"]:
                print(f"      labels: {f}")
            for f in s["retrieval_failures"]:
                print(f"      retrieval: {f}")

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Run triage eval suite.")
    parser.add_argument("--cases", type=Path, default=Path("tests/eval/cases.yaml"))
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument("--label", type=str, default="run",
                       help="Tag this run (e.g. 'fixed-chunking-baseline')")
    parser.add_argument("--output-dir", type=Path,
                       default=Path("tests/eval/results"))
    args = parser.parse_args()

    print(f"\n>> Eval starting -- label='{args.label}'")
    print(f"  Cases: {args.cases}")
    print(f"  Docs:  {args.docs}\n")

    # Setup
    print("Setting up vector store...")
    n_chunks = setup_vector_store(args.docs)

    # Load cases
    with args.cases.open() as f:
        cases = yaml.safe_load(f)
    print(f"  Loaded {len(cases)} cases\n")

    # Run each case
    results = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}", flush=True)
        try:
            run_out = run_case(case)
            scores = score_case(case, run_out)
            results.append({
                "case_id": case["id"],
                "case_title": case["title"],
                "run": run_out,
                "scores": scores,
            })
            cat_ok = "[OK]" if scores["category"] == 1.0 else "[X] "
            pri_ok = "[OK]" if scores["priority"] == 1.0 else "[X] "
            print(f"    category={cat_ok}  priority={pri_ok}  labels={scores['labels']:.2f}", end="")
            if scores["retrieval"] is not None:
                print(f"  retrieval={scores['retrieval']:.2f}")
            else:
                print()
        except Exception as exc:
            logger.error("Case %s failed: %s", case["id"], exc, exc_info=True)
            results.append({
                "case_id": case["id"],
                "case_title": case["title"],
                "error": str(exc),
                "scores": {"category": 0, "priority": 0, "labels": 0,
                          "retrieval": 0, "label_failures": [], "retrieval_failures": []},
            })

    # Scorecard
    import os
    model_info = {
        "provider": os.getenv("LLM_PROVIDER", "anthropic"),
        "model": os.getenv("GEMINI_MODEL") or os.getenv("ANTHROPIC_MODEL") or "default",
    }
    summary = print_scorecard(results, args.label, model_info)

    # Save
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = args.output_dir / f"{ts}-{args.label}.json"
    payload = {
        "timestamp": ts,
        "label": args.label,
        "doc_chunks_indexed": n_chunks,
        "summary": summary,
        "results": results,
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
