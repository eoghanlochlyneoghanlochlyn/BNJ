from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

import requests

from config import IRAN_TIMEZONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}


def _walk(node: Any, out: list[dict]) -> None:
    if isinstance(node, dict):
        if (("home" in node and "away" in node)
                or ("homeTeam" in node and "awayTeam" in node)):
            out.append(node)
        for value in node.values():
            _walk(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, out)


def _normalize(raw: dict) -> dict:
    home = raw.get("home") or raw.get("homeTeam") or {}
    away = raw.get("away") or raw.get("awayTeam") or {}
    tournament = raw.get("tournament") or raw.get("league") or {}
    if not isinstance(home, dict):
        home = {"name": home}
    if not isinstance(away, dict):
        away = {"name": away}
    if not isinstance(tournament, dict):
        tournament = {"name": tournament}

    return {
        "id": raw.get("id") or raw.get("matchId"),
        "home": home.get("name") or home.get("longName") or "",
        "away": away.get("name") or away.get("longName") or "",
        "home_id": home.get("id") or raw.get("homeTeamId"),
        "away_id": away.get("id") or raw.get("awayTeamId"),
        "competition": tournament.get("name") or raw.get("competitionName") or raw.get("leagueName") or "",
        "startTimestamp": raw.get("startTimestamp") or raw.get("kickoffTimestamp") or raw.get("timestamp") or raw.get("start"),
    }


def fetch_matches_for_iran_date(day: dt.date) -> list[dict]:
    url = "https://www.fotmob.com/api/data/matches"
    response = requests.get(url, params={"date": day.strftime("%Y%m%d")}, headers=HEADERS, timeout=40)
    response.raise_for_status()

    raw_matches: list[dict] = []
    _walk(response.json(), raw_matches)

    result, seen = [], set()
    for raw in raw_matches:
        match = _normalize(raw)
        match_id = str(match.get("id") or "")
        if not match_id or match_id in seen:
            continue
        seen.add(match_id)

        ts = match.get("startTimestamp")
        try:
            if ts is None:
                continue
            if isinstance(ts, str) and not ts.isdigit():
                parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                parsed = dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc)
            iran_dt = parsed.astimezone(IRAN_TIMEZONE)
            if iran_dt.date() == day:
                match["startIran"] = iran_dt.isoformat()
                result.append(match)
        except (TypeError, ValueError, OverflowError):
            continue
    return result
