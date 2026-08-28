"""Quick import validation script."""
import sys
print('Python:', sys.version)
try:
    from core.db import init_db
    print('core.db OK')
except Exception as e:
    print(f'core.db ERROR: {e}')

try:
    from vectordb.chroma_store import store
    print('chroma_store OK')
    cols = store.list_collections()
    print(f'Collections: {cols}')
except Exception as e:
    print(f'chroma_store ERROR: {e}')

try:
    from core.cache import get_cache_stats
    stats = get_cache_stats()
    print(f'cache OK: {stats}')
except Exception as e:
    print(f'cache ERROR: {e}')

try:
    from core.rag_chain import retrieve_chunks, run_query
    print('rag_chain OK')
except Exception as e:
    print(f'rag_chain ERROR: {e}')

print('=== ALL IMPORTS OK ===')

