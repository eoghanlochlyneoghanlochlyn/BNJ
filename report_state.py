from __future__ import annotations

import hashlib
import json
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
    """Backward-compatible boolean check used by fixtures/results."""
    value = state.get(key)
    if isinstance(value, dict):
        return bool(value.get("sent"))
    return bool(value)


def mark_sent(state: dict, key: str, metadata: dict | None = None) -> None:
    """Record a sent report. Old boolean callers remain supported."""
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
) -> bool:
    """Return True only when this report state differs from the last sent one."""
    previous = state.get(key)
    if not isinstance(previous, dict):
        return True
    if previous.get("fingerprint") != fingerprint:
        return True
    if stage is not None and previous.get("stage") != stage:
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
) -> None:
    mark_sent(
        state,
        key,
        {
            "fingerprint": fingerprint,
            "report_type": report_type,
            "competition_id": str(competition_id),
            "season": season,
            "stage": stage,
        },
    )
