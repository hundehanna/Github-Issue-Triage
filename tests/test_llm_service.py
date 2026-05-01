"""Tests for the LangChain-based LLM triage service.

We mock the ChatAnthropic model so no real API calls are made.

The chain is:  ChatPromptTemplate | ChatAnthropic.with_structured_output(TriageOutput)

Strategy: patch `langchain_anthropic.ChatAnthropic` so that
`llm.with_structured_output(TriageOutput)` returns a real `RunnableLambda`
that emits a fake TriageOutput. The lambda receives the rendered prompt as
input, so we can also assert what variables were passed in.
"""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.runnables import RunnableLambda

from app.services.llm_service import TriageOutput, classify_with_llm


def _fake_output(
    category="Bug",
    priority="High",
    labels=None,
    reason="test reason",
) -> TriageOutput:
    return TriageOutput(
        category=category,
        priority=priority,
        suggested_labels=labels or ["bug", "priority-high"],
        reason=reason,
    )


def _patch_chat_anthropic(mock_cls, output: TriageOutput, capture: list | None = None):
    """Wire up mock_cls so chain `_PROMPT | llm.with_structured_output(...)` returns `output`.

    If `capture` is provided, each invocation of the lambda appends the rendered
    prompt to it so tests can inspect what reached the LLM stage.
    """
    def _lambda(prompt_value):
        if capture is not None:
            capture.append(prompt_value)
        return output

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = RunnableLambda(_lambda)
    mock_cls.return_value = mock_llm
    return mock_llm


@patch("app.services.llm_service.ChatAnthropic")
def test_classify_returns_triage_result(mock_cls):
    _patch_chat_anthropic(mock_cls, _fake_output(
        category="Bug", priority="High", labels=["bug", "priority-high"], reason="Crash in prod",
    ))

    result = classify_with_llm("owner/repo", 42, "App crashes on startup", "", api_key="fake")

    assert result.category == "Bug"
    assert result.priority == "High"
    assert result.suggested_labels == ["bug", "priority-high"]
    assert result.reason == "Crash in prod"
    assert result.repo == "owner/repo"
    assert result.issue_number == 42


@patch("app.services.llm_service.ChatAnthropic")
def test_classify_renders_title_and_body_into_prompt(mock_cls):
    captured: list = []
    _patch_chat_anthropic(mock_cls, _fake_output(), capture=captured)

    classify_with_llm("owner/repo", 1, "My title", "My body", api_key="fake")

    # captured[0] is the rendered ChatPromptValue. Stringifying gives the messages.
    rendered = str(captured[0])
    assert "My title" in rendered
    assert "My body" in rendered
    assert "owner/repo" in rendered


@patch("app.services.llm_service.ChatAnthropic")
def test_classify_includes_context_section(mock_cls):
    captured: list = []
    _patch_chat_anthropic(mock_cls, _fake_output(), capture=captured)

    classify_with_llm("owner/repo", 1, "title", "body",
                     context="some retrieved doc", api_key="fake")

    rendered = str(captured[0])
    assert "some retrieved doc" in rendered


@patch("app.services.llm_service.ChatAnthropic")
def test_classify_feature_request(mock_cls):
    _patch_chat_anthropic(mock_cls, _fake_output(
        category="Feature Request", priority="Low",
        labels=["feature-request", "priority-low"],
    ))

    result = classify_with_llm("owner/repo", 7, "Add dark mode", "", api_key="fake")

    assert result.category == "Feature Request"
    assert result.priority == "Low"


@patch("app.services.llm_service.ChatAnthropic")
def test_classify_propagates_api_error(mock_cls):
    def _raise(_):
        raise Exception("API unavailable")

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = RunnableLambda(_raise)
    mock_cls.return_value = mock_llm

    with pytest.raises(Exception, match="API unavailable"):
        classify_with_llm("owner/repo", 1, "title", "body", api_key="fake")
