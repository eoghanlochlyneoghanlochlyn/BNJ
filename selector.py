from __future__ import annotations

from config import COMPETITION_IDS, MAJOR_LEAGUE_IDS, PRIORITY_TEAM_IDS


def _team_id(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("teamId") or "")
    return ""


def _candidate_competition_ids(match: dict) -> set[str]:
    """Collect every numeric competition identity extracted from FotMob."""
    ids: set[str] = set()

    for key in (
        "leagueId",
        "competitionId",
        "tournamentId",
        "primaryLeagueId",
        "primaryId",
        "parentLeagueId",
    ):
        value = match.get(key)
        if value not in (None, ""):
            ids.add(str(value))

    raw_league = match.get("rawLeague") or {}
    if isinstance(raw_league, dict):
        for key in (
            "id",
            "leagueId",
            "competitionId",
            "tournamentId",
            "primaryId",
            "parentLeagueId",
        ):
            value = raw_league.get(key)
            if value not in (None, ""):
                ids.add(str(value))

    return ids


def _match_competition_id(match: dict) -> str:
    """Return the configured competition ID when any extracted ID matches."""
    candidates = _candidate_competition_ids(match)
    configured = COMPETITION_IDS | MAJOR_LEAGUE_IDS

    for competition_id in configured:
        if competition_id in candidates:
            return competition_id

    return next(iter(candidates), "")


def _has_priority_team(match: dict) -> bool:
    for key in ("home", "away"):
        team = match.get(key) or match.get(f"{key}Team")
        if _team_id(team) in PRIORITY_TEAM_IDS:
            return True
    return False


def qualifies(match: dict) -> bool:
    # FotMob may expose a concrete group/subcompetition ID (e.g. 920743)
    # while primaryId identifies the actual competition (e.g. 9806).
    # The final decision is based on whether ANY extracted numeric identity
    # belongs to our configured competition set.
    competition_ids = _candidate_competition_ids(match)

    if competition_ids & (COMPETITION_IDS | MAJOR_LEAGUE_IDS):
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
