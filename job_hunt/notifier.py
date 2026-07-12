import urllib.parse
from typing import Any

import requests

_DISCORD_CONTENT_LIMIT = 2000
_DISCORD_SAFE_CHUNK = 1900


def _chunk_discord_message(message: str) -> list[str]:
    if len(message) <= _DISCORD_CONTENT_LIMIT:
        return [message]

    chunks: list[str] = []
    current = ""
    for line in message.splitlines(keepends=True):
        if len(line) > _DISCORD_SAFE_CHUNK:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for i in range(0, len(line), _DISCORD_SAFE_CHUNK):
                chunks.append(line[i: i + _DISCORD_SAFE_CHUNK].rstrip())
            continue
        if len(current) + len(line) > _DISCORD_SAFE_CHUNK:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current:
        chunks.append(current.rstrip())
    return chunks


def send_whatsapp(phone: str, apikey: str, message: str) -> bool:
    encoded = urllib.parse.quote(message)
    url = f"https://api.textmebot.com/send.php?phone={phone}&text={encoded}&apikey={apikey}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            print("WhatsApp sent.")
            return True
        print(f"WhatsApp failed: HTTP {resp.status_code} — {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"WhatsApp error: {e}")
        return False


def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            print("Telegram sent.")
            return True
        print(f"Telegram failed: HTTP {resp.status_code} — {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def send_discord(webhook_url: str, message: str) -> bool:
    try:
        for chunk in _chunk_discord_message(message):
            payload: dict[str, Any] = {"content": chunk, "allowed_mentions": {"parse": []}}
            resp = requests.post(webhook_url, json=payload, timeout=15)
            if resp.status_code not in (200, 204):
                print(f"Discord failed: HTTP {resp.status_code} — {resp.text[:200]}")
                return False
        print("Discord sent.")
        return True
    except Exception as e:
        print(f"Discord error: {e}")
        return False
