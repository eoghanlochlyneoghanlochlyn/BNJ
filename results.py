"""Previous-day results, using the same selection and poster renderer as fixtures."""
import argparse
import datetime as dt
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests

from config import IRAN_TIMEZONE
from fotmob import fetch_matches_for_iran_date, HEADERS, FOTMOB_BASE_URL, _extract_match_stage
from selector import select_fixtures
from renderer import render_fixtures
from telegram import send_photos, send_photo
from report_state import load_state, already_sent, mark_sent



def _coerce_score_pair(value):
    if isinstance(value, dict):
        h = value.get("home", value.get("homeScore"))
        a = value.get("away", value.get("awayScore"))
        try:
            if h is not None and a is not None:
                return {"home": int(h), "away": int(a)}
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return {"home": int(value[0]), "away": int(value[1])}
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        import re
        m = re.search(r"(\\d+)\\s*[-:]\\s*(\\d+)", value)
        if m:
            return {"home": int(m.group(1)), "away": int(m.group(2))}
    return None


def _shootout_marker(node):
    if isinstance(node, dict):
        for key, value in node.items():
            compact = str(value).lower().replace(" ", "").replace("_", "").replace("-", "")
            if "penaltyshootout" in compact or compact == "shootout":
                return True
            if key in ("isPenaltyShootoutEvent",) and value is True:
                return True
            if isinstance(value, (dict, list)) and _shootout_marker(value):
                return True
    elif isinstance(node, list):
        return any(_shootout_marker(x) for x in node)
    return False



def _recursive_values(node, target_keys):
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in target_keys:
                found.append(value)
            if isinstance(value, (dict, list)):
                found.extend(_recursive_values(value, target_keys))
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                found.extend(_recursive_values(value, target_keys))
    return found

def _shootout_sections(node, result=None):
    if result is None:
        result = []
    keys = ("penaltyShootout", "penalty_shootout", "shootout",
            "penaltyShootoutEvents", "penalty_shootout_events")
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and isinstance(value, (dict, list)):
                result.append(value)
                _shootout_sections(value, result)
            elif isinstance(value, (dict, list)):
                _shootout_sections(value, result)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                _shootout_sections(value, result)
    return result


def _event_lists(node):
    result = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("events", "list") and isinstance(value, list):
                result.append(value)
            elif isinstance(value, (dict, list)):
                result.extend(_event_lists(value))
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                result.extend(_event_lists(value))
    return result


def _shootout_score(details):
    content = details.get("content") or {}
    if not isinstance(content, dict):
        return None

    for key in ("penaltyScore", "penalty_score", "shootoutScore", "shootout_score"):
        if key in content:
            result = _coerce_score_pair(content.get(key))
            if result:
                return result

    # FotMob can place the shootout score several levels below content,
    # so search the entire payload for explicit score fields before
    # counting individual shootout kicks.
    for node in (details, content):
        for key in ("penaltyScore", "penalty_score", "shootoutScore", "shootout_score"):
            for value in _recursive_values(node, {key}):
                result = _coerce_score_pair(value)
                if result:
                    return result

    sections = _shootout_sections(content)
    facts = content.get("matchFacts")
    if isinstance(facts, dict):
        sections.extend(_shootout_sections(facts))

    for section in sections:
        for key in ("penaltyScore", "penalty_score", "shootoutScore", "shootout_score"):
            if isinstance(section, dict) and key in section:
                result = _coerce_score_pair(section.get(key))
                if result:
                    return result
        if isinstance(section, dict) and isinstance(section.get("penalties"), dict):
            result = _coerce_score_pair(section["penalties"])
            if result:
                return result

    header = details.get("header") or {}
    teams = header.get("teams") or {}
    if not isinstance(teams, dict):
        teams = {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    home_id = home.get("id")
    away_id = away.get("id")

    seen = set()
    hs = 0
    aws = 0
    found = False

    def fingerprint(event):
        keys = ("teamId", "isHome", "playerId", "playerName", "minute", "time",
                "period", "isScored", "scored", "converted", "successful",
                "success", "description", "eventType", "incidentType")
        return tuple((key, json.dumps(event.get(key), ensure_ascii=False, sort_keys=True, default=str)
                      if isinstance(event.get(key), (dict, list)) else str(event.get(key)))
                     for key in keys)

    for events in _event_lists(sections):
        for event in events:
            if not isinstance(event, dict):
                continue
            marker = str(event.get("type") or event.get("eventType") or event.get("incidentType") or "").lower()
            if not (event.get("isPenaltyShootoutEvent") is True or "penaltyshootout" in marker or marker == "shootout"):
                continue
            key = fingerprint(event)
            if key in seen:
                continue
            seen.add(key)
            found = True

            scored = None
            for field in ("isGoal", "isScored", "scored", "converted", "success", "successful"):
                if isinstance(event.get(field), bool):
                    scored = event[field]
                    break
            text = " ".join(str(event.get(k, "")) for k in
                            ("type", "eventType", "incidentType", "incidentClass", "description", "reason")).lower()
            if any(word in text for word in ("miss", "saved", "save", "off target", "woodwork")):
                scored = False
            if scored is False:
                continue
            if scored is None:
                scored = True
            if not scored:
                continue

            team_id = event.get("teamId")
            is_home = event.get("isHome")
            if team_id is not None:
                if str(team_id) == str(home_id):
                    is_home = True
                elif str(team_id) == str(away_id):
                    is_home = False
            if is_home is True:
                hs += 1
            elif is_home is False:
                aws += 1

    if found and (hs or aws):
        return {"home": hs, "away": aws}
    return None


def number(value):
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def score_for(match):
    response = requests.get(
        FOTMOB_BASE_URL + "/api/data/matchDetails",
        params={"matchId": match["id"]}, headers=HEADERS, timeout=30)
    response.raise_for_status()
    details = response.json()
    header = details.get("header") or {}
    status = header.get("status") or {}
    if not isinstance(status, dict):
        status = {}
    teams = header.get("teams") or details.get("teams") or {}
    if isinstance(teams, list):
        teams = {"home": teams[0] if len(teams) > 0 else {}, "away": teams[1] if len(teams) > 1 else {}}
    if not isinstance(teams, dict):
        teams = {}
    home = teams.get("home") or header.get("homeTeam") or {}
    away = teams.get("away") or header.get("awayTeam") or {}
    if not isinstance(home, dict): home = {}
    if not isinstance(away, dict): away = {}
    daily_status = match.get("rawStatus") or {}
    finished = status.get("finished") or status.get("isFinished") or daily_status.get("finished")
    if not finished:
        raise RuntimeError("Match not confirmed finished: " + match["id"])
    daily_home = match.get("rawHome") or {}
    daily_away = match.get("rawAway") or {}
    h = number(home.get("score"))
    a = number(away.get("score"))
    if h is None: h = number(daily_home.get("score"))
    if a is None: a = number(daily_away.get("score"))
    if h is None or a is None:
        raise RuntimeError("Final score missing: " + match["id"])
    label = f"{h} - {a}"
    # FotMob's header normally stores the score before the shootout.
    # Shootout kicks are represented in matchFacts events with
    # isPenaltyShootoutEvent=True; count only successful shootout goals.
    penalty_score = _shootout_score(details)
    if penalty_score is not None:
        label = f"{h} ({penalty_score['home']}-{penalty_score['away']}) {a}"

    match["resultLabel"] = label.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    stage = _extract_match_stage(details)
    if stage: match["stage"] = stage
    print("[RESULT]", match["id"], match["resultLabel"])
    return match


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Previous calendar date in Iran")
    parser.add_argument("--output", default="output/results.png")
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()
    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(IRAN_TIMEZONE).date() - dt.timedelta(days=1)
    # Calendar-day results (00:00–24:00 Iran), ready for the 08:00 report.
    candidates = fetch_matches_for_iran_date(day - dt.timedelta(days=1))
    candidates += fetch_matches_for_iran_date(day)
    candidates = [m for m in candidates if dt.datetime.fromisoformat(m["startIran"]).date() == day]
    selected = select_fixtures(candidates)
    if not selected:
        raise RuntimeError("No qualifying matches; refusing blank results poster.")
    with ThreadPoolExecutor(max_workers=6) as pool:
        selected = list(pool.map(score_for, selected))
    output = Path(args.output)
    render_fixtures(selected, day, output)
    paths = [output]
    index = 2
    while output.with_name(f"{output.stem}-{index}{output.suffix}").exists():
        paths.append(output.with_name(f"{output.stem}-{index}{output.suffix}"))
        index += 1
    if args.send_telegram:
        state = load_state()
        key = "results:" + day.isoformat()
        if not already_sent(state, key):
            caption = "🏁 نتایج روز قبل | " + day.isoformat()
            if len(paths) == 1:
                send_photo(paths[0], caption)
            else:
                send_photos(paths, caption)
            mark_sent(state, key)
    print("Generated", len(paths), "results page(s)")


if __name__ == "__main__":
    main()
