import json
import requests

from .settings import settings


def create_groq_client():
    if not settings.groq_api_key:
        return {
            'provider': 'groq',
            'status': 'missing_api_key',
            'note': 'Set GROQ_API_KEY in backend/.env or environment variables.',
        }

    return {
        'provider': 'groq',
        'status': 'configured',
        'model': settings.groq_model,
        'endpoint': settings.groq_api_url,
    }


def ask_groq(prompt: str) -> str:
    if not settings.groq_api_key:
        return (
            'Groq API key is not configured. Install your key in backend/.env as GROQ_API_KEY and restart the server.'
        )

    fallback_models = []
    for m in [settings.groq_model, 'openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'llama-3.3-70b-versatile', 'llama-3.1-8b-instant']:
        if m and m not in fallback_models:
            fallback_models.append(m)

    last_error = None
    response = None

    for model_name in fallback_models:
        payload = {
            'model': model_name,
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.3,
        }
        headers = {
            'Authorization': f'Bearer {settings.groq_api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        url = settings.groq_api_url.rstrip('/') + '/chat/completions'
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                break

            last_error = f'Groq API request failed ({response.status_code}): {response.text[:200]}'
            if response.status_code in (400, 404) and any(kw in response.text.lower() for kw in ['model', 'does not exist', 'decommissioned', 'not exist']):
                continue
            return "Sorry, I couldn't generate a response right now. Please try again."
        except Exception as e:
            last_error = f'Groq API connection error: {e}'
            continue

    if not response or response.status_code != 200:
        return "Sorry, I couldn't generate a response right now. Please try again."

    data = response.json()
    try:
        content = data['choices'][0]['message']['content']
        if content:
            return content.strip()
    except (KeyError, IndexError):
        pass

    return "Sorry, I couldn't generate a response right now. Please try again."

