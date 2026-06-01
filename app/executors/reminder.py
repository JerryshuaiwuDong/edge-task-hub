import logging

from app.ai.local_llm import generate_text
from app.ai.prompt_vars import render_prompt
from app.models import Task
from app.notifier import send_markdown

logger = logging.getLogger(__name__)


def run(task: Task, payload: dict) -> tuple[str, str, str]:
    fallback = payload.get("message", "").strip() or task.description or "Reminder"
    title = task.name or "Reminder"

    if getattr(task, "use_ai", False) and (task.ai_prompt_template or "").strip():
        template = task.ai_prompt_template.strip()
        prompt = render_prompt(template, task.name, task.timezone)
        logger.info("Generating reminder via local LLM for task %s", task.id)
        body, llm_err = generate_text(prompt, max_tokens=200, timeout=180, fallback=fallback)
        if llm_err:
            logger.warning("LLM fallback for task %s: %s", task.id, llm_err)
            output_note = f"LLM warning: {llm_err}. Used fallback text."
        else:
            output_note = "AI-generated via local Ollama model on device."
        message = f"🤖 AI-generated · {title}\n\n{body}"
        ok, detail = send_markdown(f"🤖 AI-generated · {title}", body)
        if ok:
            return "success", f"{output_note}\n{detail}", ""
        return "failed", "", detail

    message = fallback
    ok, detail = send_markdown(title, message)
    if ok:
        return "success", detail, ""
    return "failed", "", detail
