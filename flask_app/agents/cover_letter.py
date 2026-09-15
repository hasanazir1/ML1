"""Generate a cover letter for a selected job."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm
from flask_app.database import db


def generate_cover_letter(cv_data, job_data, profile_id):
    """Generate a cover letter from CV and job data."""
    role_info = db.get_llm_role("Cover Letter Generator Expert")
    system_prompt = role_info["specific_instructions"] if role_info else "اكتب Cover Letter احترافي."

    user_prompt = f"""بيانات المتقدم:
- الاسم: {cv_data.get("name", "")}
- المهارات: {", ".join(cv_data.get("skills", []))}
- الخبرات: {cv_data.get("experience", [])}
- المستوى: {cv_data.get("level", "")}
- ملخص: {cv_data.get("summary", "")}

الوظيفة المطلوبة:
- المسمى: {job_data.get("title", "")}
- الشركة: {job_data.get("company", "")}
- الوصف: {job_data.get("description", "")}

اكتب رسالة تقديم احترافية مخصصة لهذه الوظيفة."""

    response = call_llm(system_prompt, user_prompt, temperature=0.7)
    return response or "عذراً، لم أتمكن من كتابة رسالة التقديم. يرجى المحاولة مرة أخرى."
