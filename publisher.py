from __future__ import annotations

from typing import Any

from report_state import canonical_hash, report_changed

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
    return bool(
        matchup.get("homeTeamId")
        or matchup.get("awayTeamId")
        or matchup.get("homeTeam")
        or matchup.get("awayTeam")
    )


def _matchup_has_result(matchup: dict) -> bool:
    matches = matchup.get("matches") or []
    for item in matches:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if isinstance(status, dict):
            finished = status.get("finished")
            if finished is None:
                finished = status.get("isFinished")
            if finished is True:
                return True
        elif item.get("finished") is True or item.get("isFinished") is True:
            return True

        home = item.get("homeScore")
        away = item.get("awayScore")
        if home is not None and away is not None:
            return True

    return any(
        matchup.get(key) is not None
        for key in (
            "homeScore",
            "awayScore",
            "aggregatedResult",
            "aggregatedWinner",
            "winner",
            "penaltyScore",
        )
    )


def _matchup_complete(matchup: dict) -> bool:
    matches = matchup.get("matches") or []
    if matches:
        real_matches = [item for item in matches if isinstance(item, dict)]
        if real_matches:
            flags = []
            for item in real_matches:
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

            # If the provider exposes all legs with final scores but no
            # finished flag, treat the matchup as complete.
            if all(
                item.get("homeScore") is not None and item.get("awayScore") is not None
                for item in real_matches
            ):
                return True

    if matchup.get("aggregatedWinner") not in (None, "", 0) or matchup.get("winner"):
        return True

    return matchup.get("homeScore") is not None and matchup.get("awayScore") is not None


def knockout_stage_status(stage: dict | None) -> str:
    """
    Publication status for one knockout stage.

    not_ready  -> participants are not known yet
    teams_known -> all participants are known, no result yet
    in_progress -> at least one result exists, stage is not complete
    completed   -> every real matchup is complete
    """
    if not stage:
        return "not_ready"

    matchups = [
        m for m in stage.get("matchups") or []
        if isinstance(m, dict) and _has_real_matchup(m)
    ]
    if not matchups:
        return "not_ready"

    if all(_matchup_complete(m) for m in matchups):
        return "completed"

    if any(_matchup_has_result(m) for m in matchups):
        return "in_progress"

    return "teams_known"


def current_knockout_stage(rounds: list[dict]) -> dict | None:
    real = sorted(
        [
            r for r in rounds
            if isinstance(r, dict)
            and any(_has_real_matchup(m) for m in r.get("matchups") or [])
        ],
        key=_stage_key,
    )
    if not real:
        return None

    # The active round is the earliest real round that is not complete.
    # A later round may already have known participants, but it must not
    # replace the active round until all earlier matchups are complete.
    for stage in real:
        matchups = [
            m for m in stage.get("matchups") or []
            if isinstance(m, dict) and _has_real_matchup(m)
        ]
        if matchups and not all(_matchup_complete(m) for m in matchups):
            return stage

    return real[-1]


def knockout_ready(stage: dict | None) -> bool:
    return knockout_stage_status(stage) != "not_ready"


def knockout_fingerprint(data: dict, stage: dict, stage_status: str | None = None) -> str:
    base = _stage_key(stage)
    rounds = [
        r for r in data.get("knockoutRounds") or []
        if isinstance(r, dict) and _stage_key(r) >= base
    ]
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
                "matches": [
                    {
                        "id": item.get("id"),
                        "homeScore": item.get("homeScore"),
                        "awayScore": item.get("awayScore"),
                        "status": item.get("status"),
                    }
                    for item in (m.get("matches") or [])
                    if isinstance(item, dict)
                ],
            } for m in r.get("matchups") or []],
        })
    return canonical_hash({
        "stage": stage.get("stage"),
        "stage_status": stage_status,
        "rounds": compact,
    })


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


def register_if_changed(
    state: dict,
    *,
    key: str,
    fingerprint: str,
    report_type: str,
    competition_id: str,
    season: str,
    stage: str | None = None,
    stage_status: str | None = None,
) -> bool:
    # This is deliberately a check only. The state is written only after
    # Telegram accepts the message, so a failed send can be retried safely.
    return report_changed(
        state,
        key,
        fingerprint,
        stage=stage,
        stage_status=stage_status,
    )
