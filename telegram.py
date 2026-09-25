from __future__ import annotations

import os
from pathlib import Path

import requests

API = "https://api.telegram.org"


def send_photo(path: Path, caption: str = "") -> None:
    token = os.environ.get("TELEGRAMBOT")
    chat_id = os.environ.get("TELEGRAMCHANNEL")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAMBOT or TELEGRAMCHANNEL GitHub secret.")

    url = f"{API}/bot{token}/sendPhoto"
    with path.open("rb") as photo:
        response = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": (path.name, photo, "image/png")},
            timeout=60,
        )
    if not response.ok:
        raise RuntimeError(
            f"Telegram send failed: HTTP {response.status_code}: {response.text[:500]}"
        )

    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API rejected the message: {payload}")
