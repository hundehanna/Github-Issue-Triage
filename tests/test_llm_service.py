"""Tests for the LangChain-based LLM triage service.

We mock _get_llm() so no real API calls are made. The chain is:
  ChatPromptTemplate | llm.with_structured_output(TriageOutput)

Strategy: patch `_get_llm` so it returns a fake LLM whose
`with_structured_output(TriageOutput)` is a real `RunnableLambda` that
emits a fake TriageOutput. The lambda receives the rendered prompt as
input so tests can also assert what reached the LLM stage.

Patching `_get_llm` (not the provider classes) means these tests work
regardless of LLM_PROVIDER — anthropic, gemini, or anything else.
"""
import os
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.runnables import RunnableLambda

from app.services.llm_service import TriageOutput, classify_with_llm, _get_llm


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


def _patch_llm(mock_get_llm, output: TriageOutput, capture: list | None = None):
    """Make _get_llm return a fake whose chain emits `output`.

    If `capture` is provided, each invocation appends the rendered prompt.
    """
    def _lambda(prompt_value):
        if capture is not None:
            capture.append(prompt_value)
        return output

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = RunnableLambda(_lambda)
    mock_get_llm.return_value = mock_llm
    return mock_llm


# ---------------------------------------------------------------------------
# Core classification tests
# ---------------------------------------------------------------------------

@patch("app.services.llm_service._get_llm")
def test_classify_returns_triage_result(mock_get_llm):
    _patch_llm(mock_get_llm, _fake_output(
        category="Bug", priority="High", labels=["bug", "priority-high"], reason="Crash in prod",
    ))

    result = classify_with_llm("owner/repo", 42, "App crashes on startup", "", api_key="fake")

    assert result.category == "Bug"
    assert result.priority == "High"
    assert result.suggested_labels == ["bug", "priority-high"]
    assert result.reason == "Crash in prod"
    assert result.repo == "owner/repo"
    assert result.issue_number == 42


@patch("app.services.llm_service._get_llm")
def test_classify_renders_title_and_body_into_prompt(mock_get_llm):
    captured: list = []
    _patch_llm(mock_get_llm, _fake_output(), capture=captured)

    classify_with_llm("owner/repo", 1, "My title", "My body", api_key="fake")

    rendered = str(captured[0])
    assert "My title" in rendered
    assert "My body" in rendered
    assert "owner/repo" in rendered


@patch("app.services.llm_service._get_llm")
def test_classify_includes_context_section(mock_get_llm):
    captured: list = []
    _patch_llm(mock_get_llm, _fake_output(), capture=captured)

    classify_with_llm("owner/repo", 1, "title", "body",
                     context="some retrieved doc", api_key="fake")

    rendered = str(captured[0])
    assert "some retrieved doc" in rendered


@patch("app.services.llm_service._get_llm")
def test_classify_feature_request(mock_get_llm):
    _patch_llm(mock_get_llm, _fake_output(
        category="Feature Request", priority="Low",
        labels=["feature-request", "priority-low"],
    ))

    result = classify_with_llm("owner/repo", 7, "Add dark mode", "", api_key="fake")

    assert result.category == "Feature Request"
    assert result.priority == "Low"


@patch("app.services.llm_service._get_llm")
def test_classify_propagates_api_error(mock_get_llm):
    def _raise(_):
        raise Exception("API unavailable")

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = RunnableLambda(_raise)
    mock_get_llm.return_value = mock_llm

    with pytest.raises(Exception, match="API unavailable"):
        classify_with_llm("owner/repo", 1, "title", "body", api_key="fake")


# ---------------------------------------------------------------------------
# Provider selection tests (_get_llm)
# ---------------------------------------------------------------------------

class TestProviderSelection:
    """Tests for the LLM_PROVIDER env var switching between providers."""

    def test_default_provider_is_anthropic(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        llm = _get_llm(api_key="fake")
        # ChatAnthropic instances have a 'model' attribute
        assert "claude" in str(llm.model).lower()

    def test_anthropic_provider_explicit(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        llm = _get_llm(api_key="fake")
        assert "claude" in str(llm.model).lower()

    def test_gemini_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        llm = _get_llm(api_key="fake")
        # ChatGoogleGenerativeAI has a 'model' attribute too
        assert "gemini" in str(llm.model).lower()

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            _get_llm(api_key="fake")

    def test_provider_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "GEMINI")
        llm = _get_llm(api_key="fake")
        assert "gemini" in str(llm.model).lower()
