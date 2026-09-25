from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from config import IRAN_TIMEZONE
from fotmob import fetch_matches_for_iran_date
from renderer import render_fixtures
from selector import select_fixtures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--output", default="output/fixtures.png")
    args = parser.parse_args()

    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(IRAN_TIMEZONE).date()
    matches = fetch_matches_for_iran_date(day)
    selected = select_fixtures(matches)

    print(f"Date (Iran): {day.isoformat()}")
    print(f"Fetched matches: {len(matches)}")
    print(f"Selected fixtures: {len(selected)}")
    for match in selected:
        print(f'{match["id"]} | {match["competition"]} | {match["home"]} - {match["away"]} | {match.get("startIran", "")}')

    render_fixtures(selected, day, Path(args.output))
    print(f"Image written to {args.output}")


if __name__ == "__main__":
    main()
