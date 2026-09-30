from __future__ import annotations

import argparse
import json
from typing import Any

import requests

from config import COMPETITION_IDS, MAJOR_LEAGUE_IDS
from fotmob import FOTMOB_BASE_URL, HEADERS
from pathlib import Path

from standings import (
    _extract_competition,
    _extract_knockout,
    _extract_season,
    _extract_tables,
    has_knockout,
)
from standings_renderer import render_knockout_standings


BRACKET_OUTPUT_DIR = Path("output/real_competitions")


DEFAULT_COMPETITIONS = {
    "47": "Premier League",
    "42": "Champions League",
    "77": "World Cup",
    "50": "European Championship",
    "9806": "Nations League A",
}


def _fetch_league(competition_id: str) -> dict:
    response = requests.get(
        f"{FOTMOB_BASE_URL}/api/data/leagues",
        params={"id": competition_id},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected response for competition {competition_id}")
    return payload


def _team_names(table: dict) -> list[str]:
    names = []
    for row in table.get("rows") or []:
        name = str(row.get("teamName") or "").strip()
        if name:
            names.append(name)
    return names


def _print_tables(tables: list[dict]) -> None:
    print(f"  Tables: {len(tables)}")
    if not tables:
        print("    - none")
        return

    for index, table in enumerate(tables, start=1):
        group = str(table.get("group") or "").strip() or "(no group)"
        rows = table.get("rows") or []
        print(f"    [{index}] {group}: {len(rows)} teams")
        names = _team_names(table)
        if names:
            preview = ", ".join(names[:6])
            if len(names) > 6:
                preview += ", ..."
            print(f"        Teams: {preview}")


def _print_knockout(rounds: list[dict]) -> None:
    print(f"  Knockout rounds: {len(rounds)}")
    if not rounds:
        print("    - none")
        return

    for index, round_data in enumerate(rounds, start=1):
        stage = str(round_data.get("stage") or "(unknown)")
        matchups = round_data.get("matchups") or []
        print(f"    [{index}] {stage}: {len(matchups)} matchups")

        for matchup_index, matchup in enumerate(matchups, start=1):
            home = str(matchup.get("homeTeam") or "TBD")
            away = str(matchup.get("awayTeam") or "TBD")
            score = ""
            if matchup.get("homeScore") is not None and matchup.get("awayScore") is not None:
                score = f" {matchup['homeScore']}-{matchup['awayScore']}"

            aggregate = matchup.get("aggregatedResult") or {}
            aggregate_text = ""
            if aggregate.get("homeScore") is not None and aggregate.get("awayScore") is not None:
                aggregate_text = f" | agg {aggregate['homeScore']}-{aggregate['awayScore']}"

            penalty = matchup.get("penaltyScore")
            penalty_text = ""
            if isinstance(penalty, dict) and penalty.get("home") is not None and penalty.get("away") is not None:
                penalty_text = f" | pens {penalty['home']}-{penalty['away']}"

            print(
                f"        M{matchup_index}: {home} vs {away}"
                f"{score}{aggregate_text}{penalty_text}"
            )



def _render_real_bracket(competition_id: str, competition_name: str, season: str, rounds: list[dict]) -> None:
    BRACKET_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "competitionId": str(competition_id),
        "competitionName": competition_name,
        "season": season,
        "knockoutRounds": rounds,
    }
    output = BRACKET_OUTPUT_DIR / f"{competition_id}_knockout.png"
    render_knockout_standings(data, None, output)

    if not output.exists() or output.stat().st_size < 1000:
        raise RuntimeError(f"Invalid bracket image: {output}")

    from PIL import Image

    with Image.open(output) as image:
        if image.width != 1600:
            raise RuntimeError(
                f"Unexpected bracket width for {competition_id}: {image.width}"
            )
        if image.height < 1500:
            raise RuntimeError(
                f"Bracket image is suspiciously short for {competition_id}: {image.height}"
            )

    print(f"  Rendered bracket: {output} ({output.stat().st_size} bytes)")

def inspect_competition(competition_id: str, dump_raw: bool = False) -> None:
    print("=" * 88)
    print(f"COMPETITION ID: {competition_id}")
    print(f"Configured: {competition_id in (COMPETITION_IDS | MAJOR_LEAGUE_IDS)}")

    payload = _fetch_league(competition_id)
    cid, name = _extract_competition(payload, competition_id)
    season = _extract_season(payload)
    tables = _extract_tables(payload)
    rounds = _extract_knockout(payload)

    details = payload.get("details")
    if isinstance(details, dict):
        print(f"FotMob details ID: {details.get('id', '')}")
        print(f"FotMob name: {details.get('name') or details.get('shortName') or ''}")

    print(f"Normalized competition ID: {cid}")
    print(f"Normalized competition name: {name or '(not found)'}")
    print(f"Season: {season or '(not found)'}")
    print(f"Payload keys: {', '.join(sorted(payload.keys()))}")

    _print_tables(tables)
    print(f"  has_knockout: {has_knockout({'knockoutRounds': rounds})}")
    _print_knockout(rounds)

    if rounds:
        _render_real_bracket(
            str(competition_id),
            name or str(competition_id),
            season or "unknown",
            rounds,
        )

    if dump_raw:
        print("  RAW JSON:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect real FotMob competition payloads for tables and knockout brackets."
    )
    parser.add_argument(
        "--competitions",
        nargs="+",
        default=list(DEFAULT_COMPETITIONS),
        help="Numeric FotMob competition IDs.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the complete raw FotMob JSON for each competition.",
    )
    args = parser.parse_args()

    for competition_id in args.competitions:
        try:
            inspect_competition(str(competition_id), args.raw)
        except requests.HTTPError as exc:
            print(f"HTTP ERROR for {competition_id}: {exc}")
        except Exception as exc:
            print(f"ERROR for {competition_id}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
