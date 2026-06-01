import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)


def _webhook_configured() -> bool:
    url = settings.feishu_webhook_url.strip()
    return bool(url) and url != "REPLACE_ME"


def send_text(message: str) -> tuple[bool, str]:
    """Send plain text to Lark/Feishu custom bot webhook."""
    if not _webhook_configured():
        return False, "Feishu webhook is not configured. Set FEISHU_WEBHOOK_URL in .env."

    payload = {
        "msg_type": "text",
        "content": {"text": message[:4000]},
    }
    try:
        resp = requests.post(settings.feishu_webhook_url, json=payload, timeout=15)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code == 200 and data.get("code", 0) == 0:
            return True, "Message sent successfully."
        return False, f"Webhook error: HTTP {resp.status_code} {data or resp.text[:200]}"
    except requests.RequestException as exc:
        logger.exception("Feishu send failed")
        return False, str(exc)


def send_markdown(title: str, content: str) -> tuple[bool, str]:
    """Send interactive card style markdown to Lark/Feishu."""
    if not _webhook_configured():
        return False, "Feishu webhook is not configured. Set FEISHU_WEBHOOK_URL in .env."

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title[:100]}},
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content[:8000]},
                }
            ],
        },
    }
    try:
        resp = requests.post(settings.feishu_webhook_url, json=payload, timeout=15)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code == 200 and data.get("code", 0) == 0:
            return True, "Message sent successfully."
        # Some older webhooks do not support interactive cards, so send text instead.
        fallback = f"**{title}**\n\n{content}"
        return send_text(fallback)
    except requests.RequestException as exc:
        logger.exception("Feishu markdown send failed")
        return False, str(exc)
