"""Answer questions about saved match results."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm
from flask_app.database import db
from flask_app.utils.prompts import build_agent_prompt


def answer_question(user_message, profile_id, jobs_list=None, history=None, selected_job_id=None):
    """Answer a question using the profile's match results."""
    role_info = db.get_llm_role("Chat Query Expert")
    system_prompt = build_agent_prompt(role_info, 'Chat Query Expert', 'أجب بناءً على بيانات المطابقة فقط.')

    match_results = db.get_match_results(profile_id)

    context_lines = []
    for mr in match_results:
        context_lines.append(
            f"- job_id={mr.get('job_id')}: {mr.get('job_title', '')} في {mr.get('job_company', '')}: "
            f"match_score={mr.get('match_score', 0)}, "
            f"recommendation={mr.get('recommendation', '')}, "
            f"strengths={mr.get('strengths', [])}, "
            f"missing_skills={mr.get('missing_skills', [])}"
        )

    context = "\n".join(context_lines) if context_lines else "لا توجد نتائج مطابقة بعد."
    selected = next((row for row in match_results if row['job_id'] == selected_job_id), None)
    if selected:
        context += (f"\nالوظيفة المختارة صراحة هي job_id={selected_job_id}: {selected['job_title']}. "
                    "أي إشارة إلى هذه الوظيفة تخصها. يمكن مقارنتها ببقية النتائج أعلاه."
                    f"\nتعليق التقييم: {selected.get('ai_comment', '')}")

    user_prompt = f"""نتائج المطابقة الحالية:
{context}

سؤال المستخدم: {user_message}"""

    print('[Chat Query Expert] Answering from saved matches')
    response = call_llm(system_prompt, user_prompt, temperature=0.3, history=history)
    return response or "عذراً، لم أتمكن من الإجابة على سؤالك. يرجى المحاولة مرة أخرى."
