"""Generate a poster for two explicitly chosen FotMob matches without sending it."""
import datetime as dt
from pathlib import Path
import requests
from fotmob import DAILY_MATCHES_URL, HEADERS, _normalize_match, enrich_match_stages
from renderer import render_fixtures

MATCHES = [("6315013", "2026-09-28"), ("5795472", "2026-10-11")]

def get_match(match_id, date):
    day = dt.date.fromisoformat(date)
    for offset in (-1, 0, 1):
        date_arg = (day + dt.timedelta(days=offset)).strftime("%Y%m%d")
        response = requests.get(DAILY_MATCHES_URL, params={"date": date_arg}, headers=HEADERS, timeout=40)
        response.raise_for_status()
        for league in response.json()["leagues"]:
            for raw in league.get("matches", []):
                if str(raw.get("id") or raw.get("matchId")) == match_id:
                    match = _normalize_match(raw, league)
                    if match:
                        return match
    raise RuntimeError("FotMob match not found: " + match_id)

if __name__ == "__main__":
    matches = [get_match(match_id, date) for match_id, date in MATCHES]
    enrich_match_stages(matches)
    for match in matches:
        print(match["id"], match["competitionName"], match["startIran"], match.get("stage"))
    render_fixtures(matches, dt.date.today(), Path("output/test-fixtures.png"))
    print("Preview generated. No Telegram send or state changes.")
