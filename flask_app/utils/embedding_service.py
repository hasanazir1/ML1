"""Create embeddings through OpenRouter."""
import os
import math
from flask_app.utils.http_client import post_json

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = os.environ.get('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1').rstrip('/') + '/embeddings'
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "openai/text-embedding-3-small")


def valid_embedding(vector, dimensions=None):
    """A finite, nonzero numeric vector, optionally of an expected size."""
    return (isinstance(vector, list) and bool(vector)
            and (dimensions is None or len(vector) == dimensions)
            and all(type(x) in (int, float) and math.isfinite(x) for x in vector)
            and any(x != 0 for x in vector))


def generate_embedding(text):
    """Return an embedding list or None when the request fails."""
    if not OPENROUTER_API_KEY or not text:
        print("[embedding_service] Embedding unavailable: missing API key or empty text")
        return None
    try:
        data = post_json(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            payload={"model": EMBEDDING_MODEL, "input": text[:8000]},
            timeout=30
        )
        vector = data["data"][0]["embedding"]
        return vector if valid_embedding(vector) else None
    except (KeyError, IndexError, TypeError):
        print('[Embeddings] No usable vector received')
        return None


def cosine_similarity(vec_a, vec_b):
    """Return cosine similarity for two vectors."""
    if not valid_embedding(vec_a) or not valid_embedding(vec_b, len(vec_a)):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
