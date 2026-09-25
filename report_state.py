from __future__ import annotations

import json
from pathlib import Path

STATE_PATH = Path("report_state.json")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def already_sent(state: dict, key: str) -> bool:
    return bool(state.get(key))


def mark_sent(state: dict, key: str) -> None:
    state[key] = True
    save_state(state)
