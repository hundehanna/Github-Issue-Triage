"""Ingest repository documentation into the RAG vector store.

Run directly::

    python -m app.services.doc_ingestor docs/
    # or via env var:
    DOCS_DIR=docs/ python -m app.services.doc_ingestor

Only Markdown (``*.md``) and plain-text (``*.txt``) files are indexed.
Each file is split into overlapping chunks before embedding so that long
documents don't exceed the model's context window.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.services.retrieval_service import embed_documents

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 512
_CHUNK_OVERLAP = 50
_SUPPORTED_EXTENSIONS = {".md", ".txt"}


def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split *text* into overlapping fixed-size character chunks."""
    if not text.strip():
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def ingest_directory(docs_path: str | Path) -> int:
    """Index all supported files under *docs_path*.

    Returns the number of chunks indexed.
    """
    root = Path(docs_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {docs_path}")

    total_chunks = 0
    for file_path in sorted(root.rglob("*")):
        if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        chunks = _chunk_text(text)
        if not chunks:
            continue
        relative = file_path.relative_to(root)
        ids = [f"{relative}::{i}" for i in range(len(chunks))]
        metadatas = [{"filename": file_path.name, "path": str(relative), "chunk": i} for i in range(len(chunks))]
        embed_documents(chunks, ids, metadatas)
        total_chunks += len(chunks)
        logger.info("Indexed %s → %d chunk(s)", relative, len(chunks))

    logger.info("Ingestion complete — %d total chunk(s) from %s", total_chunks, root)
    return total_chunks


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DOCS_DIR", "docs")
    ingested = ingest_directory(path)
    print(f"Indexed {ingested} chunk(s) from '{path}'")
