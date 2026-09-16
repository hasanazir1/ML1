"""Call OpenRouter chat completions."""
import os
import json
import re
from flask_app.utils.http_client import post_json

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_CHAT_URL = os.environ.get('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1').rstrip('/') + '/chat/completions'
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")


def call_llm(system_prompt, user_message, temperature=0.3, history=None):
    """Return the model response or None on failure."""
    if not OPENROUTER_API_KEY:
        return None
    messages = [{"role": "system", "content": system_prompt}]
    for item in (history or [])[-6:]:
        role = {'user': 'user', 'agent': 'assistant'}.get(item.get('sender'))
        if role and isinstance(item.get('message'), str):
            content = item['message'][:4000]
            if item.get('job_id'):
                content += f"\n[Selected job_id={item['job_id']}]"
            messages.append({'role': role, 'content': content})
    messages.append({'role': 'user', 'content': user_message})
    try:
        data = post_json(
            OPENROUTER_CHAT_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            payload={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 1500
            },
            timeout=60
        )
        content = data["choices"][0]["message"]["content"]
        return content.strip() if isinstance(content, str) and content.strip() else None
    except (KeyError, IndexError, TypeError):
        print('[LLM] No usable response received')
        return None


def extract_json_from_response(text):
    """Extract a JSON object from model output."""
    if not isinstance(text, str) or not text.strip():
        return None
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None
