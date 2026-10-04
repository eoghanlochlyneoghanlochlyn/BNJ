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
    """Fetch matches from yesterday and today.

    Yesterday is intentionally included because a match can start before
    midnight in Iran and finish after midnight. The caller uses persisted
    pending-match state to distinguish those carry-over matches from ordinary
    completed matches from yesterday.
    """
    matches = fetch_matches_for_iran_date(day - dt.timedelta(days=1))
    matches += fetch_matches_for_iran_date(day)
    unique = {}
    for match in matches:
        match_date = _match_date(match)
        if match_date in {day - dt.timedelta(days=1), day}:
            unique[str(match["id"])] = match
    return list(unique.values())


def _pending_match_competitions(
    state: dict,
    previous_matches: list[dict],
) -> tuple[set[str], dict[str, dict]]:
    """Return competitions whose previously unfinished matches have now ended.

    The pending map is persisted between scheduled runs. This lets a 23:00
    match that finishes at 01:00 trigger publication on the next day's run.
    """
    previous_pending = state.get("_pending_matches")
    if not isinstance(previous_pending, dict):
        previous_pending = {}

    carryover_competitions: set[str] = set()
    next_pending: dict[str, dict] = {}

    for match in previous_matches:
        match_id = str(match.get("id") or "")
        if not match_id:
            continue

        competition_ids = {
            str(x)
            for x in (match.get("competitionIds") or [])
            if str(x) in COMPETITION_IDS
        }
        league_id = str(match.get("leagueId") or "")
        if league_id in COMPETITION_IDS:
            competition_ids.add(league_id)
        if not competition_ids:
            continue

        if _finished(match):
            if match_id in previous_pending:
                carryover_competitions.update(competition_ids)
        else:
            next_pending[match_id] = {
                "competition_ids": sorted(competition_ids),
                "start_date": _match_date(match).isoformat()
                if _match_date(match)
                else None,
            }

    return carryover_competitions, next_pending


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


def _send_knockout_stage(
    state: dict,
    data: dict,
    competition_id: str,
    output_dir: Path,
    stage: dict,
) -> int:
    status = knockout_stage_status(stage)
    if status == "not_ready":
        return 0

    label = str(stage.get("stage") or "مرحله حذفی")
    season = str(data.get("season") or "فصل جاری")

    # Stage + status are deliberately separate identities. A stage can move
    # through teams_known -> in_progress -> completed, and each meaningful
    # state is published at most once.
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


def _send_knockout(
    state: dict,
    data: dict,
    competition_id: str,
    output_dir: Path,
) -> int:
    stage = current_knockout_stage(data.get("knockoutRounds") or [])
    if not stage:
        return 0
    return _send_knockout_stage(state, data, competition_id, output_dir, stage)


def _send_all_ready_knockout_stages(
    state: dict,
    data: dict,
    competition_id: str,
    output_dir: Path,
) -> int:
    """Manual competition inspection: publish every stage whose teams are known.

    Future stages are intentionally allowed here. This is different from the
    automatic publisher, which only publishes the current active stage.
    Stages with unknown/TBD participants are skipped.
    """
    rounds = data.get("knockoutRounds") or []
    ordered = sorted(
        [r for r in rounds if isinstance(r, dict)],
        key=publisher_stage_key,
    )
    sent = 0
    for stage in ordered:
        sent += _send_knockout_stage(
            state, data, competition_id, output_dir, stage
        )
    return sent


def publish(day: dt.date, competition_id: str | None = None) -> int:
    # Explicit competition mode is for a manual/full snapshot. It does not
    # depend on today's matches and may inspect future knockout stages whose
    # participants are already known.
    if competition_id:
        competition_id = str(competition_id)
        state = load_state()
        data = fetch_standings(competition_id)
        output_dir = Path("output/standings") / competition_id
        output_dir.mkdir(parents=True, exist_ok=True)

        sent = 0
        if data.get("tables"):
            if is_grouped_standings(data):
                sent += _send_grouped_tables(state, data, competition_id, output_dir)
                sent += _send_overall_table(state, data, competition_id, output_dir)
            else:
                sent += _send_overall_table(state, data, competition_id, output_dir)

        if has_knockout(data):
            sent += _send_all_ready_knockout_stages(
                state, data, competition_id, output_dir
            )

        save_state(state)
        print(
            f"[PUBLISH] Manual competition {competition_id}: "
            f"sent {sent} report(s)."
        )
        return sent

    matches = _todays_matches(day)
    state = load_state()

    previous_matches = [
        match for match in matches
        if _match_date(match) == day - dt.timedelta(days=1)
    ]
    today_matches = [
        match for match in matches
        if _match_date(match) == day
    ]

    carryover_competitions, next_pending = _pending_match_competitions(
        state, previous_matches
    )
    state["_pending_matches"] = next_pending

    today_competitions = {
        str(cid)
        for match in today_matches
        for cid in (match.get("competitionIds") or [match.get("leagueId")])
        if str(cid) in COMPETITION_IDS
    }
    candidates = sorted(today_competitions | carryover_competitions)

    if not candidates:
        save_state(state)
        print(f"[PUBLISH] No relevant matches on {day.isoformat()}; nothing to publish.")
        return 0

    sent = 0

    for competition_id in candidates:
        day_matches = _competition_matches(today_matches, competition_id)
        carryover = competition_id in carryover_competitions

        # A normal table publication waits for today's match day to finish.
        # A carry-over match from yesterday is independently eligible as soon
        # as that previously unfinished match is confirmed finished.
        today_complete = bool(day_matches) and all(
            _finished(match) for match in day_matches
        )
        if not today_complete and not carryover:
            continue

        data = fetch_standings(competition_id)
        output_dir = Path("output/standings") / competition_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Tables are published after today's competition matches finish,
        # or immediately when a previously unfinished match from yesterday
        # has now finished after crossing midnight.
        if today_complete or carryover:
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
    parser.add_argument(
        "--competition-id",
        help="Manually publish all currently known tables and knockout stages for one competition.",
    )
    args = parser.parse_args()
    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(IRAN_TIMEZONE).date()
    publish(day, competition_id=args.competition_id)


if __name__ == "__main__":
    main()
