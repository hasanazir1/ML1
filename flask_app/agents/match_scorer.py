"""Score how well a CV matches a job."""
import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm, extract_json_from_response
from flask_app.database import db
from flask_app.utils.prompts import build_agent_prompt


def get_match_scoring_system_prompt():
    """Load the match scoring prompt from the database."""
    role = db.get_llm_role("Match Scoring Expert")
    fallback = 'Return JSON: match_score (0-100), strengths and missing_skills (string lists), recommendation (Highly Recommended|Partial Match|Not Recommended), ai_comment (string).'
    return build_agent_prompt(role, 'Match Scoring Expert', fallback)


def score_match(cv_data, job_data):
    """Return a normalized match result or None."""
    print(f"[Match Scoring Expert] Evaluating job_id={job_data.get('job_id')}")
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
        print(f"[match_scorer] Failed to score match for job {job_data.get('title')}")
        return None

    if not isinstance(data, dict):
        print(f"[match_scorer] Invalid shape: expected a JSON object for job "
              f"{job_data.get('title')}, got {type(data).__name__}")
        return None

    required_keys = ("match_score", "strengths", "missing_skills", "recommendation", "ai_comment")
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        print(f"[match_scorer] Invalid shape: missing keys {missing_keys} for job {job_data.get('title')}")
        return None

    for key in ("strengths", "missing_skills"):
        value = data[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            print(f"[match_scorer] Invalid shape: {key} must be a list of strings "
                  f"for job {job_data.get('title')}")
            return None

    if not isinstance(data["ai_comment"], str):
        print(f"[match_scorer] Invalid shape: ai_comment must be a string "
              f"for job {job_data.get('title')}")
        return None

    try:
        value = data['match_score']
        if isinstance(value, bool):
            return None
        score = float(value)
        if not math.isfinite(score) or not 0 <= score <= 100:
            return None
        data['match_score'] = round(score)
    except (ValueError, TypeError):
        print(f"[match_scorer] Invalid shape: match_score is not numeric "
              f"for job {job_data.get('title')}")
        return None

    valid_recs = ["Highly Recommended", "Partial Match", "Not Recommended"]
    if data["recommendation"] not in valid_recs:
        print(f"[match_scorer] Invalid shape: recommendation {data['recommendation']!r} "
              f"is not one of {valid_recs} for job {job_data.get('title')}")
        return None

    print(f"[Match Scoring Expert] job_id={job_data.get('job_id')} score={data['match_score']}")
    return data
