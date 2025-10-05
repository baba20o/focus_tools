#!/usr/bin/env python3
"""
focus_rag_adapter.py — Import-based adapter to EIS_CHATBOT RAG engine.

Purpose:
- Provide a minimal, optional bridge from Focus Tools to the EIS RAG search.
- Keep it strictly opt-in and scoped: use path filters derived from Focus bundles
  to limit semantic retrieval to relevant repos/paths.

Env:
  EIS_CHATBOT_PATH   Absolute path to the EIS_CHATBOT repo (optional if folder
                     exists adjacent to current working dir).

API:
  rag_search(question: str, path_filters: list[str], k: int = 5, debug: bool=False) -> list[dict]
    Returns a list of chunks with fields: {url, text, score, source_type?}

Notes:
- We import EIS modules lazily and degrade gracefully if unavailable.
- We call rag_engine.enhanced_search_for_basic_questions first if present,
  otherwise fall back to vector_store.search.
- Path scoping is implemented by filtering the returned docs by simple
  substring matches against normalized scope hints derived from path_filters.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _ensure_eis_on_path() -> None:
    """Add EIS_CHATBOT_PATH (or ./EIS_CHATBOT) to sys.path once."""
    # Already available?
    if any("eis_chatbot" in (p or "") for p in sys.modules.keys()):
        return
    added = False
    root_env = os.getenv("EIS_CHATBOT_PATH", "").strip()
    if root_env:
        p = Path(root_env).expanduser().resolve()
        if p.exists() and str(p) not in sys.path:
            sys.path.append(str(p))
            added = True
    if not added:
        # Fallback to local folder if present
        local = Path.cwd() / "EIS_CHATBOT"
        if local.exists() and str(local) not in sys.path:
            sys.path.append(str(local))


def _normalize_hint(s: str) -> str:
    return s.replace("\\", "/").lower()


def _scope_hints_from_paths(path_filters: List[str]) -> List[str]:
    """Generate a small set of case-insensitive substr hints from absolute paths.

    Heuristic: include repo base name and the last 2 directories of each path.
    """
    hints: List[str] = []
    for p in path_filters or []:
        try:
            parts = Path(p).parts
        except Exception:
            parts = tuple(str(p).replace("\\", "/").split("/"))
        parts = tuple(x for x in parts if x and x not in ("/", "\\"))
        if not parts:
            continue
        # repo/base name
        hints.append(parts[-1])
        # last two directories (if available)
        if len(parts) >= 2:
            hints.append("/".join(parts[-2:]))
        if len(parts) >= 3:
            hints.append("/".join(parts[-3:]))
    # Deduplicate, normalize
    out: List[str] = []
    seen = set()
    for h in hints:
        nh = _normalize_hint(h)
        if nh and nh not in seen:
            out.append(nh)
            seen.add(nh)
    return out


def _filter_docs_by_scope(docs: List[Dict[str, Any]], path_filters: List[str]) -> List[Dict[str, Any]]:
    if not docs:
        return []
    hints = _scope_hints_from_paths(path_filters)
    if not hints:
        return docs
    out: List[Dict[str, Any]] = []
    for d in docs:
        url = _normalize_hint(str(d.get("url", "")))
        text = _normalize_hint(str(d.get("text", d.get("content", ""))))
        if any(h in url or h in text for h in hints):
            out.append(d)
    # If nothing matched, return originals to avoid empty results
    return out or docs


def rag_search(
    question: str,
    path_filters: Optional[List[str]] = None,
    k: int = 5,
    debug: bool = False,
    source_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Search EIS RAG within a scoped set of path hints.

    Returns a list of chunks: {url, text, score, source_type?}
    """
    _ensure_eis_on_path()
    try:
        # Prefer rag_engine (hybrid + BM25 + intent boosts)
        from eis_chatbot.services import rag_engine  # type: ignore
        use_rag_engine = True
    except Exception:
        use_rag_engine = False
        rag_engine = None  # type: ignore
    docs: List[Dict[str, Any]] = []
    try:
        if use_rag_engine and hasattr(rag_engine, "enhanced_search_for_basic_questions"):
            # Ask for a bit more then filter by scope
            # If source_types are provided, pass them as include_sources to honor caller's preference
            kwargs = {"k": max(k * 3, 10)}
            if source_types:
                kwargs["include_sources"] = source_types
            raw = rag_engine.enhanced_search_for_basic_questions(question, **kwargs)  # type: ignore
            # Normalize each doc shape
            for d in raw or []:
                url = d.get("url") or d.get("source_url") or ""
                text = d.get("text") or d.get("content") or ""
                score = float(d.get("score", d.get("hybrid_score", d.get("vector_score", 0.0))))
                docs.append({"url": url, "text": text, "score": score, "source_type": d.get("source_type")})
        else:
            # Fallback to vector store search
            from eis_chatbot.services import vector_store  # type: ignore
            if source_types:
                raw = vector_store.search_with_filters(question, source_types=source_types, k=max(k, 10))
            else:
                raw = vector_store.search(question, k=max(k * 3, 10))
            for d in raw or []:
                url = d.get("url") or ""
                text = d.get("text") or d.get("content") or ""
                score = float(d.get("score", 0.0))
                docs.append({"url": url, "text": text, "score": score, "source_type": d.get("source_type")})
    except Exception as e:
        if debug:
            sys.stderr.write(f"[RAG-ADAPTER] Error calling EIS engine: {e}\n")
        return []

    # Scope to hints derived from path_filters
    filtered = _filter_docs_by_scope(docs, path_filters or [])
    # Apply source type filtering post-hoc if requested
    if source_types:
        st = {s.lower() for s in source_types}
        filtered = [d for d in filtered if str(d.get("source_type", "")).lower() in st]
    # Truncate to k
    return filtered[:k]


__all__ = ["rag_search"]
