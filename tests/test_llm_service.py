"""Tests for the LLM triage service.

All tests mock the Anthropic client so no real API calls are made.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm_service import classify_with_llm


def _make_llm_response(category="Bug", priority="High", labels=None, reason="test reason"):
    """Build a fake Anthropic messages.create() response."""
    if labels is None:
        labels = ["bug", "priority-high"]
    tool_use_block = SimpleNamespace(
        type="tool_use",
        input={
            "category": category,
            "priority": priority,
            "suggested_labels": labels,
            "reason": reason,
        },
    )
    return SimpleNamespace(content=[tool_use_block])


@patch("app.services.llm_service.anthropic.Anthropic")
def test_classify_returns_triage_result(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_llm_response(
        category="Bug", priority="High", labels=["bug", "priority-high"], reason="Crash in prod"
    )

    result = classify_with_llm("owner/repo", 42, "App crashes on startup", "", api_key="fake")

    assert result.category == "Bug"
    assert result.priority == "High"
    assert result.suggested_labels == ["bug", "priority-high"]
    assert result.reason == "Crash in prod"
    assert result.repo == "owner/repo"
    assert result.issue_number == 42


@patch("app.services.llm_service.anthropic.Anthropic")
def test_classify_passes_correct_args_to_api(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_llm_response()

    classify_with_llm("owner/repo", 1, "My title", "My body", api_key="fake")

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "triage_issue"}
    assert "My title" in call_kwargs["messages"][0]["content"]
    assert "My body" in call_kwargs["messages"][0]["content"]


@patch("app.services.llm_service.anthropic.Anthropic")
def test_classify_feature_request(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_llm_response(
        category="Feature Request", priority="Low", labels=["feature-request", "priority-low"]
    )

    result = classify_with_llm("owner/repo", 7, "Add dark mode", "", api_key="fake")

    assert result.category == "Feature Request"
    assert result.priority == "Low"


@patch("app.services.llm_service.anthropic.Anthropic")
def test_classify_propagates_api_error(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("API unavailable")

    with pytest.raises(Exception, match="API unavailable"):
        classify_with_llm("owner/repo", 1, "title", "body", api_key="fake")
