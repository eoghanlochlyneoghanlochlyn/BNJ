"""Previous-day results, using the same selection and poster renderer as fixtures."""
import argparse
import datetime as dt
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests

from config import IRAN_TIMEZONE
from fotmob import fetch_matches_for_iran_date, HEADERS, FOTMOB_BASE_URL, _extract_match_stage
from selector import select_fixtures
from renderer import render_fixtures
from telegram import send_photos, send_photo
from report_state import load_state, already_sent, mark_sent


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
    penalty = status.get("penalties") or status.get("penaltyScore") or {}
    if not isinstance(penalty, dict): penalty = {}
    ph = number(home.get("penaltyScore"))
    pa = number(away.get("penaltyScore"))
    if ph is None: ph = number(penalty.get("home"))
    if ph is None: ph = number(home.get("penalties"))
    if pa is None: pa = number(penalty.get("away"))
    if pa is None: pa = number(away.get("penalties"))
    if ph is not None and pa is not None:
        label += f" ({ph} - {pa})"
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
