from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from config import IRAN_TIMEZONE
from fotmob import fetch_matches_for_iran_date
from renderer import render_fixtures
from report_state import already_sent, load_state, mark_sent
from selector import select_fixtures
from telegram import send_photo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--output", default="output/fixtures.png")
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()

    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(IRAN_TIMEZONE).date()
    matches = fetch_matches_for_iran_date(day)
    selected = select_fixtures(matches)

    print(f"Date (Iran): {day.isoformat()}")
    print(f"Fetched matches: {len(matches)}")
    print(f"Selected fixtures: {len(selected)}")

    output = Path(args.output)
    render_fixtures(selected, day, output)
    print(f"Image written to {output}")

    if args.send_telegram:
        state = load_state()
        key = f"fixtures:{day.isoformat()}"
        if already_sent(state, key):
            print(f"Telegram report already sent: {key}")
            return

        caption = f"📅 مسابقات امروز | {day.isoformat()}"
        send_photo(output, caption)
        mark_sent(state, key)
        print("Telegram report sent successfully.")


if __name__ == "__main__":
    main()
