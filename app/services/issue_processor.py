import logging
import os

from app.models.triage import TriageResult
from app.services.llm_service import classify_with_llm

logger = logging.getLogger(__name__)


def triage_issue(repo_name: str, issue_number: int, title: str, body: str) -> TriageResult:
    """Triage a GitHub issue.

    Uses the LLM service when ANTHROPIC_API_KEY is set; falls back to
    keyword-based heuristics otherwise.
    """
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return classify_with_llm(repo_name, issue_number, title, body)
        except Exception as exc:
            logger.warning("LLM triage failed, falling back to keyword matching: %s", exc)

    return _keyword_triage(repo_name, issue_number, title, body)


def _keyword_triage(repo_name: str, issue_number: int, title: str, body: str) -> TriageResult:
    text = f"{title}\n{body}".lower()

    category_rules = [
        ("Bug", ["bug", "error", "crash", "exception", "traceback", "fail", "broken"]),
        ("Feature Request", ["feature", "enhancement", "request", "proposal", "would like"]),
        ("Documentation", ["docs", "documentation", "readme", "typo", "example"]),
        ("Question", ["question", "how to", "help", "clarify", "why does"]),
    ]

    category = "Other"
    matched_keywords: list[str] = []
    for candidate, keywords in category_rules:
        hits = [kw for kw in keywords if kw in text]
        if hits:
            category = candidate
            matched_keywords = hits
            break

    high_priority_keywords = ["urgent", "critical", "blocking", "blocker", "production", "security", "crash"]
    low_priority_keywords = ["nice to have", "minor", "nit", "cosmetic", "typo"]

    if any(kw in text for kw in high_priority_keywords):
        priority = "High"
    elif any(kw in text for kw in low_priority_keywords):
        priority = "Low"
    else:
        priority = "Medium"

    suggested_labels = [category.lower().replace(" ", "-")]
    if priority == "High":
        suggested_labels.append("priority-high")
    elif priority == "Low":
        suggested_labels.append("priority-low")
    else:
        suggested_labels.append("priority-medium")

    result = TriageResult(
        repo=repo_name,
        issue_number=issue_number,
        category=category,
        priority=priority,
        suggested_labels=suggested_labels,
        reason=f"Matched keywords: {', '.join(matched_keywords)}" if matched_keywords else "No specific keywords matched.",
    )
    logger.info(
        "Keyword triage for %s#%d — category=%s priority=%s labels=%s",
        repo_name,
        issue_number,
        result.category,
        result.priority,
        result.suggested_labels,
    )
    return result
