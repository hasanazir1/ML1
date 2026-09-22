"""Suggest CV improvements without changing the stored profile."""
import json

from flask_app.database import db
from flask_app.utils.llm_service import call_llm
from flask_app.utils.prompts import build_agent_prompt


def suggest_cv_improvements(profile, user_message, match=None, history=None):
    """Use saved CV facts and, when chosen, one owned job match."""
    role = db.get_llm_role('CV Improvement Expert')
    system_prompt = build_agent_prompt(
        role, 'CV Improvement Expert',
        'اقترح تحسينات محددة للسيرة دون اختراع مؤهلات أو تعديل البيانات.'
    )
    cv_facts = {
        'field': profile.get('field'),
        'level': profile.get('level'),
        'summary': profile.get('summary'),
        'skills': profile.get('skills') or [],
        'experience': profile.get('experience') or [],
        'education': profile.get('education') or [],
    }
    job_context = None
    if match:
        job_context = {
            'job_id': match['job_id'],
            'title': match['job_title'],
            'company': match['job_company'],
            'description': match['job_description'],
            'strengths': match.get('strengths') or [],
            'missing_skills': match.get('missing_skills') or [],
            'ai_comment': match.get('ai_comment'),
        }
    user_prompt = (
        'بيانات السيرة المحلّلة:\n' + json.dumps(cv_facts, ensure_ascii=False) +
        '\n\nالوظيفة المختارة ونتيجة المطابقة (إن وجدت):\n' +
        (json.dumps(job_context, ensure_ascii=False) if job_context else 'لا توجد وظيفة مختارة.') +
        '\n\nطلب المستخدم: ' + user_message
    )
    print(f"[CV Improvement Expert] Selected job_id={match['job_id'] if match else None}")
    response = call_llm(system_prompt, user_prompt, temperature=0.3, history=history)
    return response or 'عذراً، لم أتمكن من اقتراح تحسينات للسيرة الآن. يرجى المحاولة مرة أخرى.'
