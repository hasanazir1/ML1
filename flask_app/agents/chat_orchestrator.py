"""Route chat messages to the right expert."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from flask_app.utils.llm_service import call_llm, extract_json_from_response
from flask_app.database import db
from flask_app.utils.prompts import build_agent_prompt

ALLOWED_AGENTS = {
    "Chat Query Expert",
    "Cover Letter Generator Expert",
    "CV Improvement Expert",
}

# Returned when the model's decision cannot be resolved into a confident action.
NEEDS_CLARIFICATION = "NeedsClarification"

# Output contract shared with the stored "Chat Orchestrator" prompt (llm_roles):
#   {"agent": "Chat Query Expert" | "Cover Letter Generator Expert" | "CV Improvement Expert",
#    "job_id": <job id from the provided list, or null>,
#    "needs_clarification": <true | false>}
RESPONSE_CONTRACT = (
    '{"agent": "Chat Query Expert" أو "Cover Letter Generator Expert" أو "CV Improvement Expert", '
    '"job_id": رقم الوظيفة من القائمة أو null, '
    '"needs_clarification": true أو false}'
)


def route_message(user_message, jobs_list, history=None):
    """Return the selected agent, job id, and original message.

    target_role is one of: "Chat Query Expert", "Cover Letter Generator Expert", "CV Improvement Expert",
    or NEEDS_CLARIFICATION when no confident decision can be made.
    """
    role_info = db.get_llm_role("Chat Orchestrator")
    system_prompt = build_agent_prompt(role_info, 'Chat Orchestrator',
        "وجه الرسالة للخبير المناسب. أرجِع JSON فقط بالشكل: " + RESPONSE_CONTRACT)

    jobs_context = "\n".join(
        f"- job_id={j['job_id']}: {j['title']} في {j.get('company', 'غير محدد')}"
        for j in jobs_list[:10]
    )
    user_prompt = f"""الوظائف المتاحة:
{jobs_context}

رسالة المستخدم: {user_message}

أجب بـ JSON فقط وفق التعليمات."""

    response = call_llm(system_prompt, user_prompt, temperature=0.2, history=history)
    if response is None:
        return 'ServiceUnavailable', None, user_message

    job_id = None
    target_role = NEEDS_CLARIFICATION
    reason = "unresolved"

    def fail(reason_text, error=None):
        nonlocal target_role, reason
        target_role = NEEDS_CLARIFICATION
        reason = reason_text
        if error is not None:
            print('[Chat Orchestrator] Invalid decision; requesting clarification')

    try:
        decision = extract_json_from_response(response)
        if not isinstance(decision, dict):
            raise ValueError(f"expected a JSON object, got {type(decision).__name__}")

        requested_agent = decision.get("agent")
        if requested_agent not in ALLOWED_AGENTS:
            raise ValueError(f"unknown agent {requested_agent!r}")

        needs_clarification = decision.get("needs_clarification")
        if type(needs_clarification) is not bool:
            raise ValueError('needs_clarification must be a boolean')
        raw_job_id = decision.get("job_id")
        parsed_job_id = raw_job_id if type(raw_job_id) is int else None
        allowed_ids = {j.get("job_id") for j in jobs_list}

        if needs_clarification:
            target_role = NEEDS_CLARIFICATION
            reason = "model requested clarification"
        elif requested_agent == "Cover Letter Generator Expert":
            if parsed_job_id is not None and parsed_job_id in allowed_ids:
                target_role = requested_agent
                job_id = parsed_job_id
                reason = "job resolved via job_id"
            else:
                target_role = NEEDS_CLARIFICATION
                reason = "cover letter requested but job_id missing or not in the user's matched jobs"
        elif requested_agent == "CV Improvement Expert":
            if raw_job_id is not None and parsed_job_id not in allowed_ids:
                target_role = NEEDS_CLARIFICATION
                reason = "CV improvement requested for a job outside the matched jobs"
            else:
                target_role = requested_agent
                job_id = parsed_job_id
                reason = "CV improvement request"
        else:
            target_role = requested_agent
            reason = "query request"
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        fail("unparseable model response", error=exc)

    print(
        f"[Chat Orchestrator] "
        f"agent={target_role} job_id={job_id} reason={reason!r}"
    )
    return target_role, job_id, user_message
