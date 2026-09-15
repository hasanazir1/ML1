"""Score how well a CV matches a job."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm, extract_json_from_response
from flask_app.database import db


def get_match_scoring_system_prompt():
    """Load the match scoring prompt from the database."""
    role = db.get_llm_role("Match Scoring Expert")
    if role:
        return role["specific_instructions"]
    return """قارن بين وصف الوظيفة وبيانات الـ CV، وأنتج JSON فقط: {"match_score": 0-100, "strengths": [...], "missing_skills": [...], "recommendation": "Highly Recommended|Partial Match|Not Recommended", "ai_comment": "..."}"""


def score_match(cv_data, job_data):
    """Return a normalized match result or None."""
    system_prompt = get_match_scoring_system_prompt()

    user_message = f"""بيانات السيرة الذاتية:
- الاسم: {cv_data.get("name", "غير محدد")}
- المهارات: {", ".join(cv_data.get("skills", []))}
- الخبرات: {cv_data.get("experience", [])}
- المستوى: {cv_data.get("level", "غير محدد")}
- المجال: {cv_data.get("field", "غير محدد")}
- ملخص: {cv_data.get("summary", "")}

بيانات الوظيفة:
- المسمى: {job_data.get("title", "")}
- الشركة: {job_data.get("company", "")}
- الوصف: {job_data.get("description", "")}

قارن وبين درجة المطابقة."""

    response = call_llm(system_prompt, user_message, temperature=0.3)
    data = extract_json_from_response(response)

    if not data:
        print(f"[match_scorer] Failed to score match for job {job_data.get("title")}")
        return None

    data.setdefault("match_score", 0)
    data.setdefault("strengths", [])
    data.setdefault("missing_skills", [])
    data.setdefault("recommendation", "Partial Match")
    data.setdefault("ai_comment", "")

    try:
        data["match_score"] = max(0, min(100, int(data["match_score"])))
    except (ValueError, TypeError):
        data["match_score"] = 0

    valid_recs = ["Highly Recommended", "Partial Match", "Not Recommended"]
    if data["recommendation"] not in valid_recs:
        data["recommendation"] = "Partial Match"

    return data
