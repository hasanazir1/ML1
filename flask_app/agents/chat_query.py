"""Answer questions about saved match results."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm
from flask_app.database import db


def answer_question(user_message, profile_id, jobs_list):
    """Answer a question using the profile's match results."""
    role_info = db.get_llm_role("Chat Query Expert")
    system_prompt = role_info["specific_instructions"] if role_info else "أجب بناءً على بيانات المطابقة فقط."

    match_results = db.get_match_results(profile_id)

    context_lines = []
    for mr in match_results:
        context_lines.append(
            f"- {mr.get("job_title", "")} في {mr.get("job_company", "")}: "
            f"match_score={mr.get("match_score", 0)}, "
            f"recommendation={mr.get("recommendation", "")}, "
            f"strengths={mr.get("strengths", [])}, "
            f"missing_skills={mr.get("missing_skills", [])}"
        )

    context = "\n".join(context_lines) if context_lines else "لا توجد نتائج مطابقة بعد."

    user_prompt = f"""نتائج المطابقة الحالية:
{context}

سؤال المستخدم: {user_message}"""

    response = call_llm(system_prompt, user_prompt, temperature=0.5)
    return response or "عذراً، لم أتمكن من الإجابة على سؤالك. يرجى المحاولة مرة أخرى."
