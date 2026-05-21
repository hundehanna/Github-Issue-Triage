"""Ingest repository documentation into the RAG vector store.

Run directly::

    python -m app.services.doc_ingestor docs/
    DOCS_DIR=docs/ python -m app.services.doc_ingestor

Chunking strategy
-----------------
Markdown files are split with a two-stage strategy that respects document
structure rather than chopping by fixed character counts:

1. ``MarkdownHeaderTextSplitter`` first splits a file on its ``#``, ``##``
   and ``###`` headings, so each section stays in one chunk. The heading
   path (e.g. *"Environment Variables > LOG_FORMAT"*) is preserved as
   metadata.
2. ``RecursiveCharacterTextSplitter`` then splits any oversized section by
   paragraph → sentence → word boundaries, preferring natural breaks.

Plain text files (``*.txt``) skip stage 1 and use only the recursive
splitter. Each emitted chunk carries ``filename``, ``path``, ``chunk``,
and (for Markdown) ``heading_path`` metadata.

The legacy ``_chunk_text`` helper is retained for backwards-compatible
imports but is no longer used by ``ingest_directory``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.services.retrieval_service import embed_documents

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 512
_CHUNK_OVERLAP = 50
_SUPPORTED_EXTENSIONS = {".md", ".txt"}

_HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]

_md_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=_HEADERS_TO_SPLIT_ON,
    strip_headers=False,
)

_recursive_splitter = RecursiveCharacterTextSplitter(
    chunk_size=_CHUNK_SIZE,
    chunk_overlap=_CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_directory(docs_path: str | Path) -> int:
    """Index all supported files under *docs_path*. Returns chunk count."""
    root = Path(docs_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {docs_path}")

    total_chunks = 0
    for file_path in sorted(root.rglob("*")):
        ext = file_path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            continue

        text = file_path.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            continue

        relative = file_path.relative_to(root)
        if ext == ".md":
            chunks, metadatas = _split_markdown(text, file_path, relative)
        else:
            chunks, metadatas = _split_plain_text(text, file_path, relative)

        if not chunks:
            continue

        ids = [f"{relative}::{i}" for i in range(len(chunks))]
        embed_documents(chunks, ids, metadatas)
        total_chunks += len(chunks)
        logger.info("Indexed %s -> %d chunk(s)", relative, len(chunks))

    logger.info("Ingestion complete -- %d total chunk(s) from %s", total_chunks, root)
    return total_chunks


# ---------------------------------------------------------------------------
# Splitting helpers
# ---------------------------------------------------------------------------

def _split_markdown(
    text: str,
    file_path: Path,
    relative: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Two-stage split: headers first, then recursive on oversized sections."""
    sections = _md_header_splitter.split_text(text)

    chunks: list[str] = []
    metadatas: list[dict[str, Any]] = []
    for section in sections:
        heading_path = _format_heading_path(section.metadata)
        body = section.page_content
        if len(body) <= _CHUNK_SIZE:
            chunks.append(body)
            metadatas.append(_make_metadata(file_path, relative, len(chunks) - 1, heading_path))
        else:
            # Section too long — split further with the recursive splitter.
            sub_chunks = _recursive_splitter.split_text(body)
            for sc in sub_chunks:
                chunks.append(sc)
                metadatas.append(_make_metadata(file_path, relative, len(chunks) - 1, heading_path))

    return chunks, metadatas


def _split_plain_text(
    text: str,
    file_path: Path,
    relative: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Use the recursive splitter only — plain text has no headings."""
    chunks = _recursive_splitter.split_text(text)
    metadatas = [
        _make_metadata(file_path, relative, i, heading_path="")
        for i in range(len(chunks))
    ]
    return chunks, metadatas


def _format_heading_path(meta: dict[str, Any]) -> str:
    """Render the H1>H2>H3 heading hierarchy as a single string for metadata."""
    parts = [meta.get(level) for level in ("h1", "h2", "h3") if meta.get(level)]
    return " > ".join(parts)


def _make_metadata(
    file_path: Path,
    relative: Path,
    chunk_index: int,
    heading_path: str,
) -> dict[str, Any]:
    md: dict[str, Any] = {
        "filename": file_path.name,
        "path": str(relative),
        "chunk": chunk_index,
    }
    if heading_path:
        md["heading_path"] = heading_path
    return md


# ---------------------------------------------------------------------------
# Legacy helper — kept for backwards compatibility with existing tests
# ---------------------------------------------------------------------------

def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Fixed-size character chunker. Retained for legacy callers; new
    ingestion uses structure-aware splitting via ``ingest_directory``.
    """
    if not text.strip():
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DOCS_DIR", "docs")
    ingested = ingest_directory(path)
    print(f"Indexed {ingested} chunk(s) from '{path}'")
