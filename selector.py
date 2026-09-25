from __future__ import annotations

from config import COMPETITION_KEYWORDS, MAJOR_LEAGUES, PRIORITY_TEAMS


def _norm(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def qualifies(match: dict) -> bool:
    competition = _norm(
        match.get("competition") or match.get("league")
        or match.get("tournament") or match.get("competitionName")
    )

    if any(_norm(name) in competition for name in MAJOR_LEAGUES):
        return True

    if any(keyword in competition for keyword in COMPETITION_KEYWORDS):
        return True

    home = _norm(match.get("home") or match.get("homeTeam", {}).get("name"))
    away = _norm(match.get("away") or match.get("awayTeam", {}).get("name"))
    priority = {_norm(name) for name in PRIORITY_TEAMS}
    return home in priority or away in priority


def select_fixtures(matches: list[dict]) -> list[dict]:
    seen: set[str] = set()
    selected: list[dict] = []

    for match in matches:
        match_id = str(match.get("id") or match.get("matchId") or "")
        if not match_id or match_id in seen or not qualifies(match):
            continue
        seen.add(match_id)
        selected.append(match)

    selected.sort(key=lambda item: (
        item.get("startTimestamp", item.get("start", 0)) or 0,
        _norm(item.get("competition") or item.get("league")),
        _norm(item.get("home")),
    ))
    return selected
