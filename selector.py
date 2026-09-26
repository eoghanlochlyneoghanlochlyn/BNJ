from __future__ import annotations

from config import COMPETITION_IDS, EXTRA_PRIORITY_TEAM_NAMES, PRIORITY_TEAM_IDS


def _norm(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _team_id(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("teamId") or "")
    return ""


def _team_name(value: object) -> str:
    if isinstance(value, dict):
        return str(
            value.get("longName")
            or value.get("name")
            or value.get("shortName")
            or ""
        )
    return str(value or "")


def _match_competition_id(match: dict) -> str:
    return str(
        match.get("leagueId")
        or match.get("competitionId")
        or match.get("tournamentId")
        or ""
    )


def _has_priority_team(match: dict) -> bool:
    priority_ids = {str(team_id) for team_id in PRIORITY_TEAM_IDS}
    priority_names = {_norm(name) for name in EXTRA_PRIORITY_TEAM_NAMES}

    for key in ("home", "away"):
        team = match.get(key) or match.get(f"{key}Team")
        if _team_id(team) in priority_ids:
            return True
        if _norm(_team_name(team)) in priority_names:
            return True

    return False


def qualifies(match: dict) -> bool:
    # A listed competition always qualifies, regardless of stage or old mode.
    if _match_competition_id(match) in {str(cid) for cid in COMPETITION_IDS}:
        return True

    # A listed team qualifies in any competition.
    return _has_priority_team(match)


def select_fixtures(matches: list[dict]) -> list[dict]:
    seen: set[str] = set()
    selected: list[dict] = []

    for match in matches:
        match_id = str(match.get("id") or match.get("matchId") or "")
        if not match_id or match_id in seen or not qualifies(match):
            continue
        seen.add(match_id)
        selected.append(match)

    def sort_key(item: dict) -> tuple:
        start = item.get("startIran") or item.get("start") or ""
        competition = _norm(
            item.get("competitionName")
            or item.get("competition")
            or item.get("league")
        )
        home = _norm(_team_name(item.get("home") or item.get("homeTeam")))
        return str(start), competition, home

    selected.sort(key=sort_key)
    return selected
