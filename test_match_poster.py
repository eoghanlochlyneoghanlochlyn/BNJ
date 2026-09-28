"""Generate and send a poster for explicitly chosen FotMob matches."""
import datetime as dt
from pathlib import Path

import requests

from config import IRAN_TIMEZONE
from fotmob import HEADERS, FOTMOB_BASE_URL, _parse_utc, enrich_match_stages
from renderer import render_fixtures
from telegram import send_photo


MATCH_IDS = [
    "6315013",
    "5795472",
    "6106414",
    "6112251",
    "6112421",
    "5868089",
    "5749694",
    "5802952",
    "5881180",
]


def get_match(match_id: str) -> dict:
    response = requests.get(
        f"{FOTMOB_BASE_URL}/api/data/matchDetails",
        params={"matchId": match_id},
        headers=HEADERS,
        timeout=40,
    )
    response.raise_for_status()
    details = response.json()

    if not isinstance(details, dict):
        raise RuntimeError(f"Invalid FotMob matchDetails response: {match_id}")

    page_props = ((details.get("props") or {}).get("pageProps") or {})
    content = details.get("content") or page_props.get("content") or {}
    general = details.get("general") or page_props.get("general") or {}
    header = details.get("header") or page_props.get("header") or {}

    if not isinstance(content, dict):
        content = {}
    if not isinstance(general, dict):
        general = {}
    if not isinstance(header, dict):
        header = {}

    teams = details.get("teams") or content.get("teams") or header.get("teams") or {}
    if not isinstance(teams, dict):
        teams = {}

    def team_from(value):
        if not isinstance(value, dict):
            return {}
        return {
            "id": value.get("id") or value.get("teamId") or value.get("teamID") or "",
            "name": (
                value.get("longName")
                or value.get("name")
                or value.get("shortName")
                or value.get("title")
                or ""
            ),
        }

    home = team_from(teams.get("home") or teams.get("homeTeam") or header.get("homeTeam"))
    away = team_from(teams.get("away") or teams.get("awayTeam") or header.get("awayTeam"))

    def find_side(value, side):
        if isinstance(value, dict):
            for key, child in value.items():
                key_low = str(key).casefold()
                if side == "home" and key_low in {"hometeam", "home_team", "home"}:
                    candidate = team_from(child)
                    if candidate.get("id") or candidate.get("name"):
                        return candidate
                if side == "away" and key_low in {"awayteam", "away_team", "away"}:
                    candidate = team_from(child)
                    if candidate.get("id") or candidate.get("name"):
                        return candidate
                candidate = find_side(child, side)
                if candidate:
                    return candidate
        elif isinstance(value, list):
            for child in value:
                candidate = find_side(child, side)
                if candidate:
                    return candidate
        return {}

    if not home.get("id") and not home.get("name"):
        home = find_side(details, "home")
    if not away.get("id") and not away.get("name"):
        away = find_side(details, "away")

    if not home.get("id") and not home.get("name"):
        raise RuntimeError(f"Home team unavailable in FotMob matchDetails: {match_id}")
    if not away.get("id") and not away.get("name"):
        raise RuntimeError(f"Away team unavailable in FotMob matchDetails: {match_id}")

    utc_value = (
        general.get("matchTimeUTC")
        or general.get("utcTime")
        or header.get("utcTime")
        or (header.get("status") or {}).get("utcTime")
        or details.get("utcTime")
        or details.get("matchTimeUTC")
    )
    parsed = _parse_utc(utc_value)

    if parsed is None:
        status = details.get("status") or content.get("status") or {}
        if isinstance(status, dict):
            parsed = _parse_utc(
                status.get("utcTime")
                or status.get("startTime")
                or status.get("timestamp")
            )

    if parsed is None:
        def find_time(value):
            if isinstance(value, dict):
                for key in ("utcTime", "matchTimeUTC", "startTime"):
                    candidate = _parse_utc(value.get(key))
                    if candidate is not None:
                        return candidate
                for child in value.values():
                    candidate = find_time(child)
                    if candidate is not None:
                        return candidate
            elif isinstance(value, list):
                for child in value:
                    candidate = find_time(child)
                    if candidate is not None:
                        return candidate
            return None

        parsed = find_time(details)

    if parsed is None:
        raise RuntimeError(f"Match time unavailable in FotMob matchDetails: {match_id}")

    league = (
        general.get("league")
        or header.get("league")
        or content.get("league")
        or details.get("league")
        or {}
    )
    if not isinstance(league, dict):
        league = {}

    return {
        "id": str(match_id),
        "start": parsed.isoformat(),
        "startIran": parsed.astimezone(IRAN_TIMEZONE).isoformat(),
        "home": {
            "id": str(home.get("id") or home.get("teamId") or ""),
            "name": str(home.get("longName") or home.get("name") or home.get("shortName") or ""),
        },
        "away": {
            "id": str(away.get("id") or away.get("teamId") or ""),
            "name": str(away.get("longName") or away.get("name") or away.get("shortName") or ""),
        },
        "leagueId": str(
            league.get("id")
            or league.get("leagueId")
            or league.get("primaryId")
            or ""
        ),
        "competitionName": str(
            league.get("name")
            or league.get("title")
            or general.get("leagueName")
            or header.get("leagueName")
            or ""
        ),
        "stage": "",
        "pageUrl": f"{FOTMOB_BASE_URL}/match/{match_id}",
    }


def main():
    matches = [get_match(match_id) for match_id in MATCH_IDS]

    enrich_match_stages(matches)

    print("Selected matches:")
    for match in matches:
        print(
            match["id"],
            "|",
            match["competitionName"],
            "|",
            match["startIran"],
            "|",
            match.get("stage"),
        )

    output_path = Path("output/test-fixtures.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    render_fixtures(matches, dt.date.today(), output_path)

    print(f"Poster generated: {output_path}")

    send_photo(output_path, "🧪 تست پوستر BNJ — مسابقات انتخابی")

    print("Poster sent to Telegram.")
    print("Daily report state was not modified.")


if __name__ == "__main__":
    main()
