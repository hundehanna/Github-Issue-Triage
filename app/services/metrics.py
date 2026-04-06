"""In-process metrics for triage observability.

Tracks counts, latency, and category/priority breakdowns in memory.
Metrics are exposed via GET /metrics and reset on process restart.

Usage:
    from app.services.metrics import metrics
    with metrics.track_triage():
        result = triage_issue(...)
    metrics.record_triage(result)
"""
import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator

from app.models.triage import TriageResult

logger = logging.getLogger(__name__)


@dataclass
class TriageMetrics:
    total: int = 0
    llm_used: int = 0
    keyword_fallback: int = 0
    errors: int = 0
    category_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    priority_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    feedback_counts: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )  # correct / incorrect / overridden
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        return round(self.total_latency_ms / self.total, 2) if self.total else 0.0

    def record_triage(self, result: TriageResult, *, used_llm: bool, latency_ms: float) -> None:
        self.total += 1
        if used_llm:
            self.llm_used += 1
        else:
            self.keyword_fallback += 1
        self.category_counts[result.category] += 1
        self.priority_counts[result.priority] += 1
        self.total_latency_ms += latency_ms
        logger.info(
            "Triage metrics — total=%d llm=%d fallback=%d avg_latency_ms=%.1f",
            self.total,
            self.llm_used,
            self.keyword_fallback,
            self.avg_latency_ms,
        )

    def record_error(self) -> None:
        self.errors += 1
        logger.warning("Triage error recorded — total_errors=%d", self.errors)

    def record_feedback(self, verdict: str) -> None:
        """Record maintainer feedback. verdict should be 'correct', 'incorrect', or 'overridden'."""
        self.feedback_counts[verdict] += 1
        logger.info("Feedback recorded — verdict=%s counts=%s", verdict, dict(self.feedback_counts))

    def to_dict(self) -> dict:
        return {
            "total_triaged": self.total,
            "llm_used": self.llm_used,
            "keyword_fallback": self.keyword_fallback,
            "errors": self.errors,
            "avg_latency_ms": self.avg_latency_ms,
            "by_category": dict(self.category_counts),
            "by_priority": dict(self.priority_counts),
            "feedback": dict(self.feedback_counts),
        }

    def reset(self) -> None:
        self.total = 0
        self.llm_used = 0
        self.keyword_fallback = 0
        self.errors = 0
        self.category_counts = defaultdict(int)
        self.priority_counts = defaultdict(int)
        self.feedback_counts = defaultdict(int)
        self.total_latency_ms = 0.0


# Module-level singleton
metrics = TriageMetrics()


@contextmanager
def track_triage_duration() -> Generator[dict, None, None]:
    """Context manager that measures elapsed time and stores it in the yielded dict."""
    info: dict = {}
    start = time.monotonic()
    try:
        yield info
    finally:
        info["latency_ms"] = (time.monotonic() - start) * 1000
