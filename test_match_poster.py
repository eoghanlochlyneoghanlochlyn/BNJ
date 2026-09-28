"""Generate and send a poster for two explicitly chosen FotMob matches."""
import datetime as dt
from pathlib import Path

import requests

from fotmob import DAILY_MATCHES_URL, HEADERS, _normalize_match, enrich_match_stages
from renderer import render_fixtures
from telegram import send_photo


MATCHES = [
    ("6315013", "2026-09-28"),
    ("5795472", "2026-10-11"),
    ("6106414", "2026-10-01"),
    ("6112251", "2026-10-01"),
    ("6112421", "2026-10-02"),
    ("5868089", "2026-10-04"),
    ("5749694", "2026-10-04"),
    ("5802952", "2026-10-04"),
    ("5881180", "2026-10-04"),
]


def get_match(match_id: str, date: str):
    day = dt.date.fromisoformat(date)

    for offset in (-1, 0, 1):
        date_arg = (day + dt.timedelta(days=offset)).strftime("%Y%m%d")

        response = requests.get(
            DAILY_MATCHES_URL,
            params={"date": date_arg},
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()

        data = response.json()

        for league in data.get("leagues", []):
            for raw in league.get("matches", []):
                raw_id = raw.get("id") or raw.get("matchId")

                if str(raw_id) != match_id:
                    continue

                match = _normalize_match(raw, league)

                if match:
                    return match

    raise RuntimeError(f"FotMob match not found: {match_id}")


def main():
    matches = [
        get_match(match_id, date)
        for match_id, date in MATCHES
    ]

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

    render_fixtures(
        matches,
        dt.date.today(),
        output_path,
    )

    print(f"Poster generated: {output_path}")

    send_photo(
        output_path,
        "🧪 تست پوستر BNJ — مسابقات انتخابی",
    )

    print("Poster sent to Telegram.")
    print("Daily report state was not modified.")


if __name__ == "__main__":
    main()
