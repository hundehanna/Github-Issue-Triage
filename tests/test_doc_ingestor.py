"""Tests for app.services.doc_ingestor.

Covers both the structure-aware Markdown chunking pipeline and the
legacy fixed-size helper.
"""

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
# Legacy fixed-size chunker (still exported for backwards compatibility)
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
# ingest_directory — happy paths
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


# ---------------------------------------------------------------------------
# Structure-aware Markdown chunking
# ---------------------------------------------------------------------------

class TestStructureAwareChunking:
    """The Markdown ingestor should split on headings, not arbitrary char counts."""

    def test_short_sections_become_one_chunk_per_section(self, tmp_path):
        md = (
            "# Top Level\n\n"
            "## Section A\n\n"
            "Content for section A.\n\n"
            "## Section B\n\n"
            "Content for section B.\n"
        )
        (tmp_path / "doc.md").write_text(md)
        ingest_directory(tmp_path)

        col = rs._get_collection("docs")
        records = col.get(include=["documents", "metadatas"])
        docs = records["documents"]

        # Each section's heading + content should land in a single chunk.
        assert any("Section A" in d and "Content for section A" in d for d in docs)
        assert any("Section B" in d and "Content for section B" in d for d in docs)

    def test_heading_path_stored_in_metadata(self, tmp_path):
        md = (
            "# Setup Guide\n\n"
            "## Environment Variables\n\n"
            "Set `LOG_FORMAT=json` for structured logs.\n"
        )
        (tmp_path / "doc.md").write_text(md)
        ingest_directory(tmp_path)

        col = rs._get_collection("docs")
        records = col.get(include=["metadatas"])
        metadatas = records["metadatas"]

        heading_paths = [m.get("heading_path", "") for m in metadatas]
        assert any("Setup Guide" in hp and "Environment Variables" in hp for hp in heading_paths)

    def test_table_like_section_stays_together(self, tmp_path):
        """A short list/table should land in a single chunk, not be split mid-row."""
        md = (
            "# Reference\n\n"
            "## Variables\n\n"
            "| Var | Default | Description |\n"
            "|---|---|---|\n"
            "| `LOG_LEVEL` | INFO | Log verbosity |\n"
            "| `LOG_FORMAT` | text | text or json |\n"
            "| `DOCS_DIR` | - | Docs path |\n"
        )
        (tmp_path / "ref.md").write_text(md)
        ingest_directory(tmp_path)

        col = rs._get_collection("docs")
        records = col.get(include=["documents"])
        # The whole table should appear in a single chunk.
        joined_chunks = records["documents"]
        for chunk in joined_chunks:
            if "LOG_FORMAT" in chunk:
                assert "LOG_LEVEL" in chunk and "DOCS_DIR" in chunk
                return
        pytest.fail("No chunk contained the full env-var table")

    def test_long_section_gets_subdivided(self, tmp_path):
        """A section whose content exceeds the chunk size should be split further."""
        long_body = "Paragraph " + ("alpha " * 200) + "\n\nParagraph " + ("beta " * 200)
        md = f"# Long\n\n## Big Section\n\n{long_body}\n"
        (tmp_path / "long.md").write_text(md)
        ingest_directory(tmp_path)

        col = rs._get_collection("docs")
        records = col.get(include=["documents", "metadatas"])
        # Should produce more than one chunk because the section exceeds 512 chars.
        assert len(records["documents"]) > 1
        # All sub-chunks should still carry the same heading path.
        big_chunks = [
            m for m in records["metadatas"]
            if m.get("heading_path", "").endswith("Big Section")
        ]
        assert len(big_chunks) > 1
