"""Extract structured data from CV text."""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm, extract_json_from_response
from flask_app.database import db
from flask_app.utils.prompts import build_agent_prompt


def get_cv_analysis_system_prompt():
    """Load the CV analysis prompt from the database."""
    role = db.get_llm_role("CV Analysis Expert")
    fallback = 'Return JSON with name, email, field, level, summary (strings or null), skills (strings), experience and education (lists of objects).'
    return build_agent_prompt(role, 'CV Analysis Expert', fallback)


def analyze_cv(raw_text):
    """Return structured CV data, or None when analysis or the shape fails."""
    print('[CV Analysis Expert] Started')
    system_prompt = get_cv_analysis_system_prompt()
    user_message = f"إليك نص السيرة الذاتية:\n\n{raw_text[:8000]}"

    response = call_llm(system_prompt, user_message, temperature=0.2)
    data = extract_json_from_response(response)

    if not data:
        print("[cv_analyzer] Failed to extract JSON from LLM response")
        return None

    if not isinstance(data, dict):
        print(f"[cv_analyzer] Invalid shape: expected a JSON object, got {type(data).__name__}")
        return None

    for key in ("name", "email", "field", "level", "summary"):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            print(f"[cv_analyzer] Invalid shape: {key!r} must be a string or null, got {type(value).__name__}")
            return None

    for key in ("skills", "experience", "education"):
        value = data.get(key)
        if not isinstance(value, list):
            print(f"[cv_analyzer] Invalid shape: {key!r} must be a list, got {type(value).__name__}")
            return None

    if not all(isinstance(skill, str) for skill in data["skills"]):
        print("[cv_analyzer] Invalid shape: skills must be a list of strings")
        return None

    for key in ("experience", "education"):
        if not all(isinstance(entry, dict) for entry in data[key]):
            print(f"[cv_analyzer] Invalid shape: {key} must be a list of objects")
            return None

    for key in ("name", "email", "field", "level", "summary"):
        data.setdefault(key, None)
    for key in ("skills", "experience", "education"):
        data.setdefault(key, [])

    if data.get('level') not in (None, 'Junior', 'Mid', 'Senior'):
        return None
    if not any(data.get(key) for key in ('skills', 'experience', 'education', 'summary', 'field')):
        return None
    print('[CV Analysis Expert] Completed')
    return data
