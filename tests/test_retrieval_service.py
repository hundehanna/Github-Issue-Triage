"""Tests for app.services.retrieval_service.

All tests use ChromaDB's EphemeralClient (in-memory) by ensuring
CHROMA_DB_PATH is unset and resetting the module-level singleton before
each test via retrieval_service._reset_client().
"""

import pytest

import app.services.retrieval_service as rs


@pytest.fixture(autouse=True)
def reset_chroma(monkeypatch, tmp_path):
    """Give every test its own isolated ChromaDB PersistentClient."""
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma"))
    rs._reset_client()
    yield
    rs._reset_client()


# ---------------------------------------------------------------------------
# embed_documents / get_context — docs collection
# ---------------------------------------------------------------------------


def test_embed_and_retrieve_doc():
    rs.embed_documents(
        texts=["The login button is broken on mobile devices."],
        ids=["doc::1"],
    )
    context = rs.get_context("login button not working", "")
    assert "login button" in context


def test_get_context_returns_string():
    rs.embed_documents(texts=["FastAPI route documentation."], ids=["doc::2"])
    result = rs.get_context("FastAPI routes", "how do routes work?")
    assert isinstance(result, str)


def test_empty_collections_return_empty_string():
    result = rs.get_context("anything", "")
    assert result == ""


# ---------------------------------------------------------------------------
# index_issue / get_context — issues collection
# ---------------------------------------------------------------------------


def test_index_and_retrieve_past_issue():
    rs.index_issue(
        repo="owner/repo",
        issue_number=42,
        title="App crashes on startup",
        body="NullPointerException in main()",
        labels=["bug", "priority-high"],
    )
    context = rs.get_context("crash on startup", "exception at launch")
    assert "crash" in context.lower() or "startup" in context.lower()


def test_index_issue_metadata_stored():
    rs.index_issue(
        repo="owner/repo",
        issue_number=7,
        title="Add dark mode",
        body="Would be nice to have a dark theme.",
        labels=["enhancement"],
    )
    col = rs._get_collection("issues")
    result = col.get(ids=["owner/repo#7"])
    assert result["ids"] == ["owner/repo#7"]
    assert result["metadatas"][0]["labels"] == "enhancement"


# ---------------------------------------------------------------------------
# Context truncation
# ---------------------------------------------------------------------------


def test_context_is_truncated_to_max_chars():
    long_text = "A" * 2000
    rs.embed_documents(texts=[long_text], ids=["doc::long"])
    context = rs.get_context("AAAA", "")
    assert len(context) <= rs._MAX_CONTEXT_CHARS + len("\n...(truncated)")
