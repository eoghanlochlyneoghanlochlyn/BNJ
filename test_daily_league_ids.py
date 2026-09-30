from __future__ import annotations

import requests

from fotmob import DAILY_MATCHES_URL, HEADERS


TARGETS = {
    ("czechia", "england"),
    ("spain", "croatia"),
    ("finland", "belarus"),
    ("san marino", "albania"),
    ("slovakia", "kazakhstan"),
    ("scotland", "switzerland"),
    ("slovenia", "north macedonia"),
}


def norm(value):
    return " ".join(str(value or "").lower().split())


def names(obj):
    if not isinstance(obj, dict):
        return ""
    return norm(
        obj.get("longName")
        or obj.get("name")
        or obj.get("shortName")
        or obj.get("teamName")
    )


def main():
    for date_text in ("20260929", "20260930"):
        print(f"\\n===== DAILY {date_text} =====")
        r = requests.get(
            DAILY_MATCHES_URL,
            params={"date": date_text},
            headers=HEADERS,
            timeout=40,
        )
        print("HTTP:", r.status_code)
        r.raise_for_status()
        data = r.json()
        leagues = data.get("leagues") or []
        print("league_count:", len(leagues))

        found = 0
        for league in leagues:
            if not isinstance(league, dict):
                continue
            for raw in league.get("matches") or []:
                if not isinstance(raw, dict):
                    continue

                home = raw.get("home") or raw.get("homeTeam") or {}
                away = raw.get("away") or raw.get("awayTeam") or {}
                pair = (names(home), names(away))
                reverse_pair = (pair[1], pair[0])

                league_name = (
                    league.get("name")
                    or league.get("title")
                    or league.get("shortName")
                    or ""
                )
                league_blob = norm(league_name)
                is_nations = "nations" in league_blob
                is_target = pair in TARGETS or reverse_pair in TARGETS

                if not (is_nations or is_target):
                    continue

                found += 1
                print("\n--- MATCH ---")
                print("id:", raw.get("id") or raw.get("matchId"))
                print("teams:", home.get("name") or home.get("longName"), "vs", away.get("name") or away.get("longName"))
                print("league.name:", league.get("name"))
                print("league.title:", league.get("title"))
                print("league.shortName:", league.get("shortName"))
                print("league.id:", league.get("id"))
                print("league.leagueId:", league.get("leagueId"))
                print("league.competitionId:", league.get("competitionId"))
                print("league.primaryId:", league.get("primaryId"))
                print("raw.leagueId:", raw.get("leagueId"))
                print("raw.competitionId:", raw.get("competitionId"))
                print("raw.tournamentId:", raw.get("tournamentId"))
                print("raw keys:", sorted(raw.keys()))
                print("league keys:", sorted(league.keys()))

        print("\nFOUND:", found)
        if found == 0:
            raise AssertionError(f"No Nations League/target matches found in daily response {date_text}")


if __name__ == "__main__":
    main()
