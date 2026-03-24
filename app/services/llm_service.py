import logging
import os

import anthropic

from app.models.triage import TriageResult

logger = logging.getLogger(__name__)

_TRIAGE_TOOL = {
    "name": "triage_issue",
    "description": (
        "Classify and prioritize a GitHub issue. "
        "Return the category, priority, suggested labels, and a brief reason."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["Bug", "Feature Request", "Documentation", "Question", "Other"],
                "description": "The nature of the issue.",
            },
            "priority": {
                "type": "string",
                "enum": ["High", "Medium", "Low"],
                "description": "Urgency level based on impact and severity.",
            },
            "suggested_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "GitHub labels to apply (e.g. 'bug', 'priority-high').",
            },
            "reason": {
                "type": "string",
                "description": "One or two sentences explaining the triage decision.",
            },
        },
        "required": ["category", "priority", "suggested_labels", "reason"],
    },
}

_SYSTEM_PROMPT = (
    "You are a senior open-source maintainer performing issue triage. "
    "Analyse the provided GitHub issue and call the triage_issue tool with your assessment. "
    "Be concise and consistent."
)


def classify_with_llm(
    repo: str,
    issue_number: int,
    title: str,
    body: str,
    *,
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> TriageResult:
    """Classify a GitHub issue using Claude. Raises on any API error."""
    client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    user_content = f"Repository: {repo}\n\nTitle: {title}\n\nBody:\n{body or '(no body)'}"

    logger.debug("Sending issue %s#%d to LLM for triage", repo, issue_number)
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        tools=[_TRIAGE_TOOL],
        tool_choice={"type": "tool", "name": "triage_issue"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    data = tool_use.input

    logger.info(
        "LLM triage for %s#%d — category=%s priority=%s",
        repo,
        issue_number,
        data["category"],
        data["priority"],
    )
    return TriageResult(
        repo=repo,
        issue_number=issue_number,
        category=data["category"],
        priority=data["priority"],
        suggested_labels=data["suggested_labels"],
        reason=data["reason"],
    )
