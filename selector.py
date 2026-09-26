from __future__ import annotations

from config import COMPETITION_IDS, MAJOR_LEAGUE_IDS, PRIORITY_TEAM_IDS


def _team_id(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("teamId") or "")
    return ""


def _match_competition_id(match: dict) -> str:
    return str(
        match.get("leagueId")
        or match.get("competitionId")
        or match.get("tournamentId")
        or ""
    )


def _has_priority_team(match: dict) -> bool:
    for key in ("home", "away"):
        team = match.get(key) or match.get(f"{key}Team")
        if _team_id(team) in PRIORITY_TEAM_IDS:
            return True
    return False


def qualifies(match: dict) -> bool:
    # Selection is strictly numeric: competition ID or priority team ID.
    competition_id = _match_competition_id(match)

    if competition_id in COMPETITION_IDS:
        return True

    if competition_id in MAJOR_LEAGUE_IDS:
        return True

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
        competition = str(
            item.get("competitionName")
            or item.get("competition")
            or item.get("league")
            or ""
        ).casefold()
        home = item.get("home") or item.get("homeTeam") or {}
        if isinstance(home, dict):
            home = home.get("longName") or home.get("name") or home.get("shortName") or ""
        return str(start), " ".join(competition.split()), str(home).casefold()

    selected.sort(key=sort_key)
    return selected
