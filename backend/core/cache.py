"""
In-memory caching layer for Digitz AI.
Provides LRU caches for embeddings, query results, and ChromaDB lookups.
"""
import hashlib
from functools import lru_cache
from cachetools import LRUCache, TTLCache
from typing import Any

from .logging import get_logger

logger = get_logger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
EMBEDDING_CACHE_SIZE = 512
EMBEDDING_CACHE_TTL = 3600  # 1 hour

QUERY_CACHE_SIZE = 256
QUERY_CACHE_TTL = 300  # 5 minutes

CHROMA_CACHE_SIZE = 128
CHROMA_CACHE_TTL = 120  # 2 minutes

# ── Caches ─────────────────────────────────────────────────────────────────
_embedding_cache: TTLCache = TTLCache(maxsize=EMBEDDING_CACHE_SIZE, ttl=EMBEDDING_CACHE_TTL)
_query_cache: TTLCache = TTLCache(maxsize=QUERY_CACHE_SIZE, ttl=QUERY_CACHE_TTL)
_chroma_cache: TTLCache = TTLCache(maxsize=CHROMA_CACHE_SIZE, ttl=CHROMA_CACHE_TTL)
_document_cache: TTLCache = TTLCache(maxsize=128, ttl=60)


def _make_key(*args, **kwargs) -> str:
    """Generate a deterministic cache key from args/kwargs."""
    raw = str(args) + str(sorted(kwargs.items()))
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def get_embedding_cache(text: str) -> list[float] | None:
    """Retrieve cached embedding if available."""
    key = _make_key(text)
    cached = _embedding_cache.get(key)
    if cached is not None:
        logger.debug(f"Embedding cache HIT for text(len={len(text)})")
    return cached


def set_embedding_cache(text: str, embedding: list[float]) -> None:
    """Store embedding in cache."""
    key = _make_key(text)
    _embedding_cache[key] = embedding
    logger.debug(f"Embedding cache SET for text(len={len(text)}) dim={len(embedding)}")


def get_query_cache(query: str, brand: str, mode: str | None = None) -> dict | None:
    """Retrieve cached query result."""
    key = _make_key(query, brand, mode)
    cached = _query_cache.get(key)
    if cached is not None:
        logger.debug(f"Query cache HIT for brand='{brand}' query='{query[:40]}...'")
    return cached


def set_query_cache(query: str, brand: str, result: dict, mode: str | None = None) -> None:
    """Store query result in cache."""
    key = _make_key(query, brand, mode)
    _query_cache[key] = result


def get_chroma_cache(brand: str, query_text: str, top_k: int) -> list | None:
    """Retrieve cached ChromaDB results."""
    key = _make_key(brand, query_text, top_k)
    cached = _chroma_cache.get(key)
    if cached is not None:
        logger.debug(f"Chroma cache HIT for brand='{brand}' query='{query_text[:40]}...'")
    return cached


def set_chroma_cache(brand: str, query_text: str, top_k: int, results: list) -> None:
    """Store ChromaDB results in cache."""
    key = _make_key(brand, query_text, top_k)
    _chroma_cache[key] = results


def invalidate_brand_cache(brand: str) -> None:
    """Invalidate all caches for a given brand (called after upload)."""
    keys_to_delete = []
    for cache in [_embedding_cache, _query_cache, _chroma_cache]:
        for k in list(cache.keys()):
            if brand in str(k):
                keys_to_delete.append(k)
    for k in keys_to_delete:
        _embedding_cache.pop(k, None)
        _query_cache.pop(k, None)
        _chroma_cache.pop(k, None)
    logger.info(f"Invalidated caches for brand='{brand}' ({len(keys_to_delete)} entries)")


def get_cache_stats() -> dict:
    """Return cache statistics for monitoring."""
    return {
        'embedding_cache': {
            'size': len(_embedding_cache),
            'maxsize': EMBEDDING_CACHE_SIZE,
            'ttl': EMBEDDING_CACHE_TTL,
        },
        'query_cache': {
            'size': len(_query_cache),
            'maxsize': QUERY_CACHE_SIZE,
            'ttl': QUERY_CACHE_TTL,
        },
        'chroma_cache': {
            'size': len(_chroma_cache),
            'maxsize': CHROMA_CACHE_SIZE,
            'ttl': CHROMA_CACHE_TTL,
        },
    }




