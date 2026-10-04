from __future__ import annotations

import hashlib
import json
import datetime as dt
from pathlib import Path
from typing import Any

STATE_PATH = Path("report_state.json")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def already_sent(state: dict, key: str) -> bool:
    value = state.get(key)
    if isinstance(value, dict):
        return bool(value.get("sent"))
    return bool(value)


def mark_sent(state: dict, key: str, metadata: dict | None = None) -> None:
    if metadata is None:
        state[key] = True
    else:
        record = dict(metadata)
        record["sent"] = True
        state[key] = record
    save_state(state)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def report_changed(
    state: dict,
    key: str,
    fingerprint: str,
    *,
    stage: str | None = None,
    stage_status: str | None = None,
) -> bool:
    previous = state.get(key)
    if not isinstance(previous, dict):
        return True
    if previous.get("fingerprint") != fingerprint:
        return True
    if stage is not None and previous.get("stage") != stage:
        return True
    if stage_status is not None and previous.get("stage_status") != stage_status:
        return True
    return False


def mark_report_sent(
    state: dict,
    key: str,
    fingerprint: str,
    *,
    report_type: str,
    competition_id: str,
    season: str,
    stage: str | None = None,
    stage_status: str | None = None,
) -> None:
    record = {
        "fingerprint": fingerprint,
        "report_type": report_type,
        "competition_id": str(competition_id),
        "season": season,
        "stage": stage,
        "stage_status": stage_status,
        "sent_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sent": True,
    }
    previous = state.get(key)
    if isinstance(previous, dict) and isinstance(previous.get("history"), list):
        history = previous["history"]
    else:
        history = []
        if isinstance(previous, dict) and previous.get("sent"):
            history.append({
                "fingerprint": previous.get("fingerprint"),
                "report_type": previous.get("report_type"),
                "competition_id": previous.get("competition_id"),
                "season": previous.get("season"),
                "stage": previous.get("stage"),
                "stage_status": previous.get("stage_status"),
                "sent_at": previous.get("sent_at"),
            })

    history.append({k: v for k, v in record.items() if k != "sent"})
    record["history"] = history[-50:]
    state[key] = record
    save_state(state)
