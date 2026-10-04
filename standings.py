from __future__ import annotations

import argparse
import datetime as dt
import re
from typing import Any

import requests

from config import IRAN_TIMEZONE, MAJOR_LEAGUE_IDS
from fotmob import FOTMOB_BASE_URL, HEADERS


LEAGUE_URL = f"{FOTMOB_BASE_URL}/api/data/leagues"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split()).strip()


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_dict(*values: Any) -> dict:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _find_table_nodes(node: Any) -> list[dict]:
    """Find FotMob table containers without assuming one exact response shape."""
    found: list[dict] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            table = value.get("table")
            if isinstance(table, dict):
                all_rows = table.get("all")
                if isinstance(all_rows, list) and all_rows:
                    found.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(node)

    unique: list[dict] = []
    seen: set[int] = set()
    for item in found:
        marker = id(item)
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique


def _normalize_rows(table: dict) -> list[dict]:
    rows = table.get("all")
    if not isinstance(rows, list):
        return []

    result: list[dict] = []
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            continue

        scores = _clean(raw.get("scoresStr") or raw.get("scoreStr"))
        gf = ga = None
        if "-" in scores:
            left, right = scores.split("-", 1)
            gf, ga = _as_int(left.strip()), _as_int(right.strip())

        result.append(
            {
                "rank": _as_int(raw.get("idx")) if raw.get("idx") is not None else (_as_int(raw.get("rank")) if raw.get("rank") is not None else index),
                "teamId": str(raw.get("id") or raw.get("teamId") or ""),
                "teamName": _clean(
                    raw.get("name")
                    or raw.get("teamName")
                    or raw.get("longName")
                    or raw.get("shortName")
                ),
                "played": _as_int(raw.get("played")) if raw.get("played") is not None else _as_int(raw.get("matches")),
                "wins": _as_int(raw.get("wins")),
                "draws": _as_int(raw.get("draws")),
                "losses": _as_int(raw.get("losses")),
                "goalsFor": _as_int(raw.get("goalsFor")) if raw.get("goalsFor") is not None else _as_int(raw.get("gf")) if gf is None else gf,
                "goalsAgainst": _as_int(raw.get("goalsAgainst")) if raw.get("goalsAgainst") is not None else _as_int(raw.get("ga")) if ga is None else ga,
                "goalDiff": _as_int(raw.get("goalConDiff")) if raw.get("goalConDiff") is not None else _as_int(raw.get("goalDiff")),
                "points": _as_int(raw.get("pts")) if raw.get("pts") is not None else _as_int(raw.get("points")),
                "form": raw.get("form") if isinstance(raw.get("form"), list) else None,
                "raw": raw,
            }
        )

    result.sort(key=lambda row: row["rank"])
    return result


def _extract_tables(data: dict) -> list[dict]:
    """Return one normalized table per real FotMob table/group."""
    candidates = _find_table_nodes(data)
    tables: list[dict] = []

    for index, node in enumerate(candidates):
        table = node.get("table") or {}
        rows = _normalize_rows(table)
        if not rows:
            continue

        group_name = _clean(
            node.get("groupName")
            or node.get("name")
            or node.get("title")
            or node.get("leagueName")
            or table.get("name")
        )

        # FotMob sometimes stores the group name beside the table in its
        # parent object. Keep it only when it is explicitly supplied.
        if not group_name:
            raw_group = node.get("group")
            if isinstance(raw_group, dict):
                group_name = _clean(
                    raw_group.get("name")
                    or raw_group.get("displayName")
                    or raw_group.get("label")
                )
            elif isinstance(raw_group, str):
                group_name = _clean(raw_group)

        if not group_name:
            raw_data = node.get("data")
            if isinstance(raw_data, dict):
                group_name = _clean(
                    raw_data.get("groupName")
                    or raw_data.get("group")
                    or raw_data.get("leagueName")
                )

        tables.append(
            {
                "group": group_name,
                "rows": rows,
                "raw": node,
                "index": index,
            }
        )

    # De-duplicate identical tables that can appear in nested API branches.
    unique: list[dict] = []
    signatures: set[tuple] = set()
    for table in tables:
        signature = tuple(
            (row["teamId"], row["rank"], row["points"])
            for row in table["rows"]
        )
        if signature in signatures:
            continue
        signatures.add(signature)
        unique.append(table)

    return unique


def _extract_season(data: dict) -> str:
    details = data.get("details")
    if isinstance(details, dict):
        for key in ("selectedSeason", "seasonName", "season"):
            value = _clean(details.get(key))
            if value:
                return value

    for key in ("selectedSeason", "seasonName", "season"):
        value = _clean(data.get(key))
        if value:
            return value

    return ""


def _extract_competition(data: dict, fallback_id: str) -> tuple[str, str]:
    details = data.get("details")
    if isinstance(details, dict):
        name = _clean(details.get("name") or details.get("shortName"))
        cid = str(details.get("id") or fallback_id)
        if name:
            return cid, name

    return str(fallback_id), ""



def is_grouped_standings(data: dict) -> bool:
    """True when FotMob returned multiple distinct standings tables/groups."""
    tables = data.get("tables") or []
    return len(tables) > 1 and all(isinstance(table, dict) for table in tables)


def group_stage_complete(table: dict) -> bool:
    """A group is complete when every team has played the full round-robin schedule."""
    rows = table.get("rows") or []
    if len(rows) < 2:
        return False

    expected_matches_per_team = len(rows) - 1
    for row in rows:
        played = _as_int(row.get("played"))
        if played is None or played < expected_matches_per_team:
            return False
    return True


def _is_group_table(table: dict) -> bool:
    """Return True for an actual named group, excluding auxiliary tables.

    FotMob can return extra standings such as "Best 3rd placed teams" alongside
    the real groups. Those tables are displayed, but they are not groups and
    must not prevent the group stage from being considered complete.
    """
    group = _clean(table.get("group"))
    if not group:
        return False
    return bool(
        re.fullmatch(
            r"(?:Grp\.?|Group)\s+[A-Za-z0-9]+",
            group,
            flags=re.IGNORECASE,
        )
    )


def all_groups_complete(data: dict) -> bool:
    """True when every actual named group has completed its schedule."""
    tables = data.get("tables") or []
    if not tables or not is_grouped_standings(data):
        return False

    group_tables = [table for table in tables if _is_group_table(table)]
    if not group_tables:
        return False

    return all(group_stage_complete(table) for table in group_tables)

def _extract_knockout_rounds(data: dict) -> list[dict]:
    """Extract FotMob knockout/playoff rounds from the league payload."""
    found: list[list[dict]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            rounds = value.get("rounds")
            if isinstance(rounds, list):
                valid = [
                    item for item in rounds
                    if isinstance(item, dict) and isinstance(item.get("matchups"), list)
                ]
                if valid:
                    found.append(valid)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(data)

    rounds: list[dict] = []
    seen: set[str] = set()
    for candidate in found:
        for item in candidate:
            signature = repr(item)
            if signature in seen:
                continue
            seen.add(signature)
            rounds.append(item)
    return rounds


def _knockout_stage_label(round_data: dict) -> str:
    """Normalize FotMob knockout stage names to Persian display labels."""
    raw = _clean(
        round_data.get("stage")
        or round_data.get("name")
        or round_data.get("roundName")
        or round_data.get("label")
    )
    low = raw.casefold()
    mapping = {
        "playoff": "پلی‌آف",
        "play-offs": "پلی‌آف",
        "play off": "پلی‌آف",
        "round of 64": "یک‌شصت‌وچهارم نهایی",
        "round of 32": "یک‌شانزدهم نهایی",
        "round of 16": "یک‌هشتم نهایی",
        "quarterfinal": "یک‌چهارم نهایی",
        "quarter-finals": "یک‌چهارم نهایی",
        "quarterfinals": "یک‌چهارم نهایی",
        "semifinal": "نیمه‌نهایی",
        "semi-finals": "نیمه‌نهایی",
        "semifinals": "نیمه‌نهایی",
        "final": "فینال",
        "third place": "رده‌بندی",
        "third-place": "رده‌بندی",
    }
    if low in mapping:
        return mapping[low]

    participant_count = _as_int(round_data.get("participantCount"))
    return {
        64: "یک‌شصت‌وچهارم نهایی",
        32: "یک‌شانزدهم نهایی",
        16: "یک‌هشتم نهایی",
        8: "یک‌چهارم نهایی",
        4: "نیمه‌نهایی",
        2: "فینال",
    }.get(participant_count, raw or "مرحله حذفی")


def _normalize_knockout_round(round_data: dict) -> dict | None:
    matchups = round_data.get("matchups")
    if not isinstance(matchups, list):
        return None

    normalized: list[dict] = []
    for index, raw in enumerate(matchups, start=1):
        if not isinstance(raw, dict):
            continue
        home = raw.get("home") if isinstance(raw.get("home"), dict) else {}
        away = raw.get("away") if isinstance(raw.get("away"), dict) else {}
        normalized.append({
            "number": _as_int(raw.get("drawOrder")) or index,
            "homeTeamId": str(raw.get("homeTeamId") or home.get("id") or ""),
            "awayTeamId": str(raw.get("awayTeamId") or away.get("id") or ""),
            "homeTeam": _clean(raw.get("homeTeam") or home.get("name")),
            "awayTeam": _clean(raw.get("awayTeam") or away.get("name")),
            "homeScore": _as_int(raw.get("homeScore")),
            "awayScore": _as_int(raw.get("awayScore")),
            "winner": str(raw.get("winner") or ""),
            "bestOf": _as_int(raw.get("bestOf")) or 1,
            "tbdTeam1": bool(raw.get("tbdTeam1")),
            "tbdTeam2": bool(raw.get("tbdTeam2")),
            "matches": raw.get("matches") if isinstance(raw.get("matches"), list) else [],
            "aggregatedResult": raw.get("aggregatedResult") if isinstance(raw.get("aggregatedResult"), dict) else {},
            "aggregatedWinner": _as_int(raw.get("aggregatedWinner")),
            "aggregatedLoser": _as_int(raw.get("aggregatedLoser")),
            "penaltyScore": raw.get("penaltyScore") if isinstance(raw.get("penaltyScore"), dict) else None,
            "raw": raw,
        })

    if not normalized:
        return None
    return {
        "stage": _knockout_stage_label(round_data),
        "participantCount": _as_int(round_data.get("participantCount")),
        "matchups": normalized,
        "raw": round_data,
    }


def _collect_explicit_shootout_sections(node: Any, result: list[Any] | None = None) -> list[Any]:
    """Collect only explicit penalty-shootout sections from a FotMob payload."""
    if result is None:
        result = []
    explicit_keys = {
        "penaltyShootout", "penalty_shootout", "shootout",
        "penaltyShootoutEvents", "penalty_shootout_events",
    }
    if isinstance(node, dict):
        for key, value in node.items():
            if key in explicit_keys and isinstance(value, (dict, list)):
                result.append(value)
                _collect_explicit_shootout_sections(value, result)
            elif isinstance(value, (dict, list)):
                _collect_explicit_shootout_sections(value, result)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                _collect_explicit_shootout_sections(item, result)
    return result


def _collect_event_lists(node: Any, result: list[list[dict]] | None = None) -> list[list[dict]]:
    if result is None:
        result = []
    if isinstance(node, list):
        if node and all(isinstance(item, dict) for item in node):
            result.append(node)
        for item in node:
            if isinstance(item, (dict, list)):
                _collect_event_lists(item, result)
    elif isinstance(node, dict):
        preferred = {
            "events", "incidents", "chronological",
            "penaltyShootoutEvents", "penalty_shootout_events",
            "periods", "timeline", "items",
        }
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                if key in preferred or key not in preferred:
                    _collect_event_lists(value, result)
    return result


def _is_penalty_shootout_event(event: dict) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("isPenaltyShootoutEvent") is True:
        return True
    for key in (
        "period", "periodName", "periodType", "matchPeriod",
        "stage", "stageName", "incidentType", "eventType",
        "incidentClass", "type",
    ):
        value = event.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("type") or value.get("key") or value.get("value")
        text = _clean(value).lower()
        compact = text.replace(" ", "").replace("_", "").replace("-", "")
        if "penaltyshootout" in compact or compact == "shootout":
            return True
    return False


def _shootout_score_from_events(node: Any, home_id: Any, away_id: Any) -> dict | None:
    sections = _collect_explicit_shootout_sections(node)
    if not sections:
        return None
    event_lists: list[list[dict]] = []
    for section in sections:
        event_lists.extend(_collect_event_lists(section))
    if not event_lists:
        return None

    seen: set[str] = set()
    home_score = 0
    away_score = 0
    for events in event_lists:
        for event in events:
            if not _is_penalty_shootout_event(event):
                continue
            fingerprint = repr(sorted((str(k), repr(v)) for k, v in event.items()))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            scored = None
            for key in ("isGoal", "isScored", "scored", "converted", "success", "successful"):
                value = event.get(key)
                if isinstance(value, bool):
                    scored = value
                    break

            event_text = " ".join(
                str(event.get(key, "")) for key in
                ("type", "eventType", "incidentType", "incidentClass", "description", "reason")
            ).lower()
            if any(word in event_text for word in ("miss", "saved", "save", "off target", "woodwork")):
                scored = False
            if scored is False:
                continue

            team_id = event.get("teamId")
            is_home = event.get("isHome")
            if home_id is not None and team_id is not None:
                if str(team_id) == str(home_id):
                    is_home = True
                elif away_id is not None and str(team_id) == str(away_id):
                    is_home = False

            if is_home is True:
                home_score += 1
            elif is_home is False:
                away_score += 1

    if home_score == 0 and away_score == 0:
        return None
    return {"home": home_score, "away": away_score}


def _find_match_ids(node: Any) -> list[str]:
    """Find actual FotMob match IDs in a matchup, not team IDs."""
    found: list[str] = []
    seen: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("matchId", "match_id", "matchID"):
                candidate = value.get(key)
                if candidate is not None:
                    text = str(candidate)
                    if text not in seen:
                        seen.add(text)
                        found.append(text)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(node)
    return found


def _coerce_score_pair(value: Any) -> dict | None:
    if isinstance(value, dict):
        home = value.get("home")
        away = value.get("away")
        if home is None:
            home = value.get("homeScore")
        if away is None:
            away = value.get("awayScore")
        if home is not None and away is not None:
            try:
                return {"home": int(home), "away": int(away)}
            except (TypeError, ValueError):
                return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return {"home": int(value[0]), "away": int(value[1])}
        except (TypeError, ValueError):
            return None
    return None


def _collect_shootout_sections(node: Any, result: list[Any] | None = None) -> list[Any]:
    if result is None:
        result = []
    if isinstance(node, dict):
        for key in (
            "penaltyShootout", "penalty_shootout", "shootout",
            "penaltyShootoutEvents", "penalty_shootout_events",
        ):
            value = node.get(key)
            if isinstance(value, (dict, list)):
                result.append(value)
                _collect_shootout_sections(value, result)
        for key, value in node.items():
            if key not in {
                "penaltyShootout", "penalty_shootout", "shootout",
                "penaltyShootoutEvents", "penalty_shootout_events",
            } and isinstance(value, (dict, list)):
                _collect_shootout_sections(value, result)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                _collect_shootout_sections(item, result)
    return result


def _find_shootout_score(node: Any) -> dict | None:
    if isinstance(node, dict):
        for key in ("penaltyScore", "penalty_score", "shootoutScore", "shootout_score"):
            score = _coerce_score_pair(node.get(key))
            if score is not None:
                return score
        for key in ("penalties", "penaltyShootout", "penalty_shootout", "shootout"):
            value = node.get(key)
            score = _coerce_score_pair(value)
            if score is not None:
                return score
            score = _find_shootout_score(value)
            if score is not None:
                return score
    elif isinstance(node, list):
        for item in node:
            score = _find_shootout_score(item)
            if score is not None:
                return score
    return None


def _fetch_penalty_score(match_id: Any, home_id: Any = None, away_id: Any = None) -> dict | None:
    if not match_id:
        return None
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/matchDetails",
            params={"matchId": str(match_id)},
            headers=HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None

        content = payload.get("content")
        if not isinstance(content, dict):
            content = {}

        for key in ("penaltyScore", "penalty_score", "shootoutScore", "shootout_score"):
            score = _coerce_score_pair(content.get(key))
            if score is not None:
                return score

        for section in _collect_explicit_shootout_sections(content):
            score = _find_shootout_score(section)
            if score is not None:
                return score

        score = _shootout_score_from_events(content, home_id, away_id)
        if score is not None:
            return score

        return _find_shootout_score(payload)
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] knockout match {match_id}: penalty details unavailable: {error}")
        return None

def _enrich_knockout_penalties(rounds: list[dict]) -> None:
    """Fill shootout scores from the actual matchDetails payload."""
    for round_data in rounds:
        for matchup in round_data.get("matchups", []):
            match_ids = _find_match_ids(matchup.get("matches") or [])
            if not match_ids:
                match_ids = _find_match_ids(matchup.get("raw") or {})
            for match_id in match_ids:
                score = _fetch_penalty_score(
                    match_id,
                    matchup.get("homeTeamId"),
                    matchup.get("awayTeamId"),
                )
                if score is not None:
                    matchup["penaltyScore"] = score
                    break

def _extract_knockout(data: dict) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple] = set()
    for round_data in _extract_knockout_rounds(data):
        normalized = _normalize_knockout_round(round_data)
        if not normalized:
            continue

        signature = (
            normalized["stage"],
            tuple(
                (m["homeTeamId"], m["awayTeamId"], m["number"])
                for m in normalized["matchups"]
            ),
        )
        if signature in seen:
            continue
        seen.add(signature)
        result.append(normalized)
    return result


def has_knockout(data: dict) -> bool:
    return bool(data.get("knockoutRounds"))


def fetch_standings(competition_id: str, season: str | None = None) -> dict:
    params = {"id": str(competition_id)}
    if season:
        params["season"] = season

    response = requests.get(
        LEAGUE_URL,
        params=params,
        headers=HEADERS,
        timeout=40,
    )
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"FotMob standings response is not an object: {competition_id}")

    tables = _extract_tables(data)
    knockout_rounds = _extract_knockout(data)
    _enrich_knockout_penalties(knockout_rounds)
    if not tables and not knockout_rounds:
        raise RuntimeError(
            f"No standings or knockout data found for FotMob competition {competition_id}."
        )

    cid, name = _extract_competition(data, str(competition_id))
    selected_season = _extract_season(data)

    print(
        f"[STANDINGS] competition={cid} name={name or 'unknown'} "
        f"season={selected_season or 'unknown'} tables={len(tables)}"
    )
    for table in tables:
        print(
            f"[STANDINGS] group={table['group'] or 'overall'} "
            f"rows={len(table['rows'])}"
        )

    return {
        "competitionId": cid,
        "competitionName": name,
        "season": selected_season,
        "tables": tables,
        "knockoutRounds": knockout_rounds,
        "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def fetch_major_league_standings() -> list[dict]:
    results = []
    for competition_id in sorted(MAJOR_LEAGUE_IDS):
        try:
            results.append(fetch_standings(competition_id))
        except requests.RequestException as error:
            print(f"[STANDINGS] {competition_id}: request failed: {error}")
        except RuntimeError as error:
            print(f"[STANDINGS] {competition_id}: {error}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition-id", default="47")
    parser.add_argument("--season")
    args = parser.parse_args()

    result = fetch_standings(args.competition_id, args.season)
    print(
        f"Fetched {len(result['tables'])} table(s), "
        f"{sum(len(t['rows']) for t in result['tables'])} row(s)."
    )


if __name__ == "__main__":
    main()
