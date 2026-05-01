"""LangChain-based LLM triage pipeline.

Chain structure:
  ChatPromptTemplate (system + human) → ChatAnthropic.with_structured_output(TriageOutput)

The prompt is rendered with {repo}, {title}, {body}, {context} and piped into
ChatAnthropic, which calls a structured-output tool and returns a TriageOutput
Pydantic object directly. That is then mapped to the TriageResult domain model.

LangSmith tracing is automatic when LANGCHAIN_TRACING_V2=true and
LANGCHAIN_API_KEY are set — no extra code required.
"""
import logging
import os
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.models.triage import TriageResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

class TriageOutput(BaseModel):
    """Pydantic schema that the LLM must populate via structured output / tool call."""

    category: Literal["Bug", "Feature Request", "Documentation", "Question", "Other"] = Field(
        description="The nature of the issue."
    )
    priority: Literal["High", "Medium", "Low"] = Field(
        description="Urgency level based on impact and severity."
    )
    suggested_labels: list[str] = Field(
        description="GitHub labels to apply (e.g. 'bug', 'priority-high')."
    )
    reason: str = Field(
        description="One or two sentences explaining the triage decision."
    )


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a senior open-source maintainer performing issue triage. "
    "Analyse the provided GitHub issue and call the triage_issue tool with your assessment. "
    "Use the provided repository context to inform your triage where relevant. "
    "Be concise and consistent."
)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    (
        "human",
        "Repository: {repo}\n\nTitle: {title}\n\nBody:\n{body}"
        "{context_section}",
    ),
])


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def classify_with_llm(
    repo: str,
    issue_number: int,
    title: str,
    body: str,
    *,
    context: str = "",
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> TriageResult:
    """Classify a GitHub issue using a LangChain → Claude pipeline.

    Raises on any API or validation error (caller handles fallback).
    LangSmith tracing is automatic when LANGCHAIN_TRACING_V2=true.
    """
    llm = ChatAnthropic(
        model=model,
        api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
        max_tokens=512,
    )

    # Build the chain: prompt | model with structured output
    chain = _PROMPT | llm.with_structured_output(TriageOutput)

    context_section = (
        f"\n\n--- Relevant context from repository ---\n{context}" if context else ""
    )

    logger.debug("Sending issue %s#%d to LLM chain for triage", repo, issue_number)

    output: TriageOutput = chain.invoke({
        "repo": repo,
        "title": title,
        "body": body or "(no body)",
        "context_section": context_section,
    })

    logger.info(
        "LLM triage for %s#%d — category=%s priority=%s",
        repo,
        issue_number,
        output.category,
        output.priority,
    )

    return TriageResult(
        repo=repo,
        issue_number=issue_number,
        category=output.category,
        priority=output.priority,
        suggested_labels=output.suggested_labels,
        reason=output.reason,
    )
