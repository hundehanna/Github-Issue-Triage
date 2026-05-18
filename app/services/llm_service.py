"""LangChain-based LLM triage pipeline.

Chain structure:
  ChatPromptTemplate (system + human) → <LLM provider>.with_structured_output(TriageOutput)

The LLM provider is selected via the LLM_PROVIDER env var:
  - "anthropic" (default) → ChatAnthropic, needs ANTHROPIC_API_KEY
  - "gemini" → ChatGoogleGenerativeAI, needs GOOGLE_API_KEY

LangSmith tracing is automatic when LANGCHAIN_TRACING_V2=true and
LANGCHAIN_API_KEY are set.
"""
import logging
import os
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.models.triage import TriageResult

# Load .env automatically so `LLM_PROVIDER`, `GOOGLE_API_KEY`, etc. are
# available even when running uvicorn from any cwd.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
        default="Medium",
        description="Urgency level based on impact and severity.",
    )
    suggested_labels: list[str] = Field(
        default_factory=list,
        description="GitHub labels to apply (e.g. 'bug', 'priority-high').",
    )
    reason: str = Field(
        default="(no reason provided)",
        description="One or two sentences explaining the triage decision.",
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
# Provider selection
# ---------------------------------------------------------------------------

_DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def _get_llm(api_key: str | None = None, model: str | None = None) -> BaseChatModel:
    """Pick the LLM provider based on LLM_PROVIDER env var.

    Supported: 'anthropic' (default), 'gemini'.
    """
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model or os.getenv("GEMINI_MODEL") or _DEFAULT_GEMINI_MODEL,
            google_api_key=api_key or os.getenv("GOOGLE_API_KEY"),
            max_output_tokens=512,
        )

    if provider == "anthropic":
        return ChatAnthropic(
            model=model or os.getenv("ANTHROPIC_MODEL") or _DEFAULT_ANTHROPIC_MODEL,
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            max_tokens=512,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER='{provider}'. Use 'anthropic' or 'gemini'."
    )


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
    model: str | None = None,
) -> TriageResult:
    """Classify a GitHub issue using a LangChain → LLM pipeline.

    Provider is selected via LLM_PROVIDER env var. Raises on any API or
    validation error (caller handles fallback). LangSmith tracing is
    automatic when LANGCHAIN_TRACING_V2=true.
    """
    llm = _get_llm(api_key=api_key, model=model)

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
