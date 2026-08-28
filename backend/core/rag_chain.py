import json
import math
import re
import sys
import time as _time
from typing import List

from .db import (
    get_brand,
    get_brand_chunks_topk,
    get_chunk_count,
    get_uploaded_files,
    get_upload_summary,
    record_query,
    reset_uploaded_documents,
    search_all,
)
from .llm_router import ask_llm, ask_llm_with_image, generate_embedding
from .cache import get_chroma_cache, set_chroma_cache, get_query_cache, set_query_cache
from .logging import get_logger
from vectordb.chroma_store import store as chroma_store

logger = get_logger(__name__)


# =============================================================
# Document Cleaning Utilities
# =============================================================

def clean_chunk_text(text: str) -> str:
    """Remove HTML tags, OCR noise, normalize whitespace."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'([^\w\s\n])\1{3,}', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = text.split('\n')
    lines = [line.strip() for line in lines]
    lines = [line for line in lines if not re.match(r'^[\s\W]+$', line)]
    text = '\n'.join(lines).strip()
    return text


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Cosine similarity between two vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude1 = math.sqrt(sum(a * a for a in v1))
    magnitude2 = math.sqrt(sum(b * b for b in v2))
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)


# =============================================================
# MMR Ranking (Maximum Marginal Relevance)
# =============================================================

def mmr_rerank(chunks: List[dict], query_embedding: List[float], top_k: int = 4, lambda_: float = 0.7) -> List[dict]:
    """MMR re-ranking. Uses pre-existing embeddings. Never calls generate_embedding()."""
    if not chunks:
        return []

    selected_indices = []
    candidate_pool = list(chunks)

    for _ in range(min(top_k, len(candidate_pool))):
        if not candidate_pool:
            break

        best_score = -float('inf')
        best_idx = -1

        for i, candidate in enumerate(candidate_pool):
            relevance = candidate.get('score', 0.0)
            diversity_penalty = 0.0
            if selected_indices:
                cand_emb = candidate.get('embedding')
                if cand_emb is not None:
                    for sel_idx in selected_indices:
                        sel_emb = candidate_pool[sel_idx].get('embedding')
                        if sel_emb is not None:
                            sim = cosine_similarity(cand_emb, sel_emb)
                            diversity_penalty = max(diversity_penalty, sim)

            mmr_score = lambda_ * relevance - (1 - lambda_) * diversity_penalty
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        if best_idx >= 0 and best_idx < len(candidate_pool):
            selected_indices.append(best_idx)

    return [chunks[i] for i in selected_indices if i < len(chunks)]


# =============================================================
# Retrieval Pipeline
# =============================================================

def retrieve_chunks_all_brands(query: str, top_k: int = 5) -> List[dict]:
    """Cross-brand retrieval: search across all available brands and combine results.

    Returns a merged list of top chunks with brand metadata preserved.
    """
    from core.db import get_brands, get_brand_chunks_keyword
    from core.llm_router import generate_embedding

    start = _time.time()
    logger.info(f"Cross-brand retrieval for query='{query[:60]}...' top_k={top_k}")

    all_brands = get_brands()
    if not all_brands:
        logger.warning("No brands found in system")
        return []

    all_results = []

    # For each brand, retrieve chunks
    for brand in all_brands:
        brand_key = brand.get('key')
        if not brand_key:
            continue

        try:
            # Try ChromaDB first (faster)
            try:
                chroma_hits = chroma_store.query(brand_key, query, top_k=top_k)
                if chroma_hits:
                    for hit in chroma_hits:
                        cleaned = clean_chunk_text(hit.get('document', ''))
                        if cleaned:
                            all_results.append({
                                'chunk_text': cleaned,
                                'doc_title': hit.get('metadata', {}).get('document_title', 'document'),
                                'brand_key': hit.get('metadata', {}).get('brand', brand_key),
                                'score': hit.get('similarity', 0.0),
                            })
            except Exception as e:
                logger.debug(f"ChromaDB search for brand '{brand_key}' failed: {e}")

            # Keyword search fallback
            try:
                kw_hits = get_brand_chunks_keyword(brand_key, query, top_k=3)
                for item in kw_hits:
                    cleaned = clean_chunk_text(item.get('chunk_text', ''))
                    if cleaned:
                        all_results.append({
                            'chunk_text': cleaned,
                            'doc_title': item.get('doc_title', 'document'),
                            'brand_key': item.get('brand_key', brand_key),
                            'score': item.get('score', 0.5),
                        })
            except Exception as e:
                logger.debug(f"Keyword search for brand '{brand_key}' failed: {e}")

        except Exception as e:
            logger.warning(f"Error retrieving chunks for brand '{brand_key}': {e}")
            continue

    if not all_results:
        logger.info(f"No results found across any brand")
        return []

    # Deduplication & Scoring Sort
    seen_texts = set()
    unique_results = []
    for r in all_results:
        key = r['chunk_text'][:150].strip().lower()
        if key not in seen_texts:
            seen_texts.add(key)
            unique_results.append(r)

    # Sort by score (descending) and return top k
    unique_results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
    final_results = unique_results[:top_k]

    logger.info(f"Cross-brand retrieval complete in {_time.time() - start:.3f}s: returned {len(final_results)} chunks from {len(all_brands)} brands")
    return final_results


def retrieve_chunks(query: str, brand_key: str, top_k: int = 5) -> List[dict]:
    """Optimized High-Speed Hybrid Retrieval pipeline:
    1. Check if brand_key is "ALL" for cross-brand search
    2. Check Chroma cache
    3. Try ChromaDB Vector Search (primary fast index)
    4. Fast SQL Keyword match for high precision
    5. Fallback to SQLite Vector Search only if ChromaDB returned empty
    """
    start = _time.time()
    logger.info(f"Retrieving chunks for brand='{brand_key}' query='{query[:60]}...' top_k={top_k}")

    # Handle cross-brand retrieval
    is_all_brands = brand_key and str(brand_key).strip().upper() in ("ALL", "ALL BRANDS", "ALL_BRANDS", "ALLBRANDS")
    if is_all_brands:
        return retrieve_chunks_all_brands(query, top_k=top_k)

    # Stage 0: Cache Lookup (single brand)
    cache_hits = get_chroma_cache(brand_key, query, top_k)
    if cache_hits:
        logger.info(f"Cache HIT ({len(cache_hits)} results)")
        return cache_hits[:top_k]

    all_results = []

    # Stage 1: ChromaDB Primary Search
    try:
        chroma_hits = chroma_store.query(brand_key, query, top_k=top_k * 2)
        if chroma_hits:
            for hit in chroma_hits:
                cleaned = clean_chunk_text(hit.get('document', ''))
                if cleaned:
                    all_results.append({
                        'chunk_text': cleaned,
                        'doc_title': hit.get('metadata', {}).get('document_title', 'document'),
                        'brand_key': hit.get('metadata', {}).get('brand', brand_key),
                        'score': hit.get('similarity', 0.0),
                    })
            logger.info(f"ChromaDB returned {len(all_results)} hits in {_time.time() - start:.3f}s")
    except Exception as e:
        logger.warning(f"ChromaDB search failed: {e}")

    # Stage 2: Fast Keyword Match (complements vector search)
    try:
        from core.db import get_brand_chunks_keyword
        kw_hits = get_brand_chunks_keyword(brand_key, query, top_k=5)
        for item in kw_hits:
            cleaned = clean_chunk_text(item.get('chunk_text', ''))
            if cleaned:
                all_results.append({
                    'chunk_text': cleaned,
                    'doc_title': item.get('doc_title', 'document'),
                    'brand_key': item.get('brand_key', brand_key),
                    'score': item.get('score', 0.5),
                })
    except Exception as e:
        logger.warning(f"Keyword search failed: {e}")

    # Stage 3: SQLite Vector Fallback (Only if ChromaDB returned empty)
    if not all_results:
        try:
            from core.llm_router import generate_embedding
            from core.db import get_brand_chunks_topk
            query_emb = generate_embedding(query)
            if query_emb:
                sq_hits = get_brand_chunks_topk(brand_key, query_emb, top_k=top_k)
                for item in sq_hits:
                    cleaned = clean_chunk_text(item.get('chunk_text', ''))
                    if cleaned:
                        all_results.append({
                            'chunk_text': cleaned,
                            'doc_title': item.get('doc_title', 'document'),
                            'brand_key': item.get('brand_key', brand_key),
                            'score': item.get('score', 0.0),
                        })
        except Exception as e:
            logger.warning(f"SQLite vector fallback failed: {e}")

    if not all_results:
        return []

    # Stage 4: Deduplication & Scoring Sort
    seen_texts = set()
    unique_results = []
    for r in all_results:
        key = r['chunk_text'][:150].strip().lower()
        if key not in seen_texts:
            seen_texts.add(key)
            unique_results.append(r)

    unique_results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
    final_results = unique_results[:top_k]

    set_chroma_cache(brand_key, query, top_k, final_results)
    logger.info(f"Retrieval complete in {_time.time() - start:.3f}s: returned {len(final_results)} chunks")
    return final_results


# =============================================================
# Mode Instructions & Prompt Formatting
# =============================================================

MODE_INSTRUCTIONS = {
    'Creative': (
        'Provide a creative, engaging, and polished response based on the brand context.\n'
        'Use Markdown headings, bullet points, and clean structure.'
    ),
    'Strategy': (
        'Provide an executive-level strategic analysis based on the brand context.\n'
        'Focus on key insights, strategic recommendations, and actionable steps.'
    ),
    'Report': (
        'Produce a concise executive report based on the context.\n'
        'Use clean headings, bullet points, and quantitative highlights where available.'
    ),
    'Q&A': (
        'Answer the question directly, accurately, and clearly using the provided context.'
    ),
}


def _build_prompt(query: str, chunks: List[dict], brand_key: str, mode: str | None = None) -> str:
    is_all_brands = brand_key and str(brand_key).strip().upper() in ("ALL", "ALL BRANDS", "ALL_BRANDS", "ALLBRANDS")
    if is_all_brands:
        brand_name = "All Available Brands"
        custom_prompt = ""
        # For cross-brand queries, add context about multiple brands
        brands_in_results = set()
        for chunk in chunks:
            brands_in_results.add(chunk.get('brand_key', 'Unknown'))
        brands_str = ", ".join(sorted(brands_in_results))
        system_instructions = (
            f"You are Digitz AI, an intelligent brand intelligence assistant with access to multiple brands.\n"
            f"Brands in knowledge base: {brands_str}\n"
            f"Rules:\n"
            f"1. Provide a direct, high-quality, professional response using the available context from multiple brands.\n"
            f"2. Use clean, executive GitHub-flavored Markdown formatting.\n"
            f"3. Always clearly mention which brand information comes from (e.g., '[KIA]', '[ENGRO]').\n"
            f"4. When comparing brands, highlight the differences clearly.\n"
            f"5. Do NOT output empty or 'Not applicable' placeholder sections.\n"
            f"6. If the exact answer is not in the context, synthesize what relevant information is available in the brand documents.\n"
        )
    else:
        # ── FIX: brand_name and custom_prompt were previously undefined in
        # this branch, causing a NameError (crash) on every single-brand
        # query — e.g. "which type of Data in this engro" with ENGRO
        # selected always failed with "Sorry, I couldn't generate a
        # response." This is why cross-brand (ALL) queries worked but
        # single-brand queries did not.
        brand = get_brand(brand_key)
        brand_name = brand.get('name', brand_key) if brand else brand_key
        custom_prompt = (brand.get('custom_prompt') or '') if brand else ''
        system_instructions = (
            f"You are Digitz AI, an executive brand assistant for {brand_name}.\n"
            f"Rules:\n"
            f"1. Give the direct answer first.\n"
            f"2. Use clear Markdown headings, bullet points, and concise structure.\n"
            f"3. Be extremely fast and brief. Avoid fluff or repetitive disclaimers.\n"
            f"4. Use available context only. If data is unavailable, respond: 'No relevant data found.'\n"
        )

    if custom_prompt:
        system_instructions += f"\nBrand Voice Guidelines: {custom_prompt}\n"

    mode_instr = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS['Q&A'])

    context_blocks = []
    for chunk in chunks[:5]:
        # Add brand label to each context block for cross-brand clarity
        brand_label = f" [{chunk['brand_key'].upper()}]" if brand_key == "ALL" else ""
        context_blocks.append(f"--- [Document: {chunk['doc_title']}{brand_label}] ---\n{chunk['chunk_text']}")

    context_str = "\n\n".join(context_blocks) if context_blocks else "No specific document context found."

    return (
        f"{system_instructions}\n\n"
        f"Mode: {mode or 'Q&A'}\n"
        f"Mode Guidance: {mode_instr}\n\n"
        f"Retrieved Brand Knowledge Base Context:\n"
        f"{context_str}\n\n"
        f"User Request:\n"
        f"{query}\n\n"
        f"Response:"
    )


def search_documents(query: str, top_k: int = 5) -> List[dict]:
    results = search_all(query, top_k=top_k)
    return [
        {'title': item['title'], 'subtitle': item.get('subtitle', ''), 'brand': item.get('brand', 'unknown')}
        for item in results
    ]


def _is_small_talk(query: str) -> bool:
    normalized = query.strip().lower().rstrip('?.! ')
    small_talk_phrases = {
        'hi', 'hello', 'hey', 'how are you', 'how r u', 'whats up', "what's up",
        'good morning', 'good afternoon', 'good evening', 'thanks', 'thank you',
        'ok', 'okay', 'cool', 'nice', 'bye', 'goodbye', 'who are you',
    }
    if normalized in small_talk_phrases:
        return True
    if len(normalized.split()) <= 4 and any(p in normalized for p in ['how are you', 'whats up', "what's up"]):
        return True
    return False


# =============================================================
# Main Query Functions
# =============================================================

def run_query(query: str, brand: str | None = None, mode: str | None = None, session_id: str | None = None) -> dict:
    selected_brand = brand
    print(f"[RAG_CHAIN] run_query() brand='{selected_brand}' mode='{mode}'")
    sys.stdout.flush()

    if not selected_brand:
        raise ValueError('Brand key is required.')

    start_time = _time.time()

    if _is_small_talk(query):
        print(f"[RAG_CHAIN] Small talk, skipping retrieval")
        answer = ask_llm(
            f"The user said: \"{query}\"\n\n"
            "This is casual small talk. Reply naturally, briefly, and warmly. "
            "Do not mention documents or knowledge bases."
        )
        response_time = round(_time.time() - start_time, 3)
        record_query(query, selected_brand, mode, answer, 'done',
                     response_time=response_time, similarity_score=0.0,
                     retrieved_chunks=0, session_id=session_id)
        return {'query': query, 'brand': selected_brand, 'answer': answer,
                'source_docs': [], 'response_time': response_time, 'similarity': 0.0}

    # Check query cache first
    cached_result = get_query_cache(query, selected_brand, mode)
    if cached_result:
        print(f"[RAG_CHAIN] Query cache HIT")
        sys.stdout.flush()
        return cached_result

    # Retrieval
    retrieve_start = _time.time()
    chunks = retrieve_chunks(query, selected_brand, top_k=5)
    retrieve_elapsed = _time.time() - retrieve_start
    print(f"[RAG_CHAIN] Retrieved {len(chunks)} chunks in {retrieve_elapsed:.3f}s")
    sys.stdout.flush()

    # Source docs
    source_docs = []
    seen_docs = set()
    for chunk in chunks:
        doc_title = chunk['doc_title']
        if doc_title not in seen_docs:
            seen_docs.add(doc_title)
            snippet = chunk['chunk_text'][:140]
            snippet += '...' if len(chunk['chunk_text']) > 140 else ''
            source_docs.append({
                'title': doc_title,
                'brand': chunk['brand_key'],
                'snippet': snippet,
                'score': round(chunk.get('score', 0.0), 4),
            })

    if not chunks:
        answer = 'No relevant documents were found. Try uploading brand files or ask a more specific question.'
        response_time = round(_time.time() - start_time, 3)
        record_query(query, selected_brand, mode, answer, 'done',
                     response_time=response_time, similarity_score=0.0,
                     retrieved_chunks=0, session_id=session_id)
        return {'query': query, 'brand': selected_brand, 'answer': answer,
                'source_docs': [], 'response_time': response_time, 'similarity': 0.0}

    # Prompt
    prompt_start = _time.time()
    prompt = _build_prompt(query, chunks, selected_brand, mode)
    prompt_elapsed = _time.time() - prompt_start

    # LLM
    llm_start = _time.time()
    answer = ask_llm(prompt)
    llm_elapsed = _time.time() - llm_start

    # Metrics
    response_time = round(_time.time() - start_time, 3)
    top_similarity = max((chunk.get('score', 0.0) for chunk in chunks), default=0.0)

    print(f"[RAG_CHAIN_TIME] RETRIEVAL={retrieve_elapsed:.3f}s | PROMPT={prompt_elapsed:.3f}s | LLM={llm_elapsed:.3f}s | TOTAL={response_time}s")
    print(f"[RAG_CHAIN] === FINISHED ===")
    sys.stdout.flush()

    output_result = {
        'query': query, 'brand': selected_brand, 'answer': answer,
        'source_docs': source_docs, 'response_time': response_time,
        'similarity': top_similarity, 'confidence': round(top_similarity, 4),
    }

    # Cache output result
    set_query_cache(query, selected_brand, output_result, mode)

    record_query(query, selected_brand, mode, answer, 'done',
                 response_time=response_time, similarity_score=top_similarity,
                 retrieved_chunks=len(chunks), session_id=session_id)

    return output_result


# =============================================================
# Image RAG Pipeline
# =============================================================
# Flow: analyze image -> extract structured fields -> build a search query
# from those fields -> search the knowledge base -> answer ONLY from the
# retrieved chunks (never generic/hallucinated info).

def _extract_image_metadata(image_bytes: bytes, image_mime: str, user_query: str) -> dict:
    """Step 1: ask the vision model to identify what is actually in the
    image, before the knowledge base is touched at all."""
    extraction_prompt = (
        "You are an enterprise RAG assistant. Analyze the attached image only.\n"
        "Do not use outside/general knowledge yet — this is an extraction step, not an answer.\n\n"
        "Extract the following fields as compact JSON. Use \"\" or [] for any field "
        "that is not visible or not applicable:\n"
        "{\n"
        '  "brand": "",\n'
        '  "product": "",\n'
        '  "category": "",\n'
        '  "ocr_text": "",\n'
        '  "packaging_text": "",\n'
        '  "visible_labels": []\n'
        "}\n\n"
        f"User's question about the image: \"{user_query}\"\n\n"
        "Respond with ONLY the JSON object — no commentary, no markdown code fences."
    )
    raw = ask_llm_with_image(extraction_prompt, image_bytes, image_mime)

    metadata = {
        'brand': '', 'product': '', 'category': '',
        'ocr_text': '', 'packaging_text': '', 'visible_labels': [],
    }
    try:
        cleaned = (raw or '').strip()
        if cleaned.startswith('```'):
            cleaned = re.sub(r'^```(json)?\s*|\s*```$', '', cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
        parsed = json.loads(cleaned)
        for key in metadata:
            if key in parsed and parsed[key]:
                metadata[key] = parsed[key]
    except Exception as e:
        logger.warning(f"Image metadata extraction JSON parse failed: {e}")

    return metadata


def _build_search_query_from_image(metadata: dict, user_query: str) -> str:
    """Step 2: turn the extracted image fields into a knowledge-base search query."""
    labels = metadata.get('visible_labels') or []
    if isinstance(labels, list):
        labels_str = ' '.join(str(l) for l in labels)
    else:
        labels_str = str(labels)

    parts = [
        metadata.get('brand', ''),
        metadata.get('product', ''),
        metadata.get('category', ''),
        metadata.get('ocr_text', ''),
        metadata.get('packaging_text', ''),
        labels_str,
    ]
    extracted = ' '.join(p for p in parts if p).strip()

    if extracted:
        return f"{extracted} {user_query}".strip()
    return user_query


def run_query_with_image(
    query: str, image_bytes: bytes, image_mime: str,
    brand: str | None = None, mode: str | None = None, session_id: str | None = None,
) -> dict:
    """RAG-grounded query with image analysis and brand detection.

    Pipeline: analyze image -> extract Brand/Product/Category/OCR/Packaging/Labels
    -> build a search query from those fields -> search the knowledge base
    -> answer strictly from the retrieved chunks.
    """
    selected_brand = brand
    start_time = _time.time()

    # Try brand detection inside the query text if brand is generic or unknown
    if not selected_brand or selected_brand.lower() == 'unknown':
        from core.db import get_brands
        all_brands = get_brands()
        query_lower = query.lower()
        for b in all_brands:
            if b['name'].lower() in query_lower or b['key'].lower() in query_lower:
                selected_brand = b['key']
                print(f"[RAG_CHAIN_IMAGE] Auto-detected brand: '{selected_brand}' from query text")
                break

    if not selected_brand:
        selected_brand = 'kia'  # default fallback to kia or active

    print(f"[RAG_CHAIN_IMAGE] brand='{selected_brand}'")
    sys.stdout.flush()

    # Step 1: Analyze the image BEFORE touching the knowledge base.
    extraction_start = _time.time()
    image_metadata = _extract_image_metadata(image_bytes, image_mime, query)
    search_query = _build_search_query_from_image(image_metadata, query)
    extraction_elapsed = _time.time() - extraction_start
    print(f"[RAG_CHAIN_IMAGE] Extracted={image_metadata} | search_query='{search_query[:100]}' | {extraction_elapsed:.3f}s")
    sys.stdout.flush()

    # If image analysis found a brand, try to match it against known brands.
    if image_metadata.get('brand'):
        from core.db import get_brands
        all_brands = get_brands()
        extracted_brand_lower = image_metadata['brand'].lower().strip()
        for b in all_brands:
            b_name_lower = b['name'].lower()
            if extracted_brand_lower and (extracted_brand_lower in b_name_lower or b_name_lower in extracted_brand_lower):
                selected_brand = b['key']
                print(f"[RAG_CHAIN_IMAGE] Brand refined from image analysis: '{selected_brand}'")
                break

    # Step 2: Search the knowledge base using the image-derived query.
    retrieve_start = _time.time()
    chunks = retrieve_chunks(search_query, selected_brand, top_k=5)
    retrieve_elapsed = _time.time() - retrieve_start

    source_docs = []
    seen_docs = set()
    for chunk in chunks:
        doc_title = chunk['doc_title']
        if doc_title not in seen_docs:
            seen_docs.add(doc_title)
            snippet = chunk['chunk_text'][:140]
            snippet += '...' if len(chunk['chunk_text']) > 140 else ''
            source_docs.append({
                'title': doc_title, 'brand': chunk['brand_key'], 'snippet': snippet,
                'score': round(chunk.get('score', 0.0), 4),
            })

    # Step 3: If nothing relevant was found, say so plainly — never
    # fall back to generic/hallucinated info.
    if not chunks:
        answer = "I couldn't find this information in the knowledge base."
        response_time = round(_time.time() - start_time, 3)
        record_query(query, selected_brand, mode, answer, 'done',
                     response_time=response_time, similarity_score=0.0,
                     retrieved_chunks=0, session_id=session_id)
        return {
            'query': query, 'brand': selected_brand, 'answer': answer,
            'source_docs': [], 'response_time': response_time,
            'similarity': 0.0, 'confidence': 0.0,
            'image_analysis': image_metadata,
        }

    # Step 4: Build a strict, KB-grounded prompt.
    prompt_start = _time.time()
    context_blocks = [f"--- [Document: {c['doc_title']}] ---\n{c['chunk_text']}" for c in chunks[:5]]
    context_str = "\n\n".join(context_blocks)

    labels_str = ', '.join(image_metadata.get('visible_labels') or []) or '(none detected)'
    strict_prompt = (
        "You are an enterprise RAG assistant.\n\n"
        "## Image Analysis (already extracted, do not re-analyze)\n"
        f"Brand: {image_metadata.get('brand') or 'unknown'}\n"
        f"Product: {image_metadata.get('product') or 'unknown'}\n"
        f"Category: {image_metadata.get('category') or 'unknown'}\n"
        f"OCR Text: {image_metadata.get('ocr_text') or '(none detected)'}\n"
        f"Packaging Text: {image_metadata.get('packaging_text') or '(none detected)'}\n"
        f"Visible Labels: {labels_str}\n\n"
        "## Rules\n"
        "1. Only answer using the Retrieved Knowledge Base Context below.\n"
        "2. If the knowledge base does not contain the answer, respond with exactly: "
        "\"I couldn't find this information in the knowledge base.\"\n"
        "3. Never answer with generic company information unless the user specifically asks for company information.\n"
        "4. Do not hallucinate or guess facts that are not in the context.\n\n"
        f"Retrieved Knowledge Base Context:\n{context_str}\n\n"
        f"User Question: {query}\n\n"
        "Response:"
    )
    prompt_elapsed = _time.time() - prompt_start

    # Step 5: Final answer, grounded in the retrieved chunks (image still
    # attached so the model can double-check visual details if needed).
    llm_start = _time.time()
    answer = ask_llm_with_image(strict_prompt, image_bytes, image_mime)
    llm_elapsed = _time.time() - llm_start

    response_time = round(_time.time() - start_time, 3)
    top_similarity = max((c.get('score', 0.0) for c in chunks), default=0.0)

    print(f"[RAG_CHAIN_IMAGE_TIME] EXTRACT={extraction_elapsed:.3f}s | RETRIEVAL={retrieve_elapsed:.3f}s | "
          f"PROMPT={prompt_elapsed:.3f}s | LLM={llm_elapsed:.3f}s | TOTAL={response_time}s")
    sys.stdout.flush()

    record_query(query, selected_brand, mode, answer, 'done',
                 response_time=response_time, similarity_score=top_similarity,
                 retrieved_chunks=len(chunks), session_id=session_id)

    return {
        'query': query, 'brand': selected_brand, 'answer': answer,
        'source_docs': source_docs, 'response_time': response_time,
        'similarity': top_similarity, 'confidence': round(top_similarity, 4),
        'image_analysis': image_metadata,
    }