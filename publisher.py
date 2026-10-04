from __future__ import annotations

from typing import Any

from report_state import canonical_hash, report_changed, mark_report_sent

_STAGE_ORDER = {
    "پلی‌آف": 10,
    "یک‌شصت‌وچهارم نهایی": 20,
    "یک‌شانزدهم نهایی": 30,
    "یک‌هشتم نهایی": 40,
    "یک‌چهارم نهایی": 50,
    "نیمه‌نهایی": 60,
    "فینال": 70,
    "رده‌بندی": 80,
}


def _stage_key(stage: dict) -> int:
    label = str(stage.get("stage") or "").strip()
    if label in _STAGE_ORDER:
        return _STAGE_ORDER[label]
    count = int(stage.get("participantCount") or 0)
    return {64: 20, 32: 30, 16: 40, 8: 50, 4: 60, 2: 70}.get(count, 0)


def _has_real_matchup(matchup: dict) -> bool:
    if matchup.get("tbdTeam1") or matchup.get("tbdTeam2"):
        return False
    return bool(matchup.get("homeTeamId") or matchup.get("awayTeamId") or matchup.get("homeTeam") or matchup.get("awayTeam"))


def current_knockout_stage(rounds: list[dict]) -> dict | None:
    real = [r for r in rounds if isinstance(r, dict) and any(_has_real_matchup(m) for m in r.get("matchups") or [])]
    return max(real, key=_stage_key) if real else None


def _matchup_complete(matchup: dict) -> bool:
    matches = matchup.get("matches") or []
    flags = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if isinstance(status, dict):
            finished = status.get("finished")
            if finished is None:
                finished = status.get("isFinished")
        else:
            finished = item.get("finished")
            if finished is None:
                finished = item.get("isFinished")
        if finished is not None:
            flags.append(bool(finished))
    if flags:
        return all(flags)
    if matchup.get("aggregatedWinner") not in (None, "", 0) or matchup.get("winner"):
        return True
    return matchup.get("homeScore") is not None and matchup.get("awayScore") is not None


def knockout_ready(stage: dict | None) -> bool:
    if not stage:
        return False
    return any(_matchup_complete(m) for m in stage.get("matchups") or [] if _has_real_matchup(m))


def knockout_fingerprint(data: dict, stage: dict) -> str:
    base = _stage_key(stage)
    rounds = [r for r in data.get("knockoutRounds") or [] if _stage_key(r) >= base]
    compact = []
    for r in rounds:
        compact.append({
            "stage": r.get("stage"),
            "matchups": [{
                "number": m.get("number"),
                "homeTeamId": m.get("homeTeamId"),
                "awayTeamId": m.get("awayTeamId"),
                "homeTeam": m.get("homeTeam"),
                "awayTeam": m.get("awayTeam"),
                "homeScore": m.get("homeScore"),
                "awayScore": m.get("awayScore"),
                "winner": m.get("winner"),
                "aggregatedResult": m.get("aggregatedResult"),
                "aggregatedWinner": m.get("aggregatedWinner"),
                "penaltyScore": m.get("penaltyScore"),
            } for m in r.get("matchups") or []],
        })
    return canonical_hash(compact)


def table_fingerprint(table: dict) -> str:
    rows = [{
        "rank": row.get("rank"),
        "teamId": row.get("teamId"),
        "played": row.get("played"),
        "wins": row.get("wins"),
        "draws": row.get("draws"),
        "losses": row.get("losses"),
        "goalsFor": row.get("goalsFor"),
        "goalsAgainst": row.get("goalsAgainst"),
        "goalDiff": row.get("goalDiff"),
        "points": row.get("points"),
        "form": row.get("form"),
    } for row in table.get("rows") or []]
    return canonical_hash({"group": table.get("group"), "rows": rows})


def register_if_changed(state: dict, *, key: str, fingerprint: str, report_type: str, competition_id: str, season: str, stage: str | None = None) -> bool:
    if not report_changed(state, key, fingerprint, stage=stage):
        return False
    mark_report_sent(state, key, fingerprint, report_type=report_type, competition_id=competition_id, season=season, stage=stage)
    return True
