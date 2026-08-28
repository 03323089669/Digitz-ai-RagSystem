import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.db import (
    get_chat_session,
    get_chat_sessions,
    create_chat_session,
    rename_chat_session,
    set_chat_session_pin_archive,
    delete_chat_session,
    get_chat_messages,
    save_chat_message,
    get_brand,
)
from core.rag_chain import run_query
from routers.auth import get_current_user





router = APIRouter(prefix='/api/conversations', tags=['recent-chats'])


def _trim_title(text: str, max_chars: int = 60) -> str:
    cleaned = ' '.join((text or '').strip().split())
    if not cleaned:
        return 'New Chat'
    # Keep it readable: cut at max chars, avoid ending mid-word.
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars].rsplit(' ', 1)[0]
    return cut or cleaned[:max_chars]


def _group_key(created_at_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at_iso.replace('Z', '+00:00'))
    except Exception:
        return 'Older'

    now = datetime.utcnow().replace(tzinfo=None)
    dt_naive = dt.replace(tzinfo=None)

    today_start = datetime(now.year, now.month, now.day)
    yesterday_start = today_start - timedelta(days=1)
    last7_start = today_start - timedelta(days=7)
    last30_start = today_start - timedelta(days=30)

    if dt_naive >= today_start:
        return 'Today'
    if dt_naive >= yesterday_start and dt_naive < today_start:
        return 'Yesterday'
    if dt_naive >= last7_start and dt_naive < yesterday_start:
        return 'Previous 7 Days'
    if dt_naive >= last30_start and dt_naive < last7_start:
        return 'Previous 30 Days'
    return 'Older'


class ConversationCreatePayload(BaseModel):
    brand_key: str


class ConversationListQuery(BaseModel):
    search: Optional[str] = None
    page: int = 1
    page_size: int = 50
    brand_key: Optional[str] = None


class ConversationUpdatePayload(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_archived: Optional[bool] = None


class MessageSendPayload(BaseModel):
    text: str
    mode: str | None = 'Creative'


@router.post('')
def create_conversation(payload: ConversationCreatePayload, current_user: dict = Depends(get_current_user)):
    brand = get_brand(payload.brand_key)
    if not brand:
        raise HTTPException(status_code=404, detail='Brand not found')

    conv = create_chat_session(
        user_id=current_user['id'],
        brand_key=payload.brand_key,
        title='New Chat',
    )
    return {'conversation': conv}


@router.get('')
def list_conversations(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    brand_key: Optional[str] = Query(None),
    include_archived: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    # Fetch all sessions for the user (optionally by brand) and then apply
    # search + grouping in Python since the existing DB helpers are simple.
    sessions = get_chat_sessions(current_user['id'], brand_key)

    if not include_archived:
        sessions = [s for s in sessions if not bool(s.get('is_archived'))]

    if search:
        q = search.strip().lower()
        sessions = [s for s in sessions if (s.get('title') or '').lower().find(q) >= 0]

    # Sort newest first (get_chat_sessions already orders by created_at desc)
    sessions = sessions

    start = (page - 1) * page_size
    end = start + page_size
    page_sessions = sessions[start:end]

    grouped = {}
    for s in page_sessions:
        key = _group_key(s.get('created_at') or '')
        grouped.setdefault(key, [])
        grouped[key].append(s)

    return {
        'conversations': grouped,
        'page': page,
        'page_size': page_size,
        'total': len(sessions),
    }


@router.get('/{conv_id}')
def get_conversation(conv_id: str, current_user: dict = Depends(get_current_user)):
    conv = get_chat_session(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail='Conversation not found')
    if conv.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail='Not authorized')
    return {'conversation': conv}


@router.put('/{conv_id}')
def update_conversation(conv_id: str, payload: ConversationUpdatePayload, current_user: dict = Depends(get_current_user)):
    conv = get_chat_session(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail='Conversation not found')
    if conv.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail='Not authorized')

    updates = {}
    if payload.title is not None:
        conv = rename_chat_session(conv_id, payload.title)
        updates['title'] = conv.get('title')

    if payload.is_pinned is not None or payload.is_archived is not None:
        conv = set_chat_session_pin_archive(conv_id, is_pinned=payload.is_pinned, is_archived=payload.is_archived)
        updates['is_pinned'] = conv.get('is_pinned')
        updates['is_archived'] = conv.get('is_archived')

    return {'conversation': conv, 'updated': updates}


@router.delete('/{conv_id}')
def delete_conversation(conv_id: str, current_user: dict = Depends(get_current_user)):
    conv = get_chat_session(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail='Conversation not found')
    if conv.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail='Not authorized')

    delete_chat_session(conv_id)
    return {'conversation_id': conv_id, 'status': 'deleted'}


@router.get('/{conv_id}/messages')
def list_messages(conv_id: str, current_user: dict = Depends(get_current_user)):
    conv = get_chat_session(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail='Conversation not found')
    if conv.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail='Not authorized')

    return {'messages': get_chat_messages(conv_id)}


@router.post('/{conv_id}/messages')
def send_message(conv_id: str, payload: MessageSendPayload, current_user: dict = Depends(get_current_user)):
    conv = get_chat_session(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail='Conversation not found')
    if conv.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail='Not authorized')

    brand_key = conv.get('brand_key')
    if not brand_key:
        raise HTTPException(status_code=400, detail='Conversation brand is missing')

    text = (payload.text or '').strip()
    if not text:
        raise HTTPException(status_code=400, detail='Message text cannot be empty')

    # Save user message
    user_msg = save_chat_message(
        session_id=conv_id,
        role='user',
        question=text,
        sources='[]',
        attachments='[]',
    )

    # Auto-title: if the conversation still has default title and this is the
    # first user message, rename it.
    if (conv.get('title') == 'New Chat' or not (conv.get('title') or '').strip()):
        history = get_chat_messages(conv_id)
        user_msgs = [m for m in history if m.get('role') == 'user']
        if len(user_msgs) == 1:
            conv = rename_chat_session(conv_id, _trim_title(text))

    # Run RAG query
    result = run_query(text, brand=brand_key, mode=payload.mode, session_id=conv_id)

    # Sources/attachments: currently pipeline returns source_docs.
    sources = json.dumps(result.get('source_docs', []))
    attachments = '[]'

    # Save assistant message
    ai_msg = save_chat_message(
        session_id=conv_id,
        role='assistant',
        answer=result.get('answer'),
        sources=sources,
        attachments=attachments,
        response_time=result.get('response_time'),
        retrieved_documents=json.dumps(result.get('source_docs', [])),
    )

    # Normalize for frontend expectations
    return {
        'conversation': conv,
        'user_message': user_msg,
        'ai_message': ai_msg,
    }

