"""Tests for app.services.doc_ingestor."""

import pytest

import app.services.retrieval_service as rs
from app.services.doc_ingestor import _chunk_text, ingest_directory


@pytest.fixture(autouse=True)
def reset_chroma(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma"))
    rs._reset_client()
    yield
    rs._reset_client()


# ---------------------------------------------------------------------------
# Chunking helper
# ---------------------------------------------------------------------------


def test_chunk_text_splits_long_text():
    text = "x" * 1000
    chunks = _chunk_text(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_chunk_text_empty_returns_empty():
    assert _chunk_text("") == []
    assert _chunk_text("   ") == []


# ---------------------------------------------------------------------------
# ingest_directory
# ---------------------------------------------------------------------------


def test_ingest_indexes_md_files(tmp_path):
    (tmp_path / "guide.md").write_text("# Setup Guide\nRun pip install to get started.")
    (tmp_path / "faq.md").write_text("# FAQ\nQ: How do I reset my password?")

    count = ingest_directory(tmp_path)
    assert count >= 2  # at least one chunk per file

    context = rs.get_context("pip install setup", "")
    assert context != ""


def test_ingest_skips_non_md_files(tmp_path):
    (tmp_path / "readme.md").write_text("# Readme\nThis is the readme.")
    (tmp_path / "script.py").write_text("print('hello')")

    ingest_directory(tmp_path)

    col = rs._get_collection("docs")
    ids = col.get()["ids"]
    assert all(".py" not in doc_id for doc_id in ids)


def test_ingest_raises_for_missing_directory():
    with pytest.raises(ValueError, match="Not a directory"):
        ingest_directory("/nonexistent/path/xyz")
