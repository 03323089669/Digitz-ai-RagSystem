"""
Real streaming support for Digitz AI using Server-Sent Events (SSE).
Provides token-by-token streaming from the active LLM provider.
"""
import json
import asyncio
from typing import AsyncGenerator

import requests

from .db import get_setting
from .llm_router import PROVIDERS, _resolve_api_key, _openai_headers
from .logging import get_logger

logger = get_logger(__name__)


async def stream_llm_response(
    prompt: str,
    system_instructions: str = "",
    chunk_size: int = 5,
) -> AsyncGenerator[str, None]:
    """Stream tokens from the active provider using SSE in a single-pass request.

    Yields JSON-encoded token events: {"token": "Hello", "done": false}
    Final event: {"token": "", "done": true}
    On error: {"error": "message"}
    """
    provider = get_setting('active_provider', 'groq').lower()
    cfg = PROVIDERS.get(provider)
    if not cfg:
        yield json.dumps({"error": f"Unknown provider '{provider}'"})
        return

    api_key = _resolve_api_key(cfg)
    if not api_key:
        yield json.dumps({"error": f"No API key configured for {cfg.name}"})
        return

    url = cfg.chat_url
    headers = cfg.headers_fn(api_key) if cfg.headers_fn else _openai_headers(api_key)

    model_candidates = []
    seen = set()
    fallback_pool = [cfg.chat_model, 'openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'llama-3.3-70b-versatile', 'llama-3.1-8b-instant'] if provider == 'groq' else [cfg.chat_model]
    for model_name in fallback_pool:
        if model_name and model_name not in seen:
            seen.add(model_name)
            model_candidates.append(model_name)

    connected_resp = None
    loop = asyncio.get_event_loop()

    for model in model_candidates:
        if provider == 'gemini':
            combined = f"{system_instructions}\n\n{prompt}" if system_instructions else prompt
            payload = {
                "contents": [{"role": "user", "parts": [{"text": combined}]}],
                "generationConfig": {"temperature": 0.2},
            }
            stream_url = f"{url}?alt=sse&key={api_key}"
        elif provider == 'claude':
            payload = {
                "model": model,
                "max_tokens": 1024,
                "stream": True,
                "system": system_instructions or "You are a helpful assistant.",
                "messages": [{"role": "user", "content": prompt}],
            }
            stream_url = url
        else:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_instructions or "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "stream": True,
            }
            stream_url = url

        try:
            resp = await loop.run_in_executor(
                None,
                lambda: requests.post(stream_url, headers=headers, json=payload, stream=True, timeout=120),
            )

            if resp.status_code == 200:
                connected_resp = resp
                break

            body_text = resp.text[:200]
            logger.warning(f"Streaming model '{model}' failed for {cfg.name}: {resp.status_code} - {body_text}")
            if resp.status_code in (400, 404) and any(kw in body_text.lower() for kw in ['model', 'does not exist', 'decommissioned', 'not exist']):
                continue

            yield json.dumps({"error": "Sorry, I couldn't generate a response right now. Please try again."})
            return
        except requests.exceptions.Timeout:
            yield json.dumps({"error": "Request timed out. Please try again."})
            return
        except Exception as e:
            logger.error(f"Streaming connection error: {e}")
            yield json.dumps({"error": "Could not connect to AI service. Please check your network and try again."})
            return

    if not connected_resp:
        yield json.dumps({"error": "Sorry, I couldn't generate a response right now. Please try again."})
        return

    # Direct single-pass stream processing
    # Force UTF-8 decoding — without this, `requests` falls back to
    # ISO-8859-1 for `application/json` responses (no charset in the
    # Content-Type header), which mangles multi-byte characters like
    # curly quotes/apostrophes (') into "â€™".
    connected_resp.encoding = 'utf-8'
    try:
        buffer = ""
        for chunk in connected_resp.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk:
                continue

            if provider == 'gemini':
                for line in chunk.split('\n'):
                    line = line.strip()
                    if line.startswith('data: '):
                        try:
                            data = json.loads(line[6:])
                            candidates = data.get('candidates', [])
                            if candidates:
                                content = candidates[0].get('content', {})
                                parts = content.get('parts', [])
                                for part in parts:
                                    token = part.get('text', '')
                                    if token:
                                        yield json.dumps({"token": token, "done": False})
                        except json.JSONDecodeError:
                            pass
            elif provider == 'claude':
                buffer += chunk
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line.startswith('data: '):
                        try:
                            data = json.loads(line[6:])
                            if data.get('type') == 'content_block_delta':
                                delta = data.get('delta', {})
                                token = delta.get('text', '')
                                if token:
                                    yield json.dumps({"token": token, "done": False})
                        except json.JSONDecodeError:
                            pass
            else:
                # OpenAI-compatible (Groq, OpenAI, DeepSeek)
                buffer += chunk
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line == 'data: [DONE]':
                        break
                    if line.startswith('data: '):
                        try:
                            data = json.loads(line[6:])
                            choices = data.get('choices', [])
                            if choices:
                                delta = choices[0].get('delta', {})
                                token = delta.get('content', '')
                                if token:
                                    yield json.dumps({"token": token, "done": False})
                        except json.JSONDecodeError:
                            pass

        yield json.dumps({"token": "", "done": True})

    except requests.exceptions.Timeout:
        yield json.dumps({"error": "Request timed out during streaming. Please try again."})
    except Exception as e:
        logger.error(f"Streaming token loop error: {e}")
        yield json.dumps({"error": "Streaming encountered an error. Please try again."})