"""Explicit historical result-poster test; does not change daily match selection."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests

from fotmob import FOTMOB_BASE_URL, HEADERS, _parse_utc, _normalize_match
from results import score_for
from renderer import render_fixtures, _result_label_for_rtl
from telegram import send_photo, send_photos


MATCH_IDS = [
    "4653849",
    "5795461",
    "4934510",
    "4685769",
    "4935324",
    "5034193",
    # Added historical test matches:
    "5186384",  # Chelsea vs Wrexham
    "5034192",  # Arsenal vs Crystal Palace
    "5793186",  # Manchester City vs Arsenal
    "5038956",  # Darmstadt vs Freiburg
    "5801099",  # Borussia Dortmund vs Bayern Munich
]


def load_match(match_id):
    response = requests.get(
        FOTMOB_BASE_URL + "/api/data/matchDetails",
        params={"matchId": match_id}, headers=HEADERS, timeout=35)
    response.raise_for_status()
    details = response.json()
    header = details.get("header") or {}
    general = details.get("general") or {}
    teams = header.get("teams") or details.get("teams") or {}
    if isinstance(teams, list):
        teams = {"home": teams[0] if len(teams) > 0 else {},
                 "away": teams[1] if len(teams) > 1 else {}}
    home = teams.get("home") or header.get("homeTeam") or {}
    away = teams.get("away") or header.get("awayTeam") or {}
    status = header.get("status") or {}
    league = header.get("league") or {}
    if not isinstance(league, dict):
        league = {}
    league_id = general.get("leagueId") or league.get("id") or general.get("parentLeagueId")
    league_name = general.get("leagueName") or league.get("name") or "سایر مسابقات"
    utc_time = status.get("utcTime") or general.get("matchTimeUTC") or general.get("matchTimeUtc")
    if not utc_time:
        raise RuntimeError(f"Match {match_id}: no kickoff UTC time")
    raw = {"id": match_id, "home": home, "away": away,
           "status": dict(status, utcTime=utc_time)}
    match = _normalize_match(raw, {"id": league_id, "name": league_name})
    if not match:
        raise RuntimeError(f"Match {match_id}: could not normalize match details")
    match["competitionName"] = league_name
    return score_for(match)


def assert_score_ordering():
    cases = [
        ("۳ - ۱", "۱ - ۳"),
        ("1 - 0", "0 - 1"),
        ("۱ (۳-۲) ۱", "۱ (۲-۳) ۱"),
        ("1 (4-3) 1", "1 (3-4) 1"),
    ]
    for raw, expected in cases:
        actual = _result_label_for_rtl({"resultLabel": raw})
        if actual != expected:
            raise AssertionError(
                f"Score reversal failed: {raw!r} -> {actual!r}, expected {expected!r}"
            )


def main():
    assert_score_ordering()
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()

    with ThreadPoolExecutor(max_workers=11) as pool:
        matches = list(pool.map(load_match, MATCH_IDS))

    if len(matches) != len(MATCH_IDS):
        raise RuntimeError("Incomplete test match list")

    matches.sort(key=lambda m: m["startIran"])
    output = Path("output/results-test.png")

    # This is a multi-date historical test, so the poster date is labeled as test.
    from datetime import date
    render_fixtures(matches, date.today(), output)

    paths = [output]
    index = 2
    while output.with_name(f"{output.stem}-{index}{output.suffix}").exists():
        paths.append(output.with_name(f"{output.stem}-{index}{output.suffix}"))
        index += 1

    if args.send_telegram:
        caption = "🏁 تست نتایج ۱۱ مسابقه تاریخی"
        if len(paths) == 1:
            send_photo(paths[0], caption)
        else:
            send_photos(paths, caption)

    print("Test completed:", len(matches), "matches;", len(paths), "poster pages")


if __name__ == "__main__":
    main()
