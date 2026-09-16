"""Generate a cover letter for a selected job."""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm
from flask_app.database import db
from flask_app.utils.prompts import build_agent_prompt


def _as_list(value):
    """Return a list whether the DB field comes back as JSON text or a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def generate_cover_letter(cv_data, job_data, profile_id, user_message='', history=None):
    """Generate a cover letter from CV and job data."""
    role_info = db.get_llm_role("Cover Letter Generator Expert")
    system_prompt = build_agent_prompt(role_info, 'Cover Letter Generator Expert', 'اكتب Cover Letter احترافي.')

    company = (job_data.get("company") or "").strip()
    if company.lower() == "jobs.ps":
        company = ""
    addressee = company if company else "لجنة التوظيف في الجهة المعلنة في إعلان الوظيفة"
    today = datetime.now().strftime("%Y-%m-%d")
    cv_text = (cv_data.get("raw_text") or "")[:4000]

    user_prompt = f"""بيانات المتقدم:
- الاسم: {cv_data.get("name", "")}
- البريد الإلكتروني: {cv_data.get("email") or "غير متوفر"}
- المهارات: {", ".join(_as_list(cv_data.get("skills")))}
- الخبرات: {_as_list(cv_data.get("experience"))}
- المستوى: {cv_data.get("level", "")}
- ملخص: {cv_data.get("summary", "")}
- تاريخ اليوم الفعلي: {today}

مقتطف من نص السيرة الذاتية (ابحث فيه عن رقم الهاتف وبيانات الاتصال):
{cv_text}

الوظيفة المطلوبة:
- المسمى: {job_data.get("title", "")}
- الشركة/الجهة: {addressee}
- الوصف: {job_data.get("description", "")}

تعليمات إلزامية:
1. خاطب الرسالة إلى {addressee} وفريق التوظيف فيها فقط. لا تذكر أبداً اسم موقع jobs.ps أو أي موقع إعلانات وسيط في الرسالة.
2. استخدم تاريخ اليوم الفعلي المذكور أعلاه، ولا تكتب أبداً عنصراً نائباً مثل [تاريخ اليوم].
3. استخدم البريد الإلكتروني الحقيقي المذكور أعلاه، ولا تكتب أبداً عنصراً نائباً مثل [عنوان البريد الإلكتروني].
4. ابحث عن رقم الهاتف في نص السيرة الذاتية أعلاه واستخدمه. إذا لم تجد رقم هاتف، احذف سطر الهاتف نهائياً من الرسالة ولا تكتب [رقم الهاتف].
5. لا تترك أي عنصر نائب بين أقواس مربعة [...] في الرسالة النهائية.

اكتب رسالة تقديم احترافية مخصصة لهذه الوظيفة."""

    user_prompt += f'\nطلب المستخدم الحالي (مثل اللغة أو طول الرسالة):\n{user_message}'
    print(f"[Cover Letter Generator Expert] Selected job_id={job_data.get('job_id')}")
    response = call_llm(system_prompt, user_prompt, temperature=0.3, history=history)
    return response or "عذراً، لم أتمكن من كتابة رسالة التقديم. يرجى المحاولة مرة أخرى."
