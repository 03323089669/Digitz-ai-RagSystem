"""
Query Router for Digitz AI.

Provides high-performance RAG query processing, vision multi-modal querying,
token-by-token SSE streaming, and complete chat session management.
"""

import json
import time
import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.db import (
    create_chat_session,
    delete_chat_session,
    get_active_company,
    get_brand_chunks,
    get_chat_messages,
    get_chat_session,
    get_chat_sessions,
    rename_chat_session,
    save_chat_message,
    set_chat_session_pin_archive,
)
from core.groq_llm import create_groq_client
from core.logging import get_logger
from core.rag_chain import run_query as run_rag_query, run_query_with_image, retrieve_chunks, _build_prompt, _is_small_talk
from core.settings import settings
from core.streaming import stream_llm_response
from routers.auth import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

# ── Configuration Constants ────────────────────────────────────────────────
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit


# ── Pydantic Request & Response Schemas ────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Text prompt or user query")
    brand: Optional[str] = Field(None, description="Brand key or active company ID")
    mode: Optional[str] = Field("Creative", description="AI response mode (Creative, Strategy, Report, Q&A)")
    session_id: Optional[str] = Field(None, description="Existing session ID (creates new if omitted)")


class SourceDocumentSchema(BaseModel):
    title: str
    brand: str
    snippet: str


class QueryResponse(BaseModel):
    query: str
    brand: str
    mode: str
    answer: str
    source_docs: List[Dict[str, Any]] = Field(default_factory=list)
    response_time: Optional[float] = None
    similarity: Optional[float] = None
    session_id: str


class SessionUpdatePayload(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_archived: Optional[bool] = None


class StatusResponse(BaseModel):
    status: str
    groq: Dict[str, Any]
    default_brand: str


# ── Endpoint Implementations ────────────────────────────────────────────────

@router.post("/", response_model=QueryResponse, summary="Execute RAG query")
def run_query(request: QueryRequest, current_user: dict = Depends(get_current_user)):
    """Execute a standard Retrieval-Augmented Generation (RAG) query.
    Retrieves brand knowledge context, constructs optimized prompts,
    executes LLM inference, and logs session messages.
    """
    start_time = time.time()
    query_text = request.query.strip()
    if not query_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query text cannot be empty."
        )

    selected_brand = request.brand or get_active_company()
    if not selected_brand:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A brand/company must be selected for AI queries."
        )

    logger.info(
        f"Processing query | user='{current_user.get('email')}' | "
        f"brand='{selected_brand}' | mode='{request.mode}' | session='{request.session_id}'"
    )

    # Session Resolution
    session = None
    if request.session_id:
        session = get_chat_session(request.session_id)

    if not session:
        session_title = query_text[:40] or "New Chat"
        session = create_chat_session(current_user["id"], selected_brand, session_title)
        logger.info(f"Created new session: id='{session['id']}' title='{session_title}'")

    # Persist user message
    save_chat_message(session["id"], "user", question=query_text)

    # Execute RAG Pipeline
    try:
        result = run_rag_query(
            query_text,
            brand=selected_brand,
            mode=request.mode,
            session_id=session["id"]
        )
    except Exception as e:
        logger.error(f"RAG chain execution failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while generating the AI response: {str(e)}"
        )

    answer = result.get("answer", "")
    sources = result.get("source_docs", [])
    resp_time = result.get("response_time", round(time.time() - start_time, 3))

    # Persist assistant message
    save_chat_message(
        session["id"],
        "assistant",
        answer=answer,
        retrieved_documents=json.dumps(sources),
        response_time=resp_time,
    )

    logger.info(f"Query executed successfully in {time.time() - start_time:.3f}s")

    return QueryResponse(
        query=query_text,
        brand=result.get("brand", selected_brand),
        mode=request.mode or "Creative",
        answer=answer,
        source_docs=sources,
        response_time=resp_time,
        similarity=result.get("similarity"),
        session_id=session["id"],
    )


@router.post("/with-image", summary="Execute Multimodal AI Vision query")
async def run_query_image(
    query: str = Form(...),
    brand: str = Form(...),
    mode: str = Form("Creative"),
    session_id: Optional[str] = Form(None),
    image: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Accept text query + uploaded image file and return AI vision analysis.

    Injects brand knowledge base context alongside multimodal visual analysis.
    """
    query_text = query.strip()
    if not query_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query text cannot be empty."
        )

    # Content-Type & Size validation
    image_mime = image.content_type or "image/jpeg"
    if image_mime not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image type: {image_mime}. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}"
        )

    image_bytes = await image.read()
    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds maximum size limit of {MAX_IMAGE_SIZE_BYTES // (1024*1024)}MB"
        )

    selected_brand = brand or get_active_company()
    if not selected_brand:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A brand/company must be selected for vision queries."
        )

    # Session Management
    session = None
    if session_id:
        session = get_chat_session(session_id)
    if not session:
        session = create_chat_session(current_user["id"], selected_brand, query_text[:40] or "Vision Query")

    save_chat_message(session["id"], "user", question=f"[Image attached] {query_text}")

    try:
        result = run_query_with_image(
            query=query_text,
            image_bytes=image_bytes,
            image_mime=image_mime,
            brand=selected_brand,
            mode=mode,
            session_id=session["id"],
        )
    except Exception as e:
        logger.error(f"Vision query execution failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process vision query: {str(e)}"
        )

    answer = result.get("answer", "")
    sources = result.get("source_docs", [])
    resp_time = result.get("response_time")

    save_chat_message(
        session["id"],
        "assistant",
        answer=answer,
        retrieved_documents=json.dumps(sources),
        response_time=resp_time,
    )

    return {
        "query": query_text,
        "brand": result.get("brand", selected_brand),
        "mode": mode,
        "answer": answer,
        "source_docs": sources,
        "response_time": resp_time,
        "similarity": result.get("similarity"),
        "session_id": session["id"],
        "has_image": True,
    }


@router.post("/stream", summary="Stream AI response via SSE")
async def stream_query(
    request: QueryRequest,
    current_user: dict = Depends(get_current_user),
):
    """Stream AI completion tokens in real-time via Server-Sent Events (SSE)."""
    query_text = request.query.strip()
    if not query_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query text cannot be empty."
        )

    selected_brand = request.brand or get_active_company()
    if not selected_brand:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A brand/company must be selected for streaming queries."
        )

    session = None
    if request.session_id:
        session = get_chat_session(request.session_id)
    if not session:
        session = create_chat_session(current_user["id"], selected_brand, query_text[:40] or "New Chat")

    save_chat_message(session["id"], "user", question=query_text)

    start_time = time.time()
    source_docs = []

    if not _is_small_talk(query_text):
        chunks = retrieve_chunks(query_text, selected_brand, top_k=4)
        seen_docs = set()
        for chunk in chunks:
            doc_title = chunk.get("doc_title", "Document")
            if doc_title not in seen_docs:
                seen_docs.add(doc_title)
                source_docs.append({
                    "title": doc_title,
                    "brand": chunk.get("brand_key", selected_brand),
                    "snippet": chunk.get("chunk_text", "")[:140] + ("..." if len(chunk.get("chunk_text", "")) > 140 else ""),
                })
        prompt_text = _build_prompt(query_text, chunks, selected_brand, request.mode)
    else:
        prompt_text = (
            f'The user said: "{query_text}"\n\n'
            "This is casual small talk. Reply naturally, briefly, and warmly "
            "as a helpful brand assistant. Keep it to 1-2 sentences."
        )

    async def event_generator():
        accumulated = ""
        # Yield metadata: sources
        yield f"data: {json.dumps({'type': 'sources', 'sources': source_docs})}\n\n"

        try:
            async for chunk in stream_llm_response(prompt_text):
                try:
                    data = json.loads(chunk)
                    if "error" in data:
                        yield f"data: {json.dumps({'type': 'error', 'error': data['error']})}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'content': accumulated})}\n\n"
                        return

                    if data.get("done"):
                        if not accumulated.strip():
                            logger.error("Streaming provider completed without response content")
                            yield f"data: {json.dumps({'type': 'error', 'error': 'The AI provider returned an empty response.'})}\n\n"
                            return
                        elapsed = round(time.time() - start_time, 3)
                        save_chat_message(
                            session["id"],
                            "assistant",
                            answer=accumulated,
                            retrieved_documents=json.dumps(source_docs),
                            response_time=elapsed,
                        )
                        yield f"data: {json.dumps({'type': 'done', 'content': accumulated, 'response_time': elapsed, 'session_id': session['id']})}\n\n"
                        return

                    token = data.get("token", "")
                    if token:
                        accumulated += token
                        yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            logger.error(f"Streaming error encountered: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status", response_model=StatusResponse, summary="Get Query Service & LLM Provider Status")
def status():
    """Retrieve system health, LLM provider settings, and default brand configurations."""
    client_info = create_groq_client()
    return StatusResponse(
        status="running",
        groq=client_info,
        default_brand=settings.default_brand,
    )


@router.get("/sessions", summary="List Chat Sessions")
def list_sessions(brand: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """List all active chat sessions for the authenticated user."""
    sessions = get_chat_sessions(current_user["id"], brand_key=brand)
    return {"sessions": sessions}


@router.get("/sessions/{session_id}/messages", summary="Get Chat Session Messages")
def list_session_messages(session_id: str, current_user: dict = Depends(get_current_user)):
    """Retrieve complete message history for a specific chat session."""
    messages = get_chat_messages(session_id)
    return {"messages": messages}


@router.put("/sessions/{session_id}", summary="Update Chat Session Attributes")
def update_session(
    session_id: str,
    payload: SessionUpdatePayload,
    current_user: dict = Depends(get_current_user)
):
    """Update title, pinned status, or archived status of a chat session."""
    updated = None
    if payload.title:
        updated = rename_chat_session(session_id, payload.title)
    if payload.is_pinned is not None or payload.is_archived is not None:
        updated = set_chat_session_pin_archive(
            session_id,
            is_pinned=payload.is_pinned,
            is_archived=payload.is_archived,
        )
    if updated is None:
        updated = get_chat_session(session_id)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found."
        )

    return {"session": updated}


@router.delete("/sessions/{session_id}", summary="Delete Chat Session")
def remove_session(session_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a chat session and all associated message history."""
    delete_chat_session(session_id)
    return {"status": "deleted", "session_id": session_id}
