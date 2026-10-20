from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)


def _call(method: str, payload: dict, token: str | None, chat_id: str | None, timeout: float) -> bool:
    """Apelează metoda `method` a botului Telegram. Citește TELEGRAM_BOT_TOKEN /
    TELEGRAM_CHAT_ID din mediu dacă nu sunt date explicit."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID lipsesc, %s nu a fost trimis:\n%s", method, payload)
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json={"chat_id": chat_id, **payload},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        # nu logăm excepția întreagă: conține URL-ul, deci tokenul botului
        logger.error("Telegram a eșuat: %s", type(exc).__name__)
        return False
    if not resp.ok:
        logger.error("Telegram a răspuns %s: %s", resp.status_code, resp.text[:200])
        return False
    return True


def send(text: str, token: str | None = None, chat_id: str | None = None, timeout: float = 15.0) -> bool:
    """Trimite un mesaj text. Un mesaj care conține doar un emoji (ex. "🎉",
    "😭") apare în Telegram mare și animat."""
    return _call("sendMessage", {"text": text, "disable_web_page_preview": True}, token, chat_id, timeout)


def send_animation(url: str, caption: str, token: str | None = None, chat_id: str | None = None,
                   timeout: float = 30.0) -> bool:
    """Trimite un GIF (link public, Telegram îl descarcă singur) cu textul ca descriere."""
    return _call("sendAnimation", {"animation": url, "caption": caption}, token, chat_id, timeout)
