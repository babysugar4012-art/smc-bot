"""
Sends messages to a Telegram chat/channel via the Bot API.
"""

import requests


def send_message(bot_token, chat_id, text, parse_mode="Markdown"):
    if not bot_token or not chat_id:
        print("[telegram] missing bot token or chat id, skipping send")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code != 200:
            print(f"[telegram] send failed: {resp.status_code} {resp.text}")
            return False
        return True
    except Exception as e:
        print(f"[telegram] send error: {e}")
        return False
