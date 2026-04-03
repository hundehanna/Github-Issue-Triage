"""RAG retrieval service backed by ChromaDB.

Two collections are maintained:
  - ``docs``   — chunks from repository documentation (Markdown files)
  - ``issues`` — past triaged issues stored after each successful triage run

Usage::

    from app.services import retrieval_service

    context = retrieval_service.get_context(title, body)
    retrieval_service.index_issue(repo, number, title, body, labels)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger(__name__)

_DOCS_COLLECTION = "docs"
_ISSUES_COLLECTION = "issues"
_MAX_CONTEXT_CHARS = 1_500

# Module-level singleton — reset to None in tests via _reset_client()
_client: chromadb.ClientAPI | None = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        db_path = os.getenv("CHROMA_DB_PATH")
        if db_path:
            logger.info("ChromaDB: using persistent store at %s", db_path)
            _client = chromadb.PersistentClient(path=db_path)
        else:
            logger.info("ChromaDB: using ephemeral in-memory store")
            _client = chromadb.EphemeralClient()
    return _client


def _reset_client() -> None:
    """Reset the module-level singleton. For use in tests only."""
    global _client
    _client = None


def _get_collection(name: str) -> chromadb.Collection:
    return _get_client().get_or_create_collection(
        name=name,
        embedding_function=DefaultEmbeddingFunction(),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_documents(
    texts: list[str],
    ids: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    collection_name: str = _DOCS_COLLECTION,
) -> None:
    """Upsert document chunks into *collection_name*."""
    if not texts:
        return
    col = _get_collection(collection_name)
    # ChromaDB 1.5+ rejects empty metadata dicts; omit the field entirely when
    # no metadata is supplied.
    upsert_kwargs: dict[str, Any] = {"ids": ids, "documents": texts}
    if metadatas:
        upsert_kwargs["metadatas"] = metadatas
    col.upsert(**upsert_kwargs)
    logger.debug("Upserted %d chunk(s) into '%s'", len(texts), collection_name)


def index_issue(
    repo: str,
    issue_number: int,
    title: str,
    body: str,
    labels: list[str],
) -> None:
    """Store a triaged issue so it can be retrieved as future context."""
    doc_id = f"{repo}#{issue_number}"
    text = f"Title: {title}\n\n{body or ''}"
    metadata: dict[str, Any] = {
        "repo": repo,
        "issue_number": issue_number,
        "labels": ", ".join(labels),
    }
    col = _get_collection(_ISSUES_COLLECTION)
    col.upsert(ids=[doc_id], documents=[text], metadatas=[metadata])
    logger.debug("Indexed past issue: %s", doc_id)


def get_context(title: str, body: str, n_results: int = 3) -> str:
    """Return a formatted context string of relevant docs and past issues.

    Returns an empty string when both collections are empty or on any error.
    """
    query = f"{title}\n{body or ''}"
    chunks: list[str] = []

    for collection_name, label in [(_DOCS_COLLECTION, "Documentation"), (_ISSUES_COLLECTION, "Similar issue")]:
        try:
            col = _get_collection(collection_name)
            count = col.count()
            if count == 0:
                continue
            result = col.query(query_texts=[query], n_results=min(n_results, count))
            for doc in result["documents"][0]:
                chunks.append(f"[{label}]\n{doc}")
        except Exception as exc:
            logger.warning("RAG retrieval failed for collection '%s': %s", collection_name, exc)

    if not chunks:
        return ""

    context = "\n\n".join(chunks)
    if len(context) > _MAX_CONTEXT_CHARS:
        context = context[:_MAX_CONTEXT_CHARS] + "\n...(truncated)"
    return context
