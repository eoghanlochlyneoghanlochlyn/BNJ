from __future__ import annotations

import datetime as dt
from typing import Any

import requests

from config import IRAN_TIMEZONE

FOTMOB_BASE_URL = "https://www.fotmob.com"
DAILY_MATCHES_URL = f"{FOTMOB_BASE_URL}/api/data/matches"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": FOTMOB_BASE_URL + "/",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split()).strip()


def _parse_utc(value: Any) -> dt.datetime | None:
    if value is None:
        return None

    text = _clean(value)
    if not text:
        return None

    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        pass

    try:
        timestamp = float(text)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _normalize_match(raw: dict, league: dict) -> dict | None:
    match_id = raw.get("id") or raw.get("matchId")
    if match_id is None:
        return None

    home = raw.get("home") or raw.get("homeTeam") or {}
    away = raw.get("away") or raw.get("awayTeam") or {}
    if not isinstance(home, dict):
        home = {}
    if not isinstance(away, dict):
        away = {}

    status = raw.get("status")
    if not isinstance(status, dict):
        status = {}

    start_value = (
        status.get("utcTime")
        or raw.get("utcTime")
        or raw.get("startTime")
        or raw.get("matchTimeUTC")
        or raw.get("startTimestamp")
    )
    start_utc = _parse_utc(start_value)
    if start_utc is None:
        return None

    league_id = (
        league.get("primaryId")
        or league.get("leagueId")
        or league.get("competitionId")
        or league.get("id")
    )

    competition_name = _clean(
        league.get("name")
        or league.get("title")
        or league.get("shortName")
    )

    home_name = _clean(
        home.get("longName")
        or home.get("name")
        or home.get("shortName")
    )
    away_name = _clean(
        away.get("longName")
        or away.get("name")
        or away.get("shortName")
    )

    iran_dt = start_utc.astimezone(IRAN_TIMEZONE)

    return {
        "id": str(match_id),
        "start": start_utc.isoformat(),
        "startIran": iran_dt.isoformat(),
        "home": {
            "id": str(home.get("id") or home.get("teamId") or ""),
            "name": home_name,
        },
        "away": {
            "id": str(away.get("id") or away.get("teamId") or ""),
            "name": away_name,
        },
        "leagueId": str(league_id) if league_id is not None else "",
        "competitionName": competition_name,
        "stage": (
            raw.get("stage") or raw.get("round") or raw.get("roundName")
            or raw.get("matchweek") or raw.get("matchday") or raw.get("group")
            or league.get("roundName") or league.get("round") or league.get("stage")
        ),
        "pageUrl": (
            raw.get("pageUrl")
            or raw.get("url")
            or f"{FOTMOB_BASE_URL}/match/{match_id}"
        ),
    }



def _stage_label(value: Any) -> str:
    """Extract an actual match round/group, never fabricate a group."""
    if isinstance(value, (int, float)):
        return f"Week {int(value)}"
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "displayName", "roundName", "groupName", "shortName", "stageName"):
            label = _stage_label(value.get(key))
            if label:
                return label
        for key in ("group", "groupId", "groupName"):
            label = _stage_label(value.get(key))
            if label:
                return f"Group {label}" if not label.lower().startswith("group") else label
        for key in ("round", "matchweek", "matchday", "week", "roundNumber"):
            label = _stage_label(value.get(key))
            if label:
                return label if not label.isdigit() else f"Week {label}"
    return ""


def _extract_match_stage(details: dict) -> str:
    """Read match-specific FotMob matchFacts/overview before league metadata."""
    page_props = ((details.get("props") or {}).get("pageProps") or {})
    content = details.get("content") or page_props.get("content") or {}
    if not isinstance(content, dict):
        content = {}
    facts = content.get("matchFacts") or {}
    if not isinstance(facts, dict):
        facts = {}
    page_props = ((details.get("props") or {}).get("pageProps") or {})
    info = details.get("general") or page_props.get("general") or {}
    if not isinstance(info, dict):
        info = {}
    overview = content.get("overview") or {}
    if not isinstance(overview, dict):
        overview = {}
    header = details.get("header") or page_props.get("header") or {}
    if not isinstance(header, dict):
        header = {}
    candidates = (
        facts.get("infoBox"),
        (facts.get("infoBox") or {}).get("Tournament") if isinstance(facts.get("infoBox"), dict) else None,
        facts.get("tournament"),
        overview.get("tournament"),
        info,
        header.get("league"),
        details.get("league"),
    )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("leagueName", "groupName", "group", "matchRound", "leagueRoundName", "roundName", "round", "matchweek",
                    "matchday", "stage", "stageName"):
            value = candidate.get(key)
            if key == "leagueName" and isinstance(value, str):
                import re
                match = re.search(r"\bGrp\.\s*([A-Za-z0-9]+)", value, re.I)
                if match:
                    return f"Group {match.group(1)}"
            label = _stage_label(value)
            if label:
                if key in ("matchRound", "leagueRoundName") and label.isdigit():
                    return f"Week {label}"
                if key in ("groupName", "group") and not label.lower().startswith("group"):
                    return f"Group {label}"
                return label
    return ""


def enrich_match_stages(matches: list[dict]) -> None:
    """Fetch details only for selected fixtures; leave unknown stages blank."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_one(match: dict) -> tuple[dict, str]:
        try:
            response = requests.get(
                f"{FOTMOB_BASE_URL}/api/data/matchDetails",
                params={"matchId": match["id"]},
                headers=HEADERS,
                timeout=12,
            )
            response.raise_for_status()
            details = response.json()
            if isinstance(details, dict):
                return match, _extract_match_stage(details)
        except (requests.RequestException, ValueError) as error:
            print(f"[STAGE] Match {match['id']}: details unavailable: {error}")
        return match, ""

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_one, match) for match in matches]
        for future in as_completed(futures):
            match, stage = future.result()
            if stage:
                match["stage"] = stage
            print(f"[STAGE] {match['id']}: {match.get('stage') or 'unknown'}")

def fetch_matches_for_iran_date(day: dt.date) -> list[dict]:
    # FotMob's daily endpoint expects YYYYMMDD, not YYYY-MM-DD.
    date_text = day.strftime("%Y%m%d")

    try:
        response = requests.get(
            DAILY_MATCHES_URL,
            params={"date": date_text},
            headers=HEADERS,
            timeout=40,
        )
        print(
            f"[FOTMOB] Daily matches {date_text}: "
            f"HTTP {response.status_code}"
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError(
            f"FotMob daily matches request failed for {date_text}: {error}"
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError("FotMob daily matches response is not a JSON object.")

    leagues = data.get("leagues")
    if not isinstance(leagues, list):
        raise RuntimeError(
            "FotMob daily matches response has no 'leagues' list; "
            "the response structure may have changed."
        )

    result: list[dict] = []
    seen: set[str] = set()

    for league in leagues:
        if not isinstance(league, dict):
            continue

        matches = league.get("matches")
        if not isinstance(matches, list):
            continue

        for raw in matches:
            if not isinstance(raw, dict):
                continue

            match = _normalize_match(raw, league)
            if not match:
                continue

            match_id = match["id"]
            if match_id in seen:
                continue
            seen.add(match_id)

            if dt.date.fromisoformat(match["startIran"][:10]) != day:
                continue

            result.append(match)

    result.sort(key=lambda item: item.get("start") or "")

    print(
        f"[FOTMOB] Parsed {len(result)} matches for Iran date {day.isoformat()} "
        f"from {len(leagues)} leagues."
    )
    return result

# validation trigger
