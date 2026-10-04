from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from config import COMPETITION_IDS, IRAN_TIMEZONE
from fotmob import fetch_matches_for_iran_date
from report_state import load_state, save_state, mark_report_sent
from publisher import (
    current_knockout_stage,
    knockout_fingerprint,
    knockout_stage_status,
    table_fingerprint,
    _stage_key as publisher_stage_key,
    register_if_changed,
)
from standings import all_groups_complete, fetch_standings, has_knockout, is_grouped_standings
from standings_renderer import render_group_standings, render_knockout_standings, render_standings
from telegram import send_photo


def _match_date(match: dict) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(match["startIran"]).date()
    except (KeyError, TypeError, ValueError):
        return None


def _finished(match: dict) -> bool:
    status = match.get("rawStatus") or {}
    if not isinstance(status, dict):
        status = {}
    for key in ("finished", "isFinished", "completed"):
        if status.get(key) is True:
            return True
    text = str(
        status.get("reason")
        or status.get("name")
        or status.get("shortName")
        or status.get("type")
        or ""
    ).casefold()
    return text in {
        "ft",
        "aet",
        "pen",
        "finished",
        "full time",
        "after penalties",
        "after extra time",
    }


def _todays_matches(day: dt.date) -> list[dict]:
    matches = fetch_matches_for_iran_date(day - dt.timedelta(days=1))
    matches += fetch_matches_for_iran_date(day)
    unique = {}
    for match in matches:
        if _match_date(match) == day:
            unique[str(match["id"])] = match
    return list(unique.values())


def _competition_matches(matches: list[dict], competition_id: str) -> list[dict]:
    result = []
    for match in matches:
        ids = {str(x) for x in (match.get("competitionIds") or [])}
        if str(match.get("leagueId") or "") in ids or str(competition_id) in ids:
            result.append(match)
    return result


def _send_grouped_tables(
    state: dict,
    data: dict,
    competition_id: str,
    output_dir: Path,
) -> int:
    sent = 0
    season = str(data.get("season") or "فصل جاری")
    tables = data.get("tables") or []

    for index, table in enumerate(tables, start=1):
        group = str(table.get("group") or f"Group {index}")
        key = f"table:{competition_id}:{season}:{group}"
        fingerprint = table_fingerprint(table)
        if not register_if_changed(
            state,
            key=key,
            fingerprint=fingerprint,
            report_type="standings",
            competition_id=competition_id,
            season=season,
            stage=group,
        ):
            continue

        safe = "".join(ch if ch.isalnum() else "_" for ch in group).strip("_")
        output = output_dir / f"{competition_id}_{index}_{safe}.png"
        render_group_standings(data, table, dt.date.today(), output)
        send_photo(output, f"📊 جدول {data.get('competitionName') or competition_id} | {group}")
        mark_report_sent(
            state, key, fingerprint,
            report_type="standings",
            competition_id=competition_id,
            season=season,
            stage=group,
            stage_status="completed",
        )
        sent += 1

    return sent


def _send_overall_table(
    state: dict,
    data: dict,
    competition_id: str,
    output_dir: Path,
) -> int:
    if is_grouped_standings(data):
        if not all_groups_complete(data):
            return 0
        key_suffix = "ALL_GROUPS_FINAL"
    else:
        key_suffix = "OVERALL"

    table_payload = {
        "tables": data.get("tables") or [],
        "competitionId": competition_id,
        "season": data.get("season") or "",
    }
    fingerprint = table_fingerprint({
        "group": key_suffix,
        "rows": [
            row
            for table in table_payload["tables"]
            for row in table.get("rows") or []
        ],
    })
    key = f"table:{competition_id}:{table_payload['season']}:{key_suffix}"
    if not register_if_changed(
        state,
        key=key,
        fingerprint=fingerprint,
        report_type="standings",
        competition_id=competition_id,
        season=str(table_payload["season"]),
        stage=key_suffix,
        stage_status="completed",
    ):
        return 0

    output = output_dir / f"{competition_id}_TABLE_FINAL.png"
    render_standings(data, dt.date.today(), output)
    send_photo(output, f"📊 جدول {data.get('competitionName') or competition_id}")
    mark_report_sent(
        state, key, fingerprint,
        report_type="standings",
        competition_id=competition_id,
        season=str(table_payload["season"]),
        stage=key_suffix,
        stage_status="completed",
    )
    return 1


def _send_knockout(
    state: dict,
    data: dict,
    competition_id: str,
    output_dir: Path,
) -> int:
    rounds = data.get("knockoutRounds") or []
    stage = current_knockout_stage(rounds)
    if not stage:
        return 0

    status = knockout_stage_status(stage)
    if status == "not_ready":
        return 0

    label = str(stage.get("stage") or "مرحله حذفی")
    season = str(data.get("season") or "فصل جاری")

    # Stage + status are deliberately separate identities. This means
    # teams_known, in_progress and completed can each be published once,
    # while unchanged data inside one status is suppressed.
    key = f"knockout:{competition_id}:{season}:{label}:{status}"
    fingerprint = knockout_fingerprint(data, stage, status)

    if not register_if_changed(
        state,
        key=key,
        fingerprint=fingerprint,
        report_type="knockout",
        competition_id=competition_id,
        season=season,
        stage=label,
        stage_status=status,
    ):
        return 0

    safe = "".join(ch if ch.isalnum() else "_" for ch in label).strip("_")
    output = output_dir / f"{competition_id}_KNOCKOUT_{safe}_{status}.png"
    render_knockout_standings(data, dt.date.today(), output, stage=stage)
    send_photo(
        output,
        f"🌳 نمودار {data.get('competitionName') or competition_id} | {label}",
    )
    mark_report_sent(
        state, key, fingerprint,
        report_type="knockout",
        competition_id=competition_id,
        season=season,
        stage=label,
        stage_status=status,
    )
    return 1


def publish(day: dt.date) -> int:
    matches = _todays_matches(day)
    if not matches:
        print(f"[PUBLISH] No matches on {day.isoformat()}; nothing to publish.")
        return 0

    candidates = sorted({
        str(cid)
        for match in matches
        for cid in (match.get("competitionIds") or [match.get("leagueId")])
        if str(cid) in COMPETITION_IDS
    })
    state = load_state()
    sent = 0

    for competition_id in candidates:
        day_matches = _competition_matches(matches, competition_id)
        if not day_matches:
            continue

        data = fetch_standings(competition_id)
        output_dir = Path("output/standings") / competition_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Tables are published only after every selected match of this
        # competition on the Iran calendar day is finished.
        if all(_finished(match) for match in day_matches):
            if data.get("tables"):
                if is_grouped_standings(data):
                    sent += _send_grouped_tables(state, data, competition_id, output_dir)
                    sent += _send_overall_table(state, data, competition_id, output_dir)
                else:
                    sent += _send_overall_table(state, data, competition_id, output_dir)

        if has_knockout(data):
            sent += _send_knockout(state, data, competition_id, output_dir)

        save_state(state)

    print(f"[PUBLISH] Sent {sent} standings/knockout report(s).")
    return sent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    args = parser.parse_args()
    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(IRAN_TIMEZONE).date()
    publish(day)


if __name__ == "__main__":
    main()
