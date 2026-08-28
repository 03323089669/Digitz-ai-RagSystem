from pathlib import Path

from backend.vectordb.chroma_store import LocalChromaStore
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vectordb.chroma_store import LocalChromaStore

def test_local_chroma_upsert_and_query(tmp_path: Path) -> None:
    store = LocalChromaStore(
        persist_directory=str(tmp_path / "chroma_db")
    )

    doc_id = store.upsert_chunk(
        brand_key="demo",
        document_id="doc-1",
        doc_title="Demo",
        chunk_index=0,
        chunk_text="Enterprise AI knowledge base for digital campaigns.",
        embedding=[0.1] * 384,
    )

    assert doc_id == "doc-1:0"

    results = store.query(
        brand_key="demo",
        query_text="digital campaigns",
        top_k=3,
    )

    assert len(results) > 0
    assert results[0]["metadata"]["document_id"] == "doc-1"