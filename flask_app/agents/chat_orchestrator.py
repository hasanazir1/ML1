"""Route chat messages to the right expert."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm
from flask_app.database import db

ALLOWED_AGENTS = {
    "Chat Query Expert",
    "Cover Letter Generator Expert",
}


def route_message(user_message, jobs_list):
    """Return the selected agent, job id, and original message."""
    role_info = db.get_llm_role("Chat Orchestrator")
    system_prompt = role_info["specific_instructions"] if role_info else "وجه الرسالة للخبير المناسب"

    jobs_context = "\n".join(
        f"- job_id={j['job_id']}: {j['title']} في {j.get('company', 'غير محدد')}"
        for j in jobs_list[:10]
    )
    user_prompt = f"""الوظائف المتاحة:
{jobs_context}

رسالة المستخدم: {user_message}

حدد إذا كان الطلب يتعلق بوظيفة معينة (حدد job_id) أو عام."""

    response = call_llm(system_prompt, user_prompt, temperature=0.2)

    job_id = None
    target_role = "Chat Query Expert"
    reason = "Invalid orchestrator response"
    processed_msg = user_message

    try:
        decision = json.loads(response or "")
        requested_agent = decision.get("agent")
        if requested_agent in ALLOWED_AGENTS:
            target_role = requested_agent
            reason = decision.get("reason") or "No reason provided"
        else:
            reason = "Unknown agent"
    except (json.JSONDecodeError, TypeError, AttributeError):
        reason = "Invalid JSON"

    if target_role == "Cover Letter Generator Expert":
        for job in jobs_list:
            if job.get("title", "").lower() in user_message.lower():
                job_id = job["job_id"]
                break

    print(
        f"[Chat Orchestrator] message={user_message!r} "
        f"agent={target_role} reason={reason!r}"
    )
    return target_role, job_id, processed_msg
