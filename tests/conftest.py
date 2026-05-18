"""Pytest configuration.

Strips LLM provider env vars before every test so the unit test suite
exercises the keyword-fallback path deterministically, regardless of
what's in the developer's local `.env`.

Tests that DO want the LLM path active mock `_get_llm` directly (see
tests/test_llm_service.py), so they're unaffected.

The eval runner (tests/eval/run_eval.py) is invoked outside pytest, so
this fixture doesn't apply there.
"""
import os

import pytest


_LLM_ENV_VARS = (
    "LLM_PROVIDER",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "GOOGLE_API_KEY",
    "GEMINI_MODEL",
)


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    """Unset all LLM-related env vars for the duration of every test."""
    for var in _LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
