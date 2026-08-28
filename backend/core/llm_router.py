"""
Unified LLM Router for Digitz AI.
Eliminates all duplicate code across 5 providers (Groq, OpenAI, Gemini, Claude, DeepSeek).
Provides a shared architecture for text completion, vision analysis, and embeddings.
"""
import os
import json
import base64
import hashlib
import time
from typing import Callable
from dataclasses import dataclass

import requests

from .db import get_setting
from .settings import settings
from .logging import get_logger
from .cache import get_embedding_cache, set_embedding_cache

logger = get_logger(__name__)

# ── Local embedding model (free, no API key) ─────────────────────────────────
_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _local_model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception as e:
            logger.warning(f"Could not load SentenceTransformer: {e}")
            _local_model = False
    return _local_model if _local_model is not False else None


# ── Provider configuration ────────────────────────────────────────────────────

@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""
    name: str
    api_key_setting: str           # key name in DB settings table
    env_key: str                   # env var name
    chat_url: str
    chat_model: str
    supports_vision: bool = False
    headers_fn: Callable = None    # returns dict of HTTP headers
    payload_fn: Callable = None    # (prompt, system, model) -> dict


def _openai_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _openai_payload(prompt: str, system: str, model: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system or "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
    }


def _gemini_payload(prompt: str, system: str, model: str) -> dict:
    combined = f"{system}\n\n{prompt}" if system else prompt
    return {
        "contents": [{"role": "user", "parts": [{"text": combined}]}],
        "generationConfig": {"temperature": 0.2}
    }


def _gemini_headers(api_key: str) -> dict:
    # Google now issues "AQ." auth keys for many accounts which are rejected
    # by the legacy "?key=" query-string method (403/404/401). These keys
    # (and the older AIzaSy ones) both work via the X-goog-api-key header,
    # so we always send it that way.
    return {"Content-Type": "application/json", "X-goog-api-key": api_key}


def _claude_headers(api_key: str) -> dict:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }


def _claude_payload(prompt: str, system: str, model: str) -> dict:
    return {
        "model": model,
        "max_tokens": 1024,
        "system": system or "You are a helpful assistant.",
        "messages": [{"role": "user", "content": prompt}],
    }


def _deepseek_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _deepseek_payload(prompt: str, system: str, model: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system or "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
    }


# All providers mapped by lowercase name
PROVIDERS: dict[str, ProviderConfig] = {
    'groq': ProviderConfig(
        name='Groq',
        api_key_setting='groq_key',
        env_key='GROQ_API_KEY',
        chat_url=os.environ.get('GROQ_API_URL', 'https://api.groq.com/openai/v1/chat/completions'),
        chat_model=os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b'),
        supports_vision=False,
        headers_fn=_openai_headers,
        payload_fn=_openai_payload,
    ),
    'openai': ProviderConfig(
        name='OpenAI',
        api_key_setting='openai_key',
        env_key='OPENAI_API_KEY',
        chat_url='https://api.openai.com/v1/chat/completions',
        chat_model='gpt-4o-mini',
        supports_vision=True,
        headers_fn=_openai_headers,
        payload_fn=_openai_payload,
    ),
    'gemini': ProviderConfig(
        name='Gemini',
        api_key_setting='gemini_key',
        env_key='GEMINI_API_KEY',
        chat_url='https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent',
        chat_model='gemini-3.5-flash',
        supports_vision=True,
        headers_fn=_gemini_headers,
        payload_fn=_gemini_payload,
    ),
    'claude': ProviderConfig(
        name='Claude',
        api_key_setting='anthropic_key',
        env_key='ANTHROPIC_API_KEY',
        chat_url='https://api.anthropic.com/v1/messages',
        chat_model='claude-sonnet-4-6',
        supports_vision=True,
        headers_fn=_claude_headers,
        payload_fn=_claude_payload,
    ),
    'deepseek': ProviderConfig(
        name='DeepSeek',
        api_key_setting='deepseek_key',
        env_key='DEEPSEEK_API_KEY',
        chat_url='https://api.deepseek.com/v1/chat/completions',
        chat_model='deepseek-chat',
        supports_vision=False,
        headers_fn=_deepseek_headers,
        payload_fn=_deepseek_payload,
    ),
}


# ── Provider name normalization ───────────────────────────────────────────────
# The frontend / DB "active_provider" value may not exactly match a PROVIDERS
# dict key (e.g. it might store "Gemini 2.5 Flash" instead of "gemini").
# This maps any such value onto the correct PROVIDERS key.

PROVIDER_ALIASES = {
    'gemini 2.5 flash': 'gemini',
    'gemini-2.5-flash': 'gemini',
    'gemini2.5flash': 'gemini',
    'gemini flash': 'gemini',
    'gemini 3.5 flash': 'gemini',
    'gemini-3.5-flash': 'gemini',
    'gemini3.5flash': 'gemini',
    'gemini (google)': 'gemini',
}


def _normalize_provider(raw: str) -> str:
    """Map whatever is stored as 'active_provider' to a PROVIDERS key."""
    key = (raw or 'groq').strip().lower()
    if key in PROVIDERS:
        return key
    if key in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[key]
    if 'gemini' in key:
        return 'gemini'
    if 'groq' in key:
        return 'groq'
    if 'claude' in key or 'anthropic' in key:
        return 'claude'
    if 'openai' in key or 'gpt' in key:
        return 'openai'
    if 'deepseek' in key:
        return 'deepseek'
    return key  # unrecognized — caller will show "Unknown provider"


def _resolve_api_key(provider_cfg: ProviderConfig) -> str:
    """Resolve API key from DB settings, then env var (.env), then settings object.
    This is the SINGLE source of truth for API keys — always use this function,
    never read provider keys directly from get_setting() elsewhere."""
    key = get_setting(provider_cfg.api_key_setting, '')
    if key:
        return key
    key = os.environ.get(provider_cfg.env_key, '')
    if key:
        return key
    # Fallback to settings object
    obj_key = provider_cfg.env_key.lower()
    return getattr(settings, obj_key, '') or ''


def _extract_text_response(provider: str, data: dict) -> str:
    """Extract text from various provider response formats."""
    if provider == 'gemini':
        try:
            return data['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError):
            return ''
    elif provider == 'claude':
        blocks = data.get('content', [])
        return ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text').strip()
    else:
        # OpenAI-compatible (Groq, OpenAI, DeepSeek)
        try:
            return data['choices'][0]['message']['content'].strip()
        except (KeyError, IndexError):
            return ''


def _call_chat_api(
    provider_cfg: ProviderConfig,
    prompt: str,
    system_instructions: str = '',
    timeout: int = 60,
) -> str:
    """Generic chat completion call for any provider."""
    api_key = _resolve_api_key(provider_cfg)
    if not api_key:
        return (
            f"I need a {provider_cfg.name} API key configured in Settings to answer that. "
            f"Please add your key and try again."
        )

    url = provider_cfg.chat_url
    candidate_models = []
    seen = set()
    fallback_pool = [provider_cfg.chat_model, 'openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'llama-3.3-70b-versatile', 'llama-3.1-8b-instant'] if provider_cfg.name.lower() == 'groq' else [provider_cfg.chat_model]
    for model_name in fallback_pool:
        if model_name and model_name not in seen:
            seen.add(model_name)
            candidate_models.append(model_name)

    # Build headers
    headers = provider_cfg.headers_fn(api_key) if provider_cfg.headers_fn else {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for model in candidate_models:
        payload = provider_cfg.payload_fn(prompt, system_instructions, model)
        try:
            logger.info(f"Calling {provider_cfg.name} API: model={model} url={url[:60]}...")
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if response.status_code == 200:
                data = response.json()
                text = _extract_text_response(provider_cfg.name.lower(), data)
                if text:
                    return text
                logger.error(f"{provider_cfg.name} returned empty response: {json.dumps(data)[:200]}")
                return "Sorry, I couldn't generate a response right now. Please try again."

            body_text = response.text[:200]
            last_error = f"{provider_cfg.name} API error ({response.status_code}): {body_text}"
            logger.warning(f"{provider_cfg.name} model '{model}' failed: {response.status_code} - {body_text}")

            if response.status_code in (400, 404) and any(kw in body_text.lower() for kw in ['model', 'does not exist', 'decommissioned', 'not exist']):
                continue
            return "Sorry, I couldn't generate a response right now. Please try again."
        except requests.exceptions.Timeout:
            logger.error(f"{provider_cfg.name} request timed out after {timeout}s")
            return f"{provider_cfg.name} request timed out. Please try again."
        except requests.exceptions.ConnectionError:
            logger.error(f"{provider_cfg.name} connection error")
            return f"Could not connect to {provider_cfg.name} API. Please check your network and try again."
        except Exception as e:
            logger.error(f"{provider_cfg.name} error: {e}")
            return f"Could not connect to {provider_cfg.name} API. Please check your network and try again."

    return "Sorry, I couldn't generate a response right now. Please try again."


# ── Local embedding ────────────────────────────────────────────────────────────

def get_local_semantic_embedding(text: str) -> list[float]:
    """Real semantic embedding using a local sentence-transformers model."""
    try:
        model = _get_local_model()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()
    except Exception:
        return get_fallback_embedding(text)


def get_fallback_embedding(text: str) -> list[float]:
    """Deterministic fallback embedding (not semantic, last resort)."""
    vector = []
    for idx in range(768):
        h = hashlib.sha256(f"{text}-{idx}".encode('utf-8')).hexdigest()
        val = int(h[:8], 16) / 4294967295.0
        vector.append(val)
    return vector


# ── Public API: ask_llm ──────────────────────────────────────────────────────

def ask_llm(prompt: str, system_instructions: str = "") -> str:
    """Route a text prompt to the active provider."""
    provider = _normalize_provider(get_setting('active_provider', 'groq'))
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return f"Unknown provider '{provider}'. Please check your Settings configuration."

    combined_prompt = f"{system_instructions}\n\n{prompt}" if system_instructions else prompt

    # For Gemini, the combined prompt is passed as-is (payload fn handles it)
    # For others, separate system/user messages
    if provider == 'gemini':
        return _call_chat_api(cfg, prompt, system_instructions)
    return _call_chat_api(cfg, combined_prompt)


# ── Vision API ────────────────────────────────────────────────────────────────

VISION_CAPABLE_PROVIDERS = {name for name, cfg in PROVIDERS.items() if cfg.supports_vision}


def _call_openai_vision(prompt: str, b64_image: str, image_mime: str, api_key: str) -> str:
    headers = _openai_headers(api_key)
    payload = {
        "model": "gpt-4.1",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{b64_image}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": 2000,
        "temperature": 0.3,
    }
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=payload, timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content']
        raise RuntimeError(f"OpenAI Vision API error ({resp.status_code})")
    except requests.exceptions.Timeout:
        raise RuntimeError("OpenAI Vision request timed out after 120s")
    except Exception as e:
        raise RuntimeError(f"OpenAI Vision error: {e}")


def _call_gemini_vision(prompt: str, b64_image: str, image_mime: str, api_key: str) -> str:
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": image_mime, "data": b64_image}},
                {"text": prompt},
            ],
        }],
        "generationConfig": {"temperature": 0.2},
    }
    try:
        resp = requests.post(url, headers=_gemini_headers(api_key), json=payload, timeout=120)
        if resp.status_code == 200:
            return resp.json()['candidates'][0]['content']['parts'][0]['text']
        raise RuntimeError(f"Gemini Vision API error ({resp.status_code})")
    except requests.exceptions.Timeout:
        raise RuntimeError("Gemini Vision request timed out after 120s")
    except Exception as e:
        raise RuntimeError(f"Gemini Vision error: {e}")


def _call_claude_vision(prompt: str, b64_image: str, image_mime: str, api_key: str) -> str:
    headers = _claude_headers(api_key)
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": b64_image}},
                {"type": "text", "text": prompt},
            ],
        }],
    }
    try:
        resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=120)
        if resp.status_code == 200:
            blocks = resp.json().get('content', [])
            return ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text').strip()
        raise RuntimeError(f"Claude Vision API error ({resp.status_code})")
    except requests.exceptions.Timeout:
        raise RuntimeError("Claude Vision request timed out after 120s")
    except Exception as e:
        raise RuntimeError(f"Claude Vision error: {e}")


def ask_llm_with_image(prompt: str, image_bytes: bytes, image_mime: str = "image/jpeg") -> str:
    """Send a prompt + image to the best available vision-capable LLM.

    Routing logic:
    1. If active provider supports vision (OpenAI/Gemini/Claude), use it directly.
    2. If active provider is text-only (Groq/DeepSeek), auto-detect a configured
       vision provider and route there with a note.
    3. If no vision-capable key is found, show a friendly message instead of an error.
    """
    active_provider = _normalize_provider(get_setting('active_provider', 'groq'))
    b64_image = base64.standard_b64encode(image_bytes).decode('utf-8')

    # NOTE: keys are resolved via _resolve_api_key() (DB -> .env -> settings obj)
    # instead of reading get_setting() directly, so GEMINI_API_KEY etc. from the
    # backend .env file are picked up even if nothing was typed into the UI.
    VISION_CALLERS = [
        ('openai', _resolve_api_key(PROVIDERS['openai']), 'GPT-4.1 (OpenAI)', _call_openai_vision),
        ('gemini', _resolve_api_key(PROVIDERS['gemini']), 'Gemini 2.5 Flash', _call_gemini_vision),
        ('claude', _resolve_api_key(PROVIDERS['claude']), 'Claude Sonnet 4.6', _call_claude_vision),
    ]

    def _run(caller_fn, key, display_name, auto_routed):
        try:
            result = caller_fn(prompt, b64_image, image_mime, key)
            if auto_routed:
                return (
                    f"> 🔀 **Auto-routed to {display_name}** for image analysis "
                    f"(your active provider `{active_provider}` is text-only).\n\n{result}"
                )
            return result
        except RuntimeError as e:
            return f"Sorry, image analysis failed: {e}"
        except Exception as e:
            logger.error(f"Vision error with {display_name}: {e}")
            return f"Sorry, image analysis encountered an error with {display_name}. Please try again."

    # Case 1: Active provider supports vision
    if active_provider in VISION_CAPABLE_PROVIDERS:
        for name, key, display_name, caller_fn in VISION_CALLERS:
            if name == active_provider:
                if not key:
                    return (
                        f"Your active provider is `{display_name}` which supports image analysis, "
                        f"but no API key is configured. Please add your key in **Settings -> AI Provider** "
                        f"or set it in the backend .env file."
                    )
                return _run(caller_fn, key, display_name, auto_routed=False)

    # Case 2: Auto-route to configured vision provider
    for name, key, display_name, caller_fn in VISION_CALLERS:
        if key:
            logger.info(f"Auto-routing image to {display_name} (active provider '{active_provider}' is text-only)")
            return _run(caller_fn, key, display_name, auto_routed=True)

    # Case 3: No vision-capable key found
    logger.warning(f"No vision-capable API key configured for provider '{active_provider}'")
    return (
        f"I would love to analyse that image for you! 🔍\n\n"
        f"However, your current AI provider (`{active_provider}`) is text-only and "
        f"cannot process images. To unlock image analysis, please:\n\n"
        f"1. Go to **Settings > AI Provider**\n"
        f"2. Add an API key for **OpenAI** (GPT-4.1), **Gemini** (2.5 Flash), or "
        f"**Anthropic/Claude** (Sonnet 4.6)\n"
        f"3. Switch the active provider to one that supports vision\n\n"
        f"Alternatively, try asking your question as text and I will do my best to help!\n\n"
        f"---\n\n"
        f"Here is a text-based response to your question:\n\n"
        f"{ask_llm(prompt)}"
    )


# ── Embeddings ───────────────────────────────────────────────────────────────

def generate_embedding(text: str) -> list[float]:
    """Generate embedding vector for text. Uses cache to avoid redundant computation."""
    cached = get_embedding_cache(text)
    if cached is not None:
        return cached

    provider = _normalize_provider(get_setting('active_provider', 'groq'))
    openai_key = _resolve_api_key(PROVIDERS['openai'])
    gemini_key = _resolve_api_key(PROVIDERS['gemini'])
    result = None

    # OpenAI Embeddings
    if provider == 'openai' and openai_key:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers=_openai_headers(openai_key),
                json={"model": "text-embedding-3-small", "input": text},
                timeout=15,
            )
            if resp.status_code == 200:
                result = resp.json()['data'][0]['embedding']
        except Exception as e:
            logger.warning(f"OpenAI embedding failed: {e}")

    # Gemini Embeddings
    if result is None and provider == 'gemini' and gemini_key:
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent"
            resp = requests.post(
                url,
                headers=_gemini_headers(gemini_key),
                json={"model": "models/text-embedding-004", "content": {"parts": [{"text": text}]}},
                timeout=15,
            )
            if resp.status_code == 200:
                result = resp.json()['embedding']['values']
        except Exception as e:
            logger.warning(f"Gemini embedding failed: {e}")

    # Fallback to local model
    if result is None:
        result = get_local_semantic_embedding(text)

    if result:
        set_embedding_cache(text, result)

    return result