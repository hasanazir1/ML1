"""Extract structured data from CV text."""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm, extract_json_from_response
from flask_app.database import db


def get_cv_analysis_system_prompt():
    """Load the CV analysis prompt from the database."""
    role = db.get_llm_role("CV Analysis Expert")
    if role:
        return role["specific_instructions"]
    return """اقرأ نص الـ CV الخام وأنتج JSON فقط بالشكل: {"name": ..., "email": ..., "skills": [...], "experience": [{"title":..., "company":..., "years":...}], "education": [{"degree":..., "field":..., "institution":...}], "field": ..., "level": "Junior|Mid|Senior", "summary": "..."}. إذا لم تجد معلومة استخدم null أو مصفوفة فارغة."""


def analyze_cv(raw_text):
    """Return structured CV data, or empty defaults when parsing fails."""
    system_prompt = get_cv_analysis_system_prompt()
    user_message = f"إليك نص السيرة الذاتية:\n\n{raw_text[:8000]}"

    response = call_llm(system_prompt, user_message, temperature=0.2)
    data = extract_json_from_response(response)

    if not data:
        print("[cv_analyzer] Failed to extract JSON from LLM response")
        return {
            "name": None, "email": None, "skills": [], "experience": [],
            "education": [], "field": None, "level": None, "summary": None
        }

    for key in ("name", "email", "field", "level", "summary"):
        data.setdefault(key, None)
    for key in ("skills", "experience", "education"):
        if not isinstance(data.get(key), list):
            data[key] = []

    return data
