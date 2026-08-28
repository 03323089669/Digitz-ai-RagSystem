from fastapi import APIRouter, Query
from core.db import search_all
from backend.vectordb.chroma_store import store as chroma_store

router = APIRouter(prefix='/search', tags=['search'])

@router.get('/')
def search(query: str = Query(..., min_length=1), brand: str | None = Query(None)):
    results = search_all(query, brand_key=brand)
    if brand:
        chroma_hits = chroma_store.query(brand, query, top_k=5)
        return {
            'query': query,
            'brand': brand,
            'results': results,
            'vector_hits': chroma_hits,
        }
    return {
        'query': query,
        'brand': brand,
        'results': results,
    }
