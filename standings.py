from __future__ import annotations

import argparse
import datetime as dt
import re
from typing import Any

import requests

from config import CHART_EXCLUDED_COMPETITION_IDS, IRAN_TIMEZONE, MAJOR_LEAGUE_IDS
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


def _fetch_match_score(match_id: Any, home_id: Any = None, away_id: Any = None) -> tuple[int | None, int | None, dict | None]:
    """Read the lightweight canonical FotMob score endpoint."""
    if not match_id:
        return None, None, None
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/match-score",
            params={"matchId": str(match_id)},
            headers=HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] match-score {match_id} unavailable: {error}")
        return None, None, None

    match = payload.get("match") if isinstance(payload, dict) else None
    if not isinstance(match, dict):
        return None, None, None
    home = match.get("home") if isinstance(match.get("home"), dict) else {}
    away = match.get("away") if isinstance(match.get("away"), dict) else {}
    hid = str(home.get("id") or "")
    aid = str(away.get("id") or "")
    if home_id and hid != str(home_id):
        return None, None, None
    if away_id and aid != str(away_id):
        return None, None, None

    def score(value: Any) -> int | None:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        return None

    return score(home.get("score")), score(away.get("score")), None


def _fetch_match_result(match_id: Any, home_id: Any = None, away_id: Any = None) -> tuple[int | None, int | None, dict | None]:
    """Read the canonical match score from FotMob matchDetails."""
    if not match_id:
        return None, None, None
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/matchDetails",
            params={"matchId": str(match_id)},
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] knockout match {match_id}: result details unavailable: {error}")
        return None, None, None

    def score(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        if isinstance(value, dict):
            for key in ("score", "current", "display", "value", "goals"):
                result = score(value.get(key))
                if result is not None:
                    return result
        return None

    def teams_score(node: Any) -> tuple[int | None, int | None] | None:
        if not isinstance(node, dict):
            return None
        teams = node.get("teams")
        if isinstance(teams, dict):
            home = teams.get("home")
            away = teams.get("away")
            if isinstance(home, dict) and isinstance(away, dict):
                hid = str(home.get("id") or home.get("teamId") or "")
                aid = str(away.get("id") or away.get("teamId") or "")
                if (not home_id or hid == str(home_id)) and (not away_id or aid == str(away_id)):
                    hs = score(home.get("score"))
                    aw = score(away.get("score"))
                    if hs is not None and aw is not None:
                        return hs, aw
        home = node.get("home")
        away = node.get("away")
        if isinstance(home, dict) and isinstance(away, dict):
            hid = str(home.get("id") or home.get("teamId") or "")
            aid = str(away.get("id") or away.get("teamId") or "")
            if (not home_id or hid == str(home_id)) and (not away_id or aid == str(away_id)):
                hs = score(home.get("score"))
                aw = score(away.get("score"))
                if hs is None:
                    hs = score(node.get("homeScore"))
                if aw is None:
                    aw = score(node.get("awayScore"))
                if hs is not None and aw is not None:
                    return hs, aw
        return None

    candidates = [payload]
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, dict):
            candidates.extend([
                content,
                content.get("header"),
                content.get("matchFacts"),
            ])
    result = None
    for candidate in candidates:
        result = teams_score(candidate)
        if result is not None:
            break

    if result is None:
        def walk(node: Any) -> tuple[int | None, int | None] | None:
            if isinstance(node, dict):
                pair = teams_score(node)
                if pair is not None:
                    return pair
                for value in node.values():
                    found = walk(value)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for value in node:
                    found = walk(value)
                    if found is not None:
                        return found
            return None
        result = walk(payload)

    penalty = _fetch_penalty_score(match_id, home_id, away_id)
    if result is None:
        return None, None, penalty
    return result[0], result[1], penalty

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
                home_score, away_score, penalty = _fetch_match_result(
                    match_id,
                    matchup.get("homeTeamId"),
                    matchup.get("awayTeamId"),
                )
                if home_score is not None:
                    matchup["homeScore"] = home_score
                if away_score is not None:
                    matchup["awayScore"] = away_score
                if penalty is not None:
                    matchup["penaltyScore"] = penalty
                if home_score is not None or away_score is not None or penalty is not None:
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


def _extract_single_matchup(data: Any) -> dict | None:
    """Extract a lone competition match when FotMob has no table/bracket."""
    candidates: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            home = node.get("home")
            away = node.get("away")
            match_id = node.get("matchId") or node.get("match_id")
            if match_id is None:
                match_id = node.get("id")
            if (
                isinstance(home, dict)
                and isinstance(away, dict)
                and home.get("id") is not None
                and away.get("id") is not None
                and match_id is not None
            ):
                key = str(match_id)
                if key not in seen:
                    seen.add(key)
                    candidates.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(data)
    if len(candidates) != 1:
        return None

    raw = candidates[0]
    home = raw.get("home") or {}
    away = raw.get("away") or {}
    home_score = _as_int(raw.get("homeScore"))
    away_score = _as_int(raw.get("awayScore"))
    if home_score is None:
        home_score = _as_int(home.get("score"))
    if away_score is None:
        away_score = _as_int(away.get("score"))

    return {
        "number": 1,
        "homeTeamId": str(home.get("id") or ""),
        "awayTeamId": str(away.get("id") or ""),
        "homeTeam": _clean(home.get("name") or home.get("longName")),
        "awayTeam": _clean(away.get("name") or away.get("longName")),
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": str(raw.get("winner") or ""),
        "bestOf": 1,
        "tbdTeam1": False,
        "tbdTeam2": False,
        "matches": [{"matchId": str(raw.get("matchId") or raw.get("match_id") or raw.get("id"))}],
        "aggregatedResult": {},
        "aggregatedWinner": None,
        "aggregatedLoser": None,
        "penaltyScore": raw.get("penaltyScore") if isinstance(raw.get("penaltyScore"), dict) else None,
        "raw": raw,
    }


def _fetch_single_matchup(competition_id: str, season: str | None) -> dict | None:
    """Fallback for single-match competitions that expose no table/bracket."""
    params = {"id": str(competition_id)}
    if season:
        params["season"] = season
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/fixtures",
            params=params,
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            return None
        return _extract_single_matchup(payload)
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] {competition_id}: single-match fallback unavailable: {error}")
        return None


def _single_match_knockout(matchup: dict) -> list[dict]:
    return [{
        "stage": "فینال",
        "participantCount": 2,
        "matchups": [matchup],
        "raw": matchup.get("raw") or {},
    }]



def _extract_fixture_matchups(data: Any) -> list[dict]:
    """Collect FotMob fixtures while tolerating the different fixture schemas."""
    found: list[dict] = []
    seen: set[str] = set()

    def first_dict(node: dict, keys: tuple[str, ...]) -> dict | None:
        for key in keys:
            value = node.get(key)
            if isinstance(value, dict):
                return value
        return None

    def match_id_from(node: dict) -> str:
        for key in ("matchId", "match_id", "fixtureId", "fixture_id"):
            value = node.get(key)
            if value is not None:
                return str(value)
        nested = node.get("match")
        if isinstance(nested, dict):
            for key in ("matchId", "match_id", "id"):
                value = nested.get(key)
                if value is not None:
                    return str(value)
        value = node.get("id")
        return str(value) if value is not None else ""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            home = first_dict(node, ("home", "homeTeam", "home_team"))
            away = first_dict(node, ("away", "awayTeam", "away_team"))
            if home and away:
                match_id = match_id_from(node)
                if not match_id:
                    nested = node.get("match")
                    if isinstance(nested, dict):
                        match_id = match_id_from(nested)
                if match_id and match_id not in seen:
                    seen.add(match_id)
                    item = dict(node)
                    item["_fixture_home"] = home
                    item["_fixture_away"] = away
                    item["_fixture_match_id"] = match_id
                    item["_fixture_stage"] = (
                        node.get("stage")
                        or node.get("roundName")
                        or node.get("round")
                        or node.get("stageName")
                        or node.get("stage_name")
                        or node.get("round_name")
                        or node.get("roundInfo")
                    )
                    found.append(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found



def _fixture_stage_text(match: dict) -> str:
    value = match.get("_fixture_stage")
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("roundName")
            or value.get("stageName")
            or value.get("round")
        )
    return str(value or "").strip().lower()


def _fixture_score_value(team: dict, match: dict, side: str) -> int | None:
    candidates = [
        team.get("score"),
        team.get("currentScore"),
        team.get("displayScore"),
        team.get("goals"),
        match.get(f"{side}Score"),
        match.get(f"{side}_score"),
        match.get(f"{side}Goals"),
    ]
    for value in candidates:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        if isinstance(value, dict):
            for key in ("current", "display", "value", "score", "goals"):
                nested = value.get(key)
                if isinstance(nested, (int, float)):
                    return int(nested)
                if isinstance(nested, str) and nested.strip().lstrip("-").isdigit():
                    return int(nested)
    return None


def _fixture_penalty_score(match: dict) -> dict | None:
    value = match.get("penaltyScore") or match.get("penaltyScores")
    if isinstance(value, dict):
        home = value.get("home")
        away = value.get("away")
        if isinstance(home, dict):
            home = home.get("score") or home.get("value")
        if isinstance(away, dict):
            away = away.get("score") or away.get("value")
        if isinstance(home, (int, float)) and isinstance(away, (int, float)):
            return {"home": int(home), "away": int(away)}
    for container_key in ("shootout", "penalties", "penaltyShootout"):
        container = match.get(container_key)
        if isinstance(container, dict):
            home = container.get("home") or container.get("homeScore")
            away = container.get("away") or container.get("awayScore")
            if isinstance(home, (int, float)) and isinstance(away, (int, float)):
                return {"home": int(home), "away": int(away)}
    return None


def _normalize_fixture_match(match: dict) -> dict:
    home = match.get("_fixture_home") or match.get("home") or match.get("homeTeam") or {}
    away = match.get("_fixture_away") or match.get("away") or match.get("awayTeam") or {}
    match_id = match.get("_fixture_match_id") or match.get("matchId") or match.get("match_id") or match.get("id")
    return {
        "home": {
            "id": str(home.get("id") or home.get("teamId") or ""),
            "name": str(home.get("name") or home.get("teamName") or ""),
        },
        "away": {
            "id": str(away.get("id") or away.get("teamId") or ""),
            "name": str(away.get("name") or away.get("teamName") or ""),
        },
        "homeScore": _fixture_score_value(home, match, "home"),
        "awayScore": _fixture_score_value(away, match, "away"),
        "winner": str(match.get("winner") or ""),
        "bestOf": 1,
        "tbdTeam1": False,
        "tbdTeam2": False,
        "matches": [{"matchId": str(match_id)}],
        "aggregatedResult": {},
        "aggregatedWinner": None,
        "aggregatedLoser": None,
        "penaltyScore": _fixture_penalty_score(match),
        "raw": match,
    }





def _fetch_uefa_world_cup_playoffs(season: str | None) -> list[dict]:
    """Build the UEFA 2026 playoff tree from fixtures plus the official path draw.

    FotMob does not expose the bracket tree reliably, so the path relationship
    is defined here, while scores/results are read from FotMob fixtures.
    """
    params = {"id": "10195"}
    if season:
        params["season"] = season
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/fixtures",
            params=params,
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] 10195: UEFA playoff fixtures unavailable: {error}")
        return []

    fixtures = _extract_fixture_matchups(payload)
    by_pair: dict[frozenset[str], dict] = {}
    for fixture in fixtures:
        home = fixture.get("home") or {}
        away = fixture.get("away") or {}
        home_id = str(home.get("id") or home.get("teamId") or "")
        away_id = str(away.get("id") or away.get("teamId") or "")
        if home_id and away_id:
            by_pair[frozenset((home_id, away_id))] = fixture

    # Official 2026 draw: two semi-finals form each path, and their winners
    # meet in that path's final. The relationships are fixed before matches.
    team_ids = {
        "ایتالیا": "8204",
        "ایرلند شمالی": "10259",
        "ولز": "5790",
        "بوسنی و هرزگوین": "10106",
        "اوکراین": "6718",
        "سوئد": "8520",
        "لهستان": "8568",
        "آلبانی": "10024",
        "ترکیه": "6595",
        "رومانی": "9730",
        "اسلواکی": "8497",
        "کوزوو": "430156",
        "دانمارک": "8238",
        "مقدونیه شمالی": "8260",
        "چک": "8496",
        "ایرلند": "5791",
    }
    paths = [
        [("ایتالیا", "ایرلند شمالی"), ("ولز", "بوسنی و هرزگوین")],
        [("اوکراین", "سوئد"), ("لهستان", "آلبانی")],
        [("ترکیه", "رومانی"), ("اسلواکی", "کوزوو")],
        [("دانمارک", "مقدونیه شمالی"), ("چک", "ایرلند")],
    ]

    def normalize(fixture: dict) -> dict:
        return _normalize_fixture_match(fixture)

    semifinals: list[dict] = []
    winners_by_path: list[list[dict]] = []
    for path in paths:
        path_matches: list[dict] = []
        path_winners: list[dict] = []
        for home_name, away_name in path:
            key = frozenset((team_ids[home_name], team_ids[away_name]))
            fixture = by_pair.get(key)
            if fixture is None:
                print(f"[STANDINGS] 10195: missing fixture {home_name} vs {away_name}")
                return []
            match = normalize(fixture)
            match_id = match.get("matches", [{}])[0].get("matchId")
            hs, aw, _ = _fetch_match_score(
                match_id,
                match.get("home", {}).get("id"),
                match.get("away", {}).get("id"),
            )
            if hs is not None and aw is not None:
                match["homeScore"] = hs
                match["awayScore"] = aw
            else:
                hs, aw, penalty = _fetch_match_result(
                    match_id,
                    match.get("home", {}).get("id"),
                    match.get("away", {}).get("id"),
                )
                if hs is not None and aw is not None:
                    match["homeScore"] = hs
                    match["awayScore"] = aw
                if penalty is not None:
                    match["penaltyScore"] = penalty
            path_matches.append(match)
            path_winners.append(match)
        winners_by_path.append(path_winners)
        semifinals.extend(path_matches)

    def winner_name(match: dict) -> tuple[str, str] | None:
        home_score = match.get("homeScore")
        away_score = match.get("awayScore")
        if not isinstance(home_score, (int, float)) or not isinstance(away_score, (int, float)):
            return None
        if home_score > away_score:
            return str(match["home"]["name"]), str(match["home"]["id"])
        if away_score > home_score:
            return str(match["away"]["name"]), str(match["away"]["id"])
        penalty = match.get("penaltyScore") or {}
        if isinstance(penalty, dict):
            hp = penalty.get("home")
            ap = penalty.get("away")
            if isinstance(hp, (int, float)) and isinstance(ap, (int, float)):
                if hp > ap:
                    return str(match["home"]["name"]), str(match["home"]["id"])
                if ap > hp:
                    return str(match["away"]["name"]), str(match["away"]["id"])
        return None

    finals: list[dict] = []
    for path_index, path_matches in enumerate(winners_by_path, 1):
        winners = [winner_name(match) for match in path_matches]
        final_fixture = None
        if all(w is not None for w in winners):
            ids = [w[1] for w in winners]
            final_fixture = by_pair.get(frozenset(ids))
        if final_fixture is not None:
            final_match = normalize(final_fixture)
            match_id = final_match.get("matches", [{}])[0].get("matchId")
            hs, aw, _ = _fetch_match_score(
                match_id,
                final_match.get("home", {}).get("id"),
                final_match.get("away", {}).get("id"),
            )
            if hs is not None and aw is not None:
                final_match["homeScore"] = hs
                final_match["awayScore"] = aw
            else:
                hs, aw, penalty = _fetch_match_result(
                    match_id,
                    final_match.get("home", {}).get("id"),
                    final_match.get("away", {}).get("id"),
                )
                if hs is not None and aw is not None:
                    final_match["homeScore"] = hs
                    final_match["awayScore"] = aw
                if penalty is not None:
                    final_match["penaltyScore"] = penalty
        elif all(w is not None for w in winners):
            home_name, home_id = winners[0]
            away_name, away_id = winners[1]
            final_match = {
                "home": {"id": home_id, "name": home_name},
                "away": {"id": away_id, "name": away_name},
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": False,
                "tbdTeam2": False,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {"source": "derived-path", "path": path_index},
            }
        else:
            # Results are not complete yet: keep the path relationship visible
            # with placeholders instead of inventing a final pairing.
            final_match = {
                "home": {"id": "", "name": f"برنده بازی {path_index * 2 - 1}"},
                "away": {"id": "", "name": f"برنده بازی {path_index * 2}"},
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": True,
                "tbdTeam2": True,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {"source": "derived-path", "path": path_index},
            }
        finals.append(final_match)

    return [
        {
            "stage": "نیمه‌نهایی",
            "participantCount": 16,
            "matchups": semifinals,
            "raw": {"source": "fixtures+draw", "competitionId": "10195", "pathCount": 4},
        },
        {
            "stage": "فینال",
            "participantCount": 8,
            "matchups": finals,
            "raw": {"source": "fixtures+draw", "competitionId": "10195", "pathCount": 4},
        },
    ]


def _manual_uefa_world_cup_playoffs() -> list[dict]:
    """Static 2026 UEFA playoff bracket; FotMob does not expose the bracket tree."""
    team_ids = {
        "ایتالیا": "8204",
        "ایرلند شمالی": "10259",
        "ولز": "5790",
        "بوسنی و هرزگوین": "10106",
        "اوکراین": "6718",
        "سوئد": "8520",
        "لهستان": "8568",
        "آلبانی": "10024",
        "ترکیه": "6595",
        "رومانی": "9730",
        "اسلواکی": "8497",
        "کوزوو": "430156",
        "دانمارک": "8238",
        "مقدونیه شمالی": "8260",
        "چک": "8496",
        "ایرلند": "5791",
    }

    def match(
        home: str,
        away: str,
        home_score: int,
        away_score: int,
        home_penalty: int | None = None,
        away_penalty: int | None = None,
    ) -> dict:
        penalty = None
        if home_penalty is not None and away_penalty is not None:
            penalty = {"home": home_penalty, "away": away_penalty}
        return {
            "number": 0,
            "homeTeamId": team_ids[home],
            "awayTeamId": team_ids[away],
            "homeTeam": home,
            "awayTeam": away,
            "homeScore": home_score,
            "awayScore": away_score,
            "winner": "",
            "bestOf": 1,
            "tbdTeam1": False,
            "tbdTeam2": False,
            "matches": [],
            "aggregatedResult": {},
            "aggregatedWinner": None,
            "aggregatedLoser": None,
            "penaltyScore": penalty,
            "raw": {},
        }

    semifinal_pairs = [
        ("ایتالیا", "ایرلند شمالی", 2, 0, None, None),
        ("ولز", "بوسنی و هرزگوین", 1, 1, 2, 4),
        ("اوکراین", "سوئد", 1, 3, None, None),
        ("لهستان", "آلبانی", 2, 1, None, None),
        ("ترکیه", "رومانی", 1, 0, None, None),
        ("اسلواکی", "کوزوو", 3, 4, None, None),
        ("دانمارک", "مقدونیه شمالی", 4, 0, None, None),
        ("چک", "ایرلند", 2, 2, 4, 3),
    ]
    final_pairs = [
        ("بوسنی و هرزگوین", "ایتالیا", 1, 1, 4, 1),
        ("سوئد", "لهستان", 3, 2, None, None),
        ("کوزوو", "ترکیه", 0, 1, None, None),
        ("چک", "دانمارک", 2, 2, 3, 1),
    ]

    semifinals = [
        dict(match("home", "away", 0, 0), number=index + 1)
        for index, match in enumerate([])
    ]
    semifinals = []
    for index, item in enumerate(semifinal_pairs, 1):
        m = match(*item)
        m["number"] = index
        semifinals.append(m)

    finals = []
    for index, item in enumerate(final_pairs, 1):
        m = match(*item)
        m["number"] = index
        finals.append(m)

    return [
        {
            "stage": "نیمه‌نهایی",
            "participantCount": 16,
            "matchups": semifinals,
            "raw": {"source": "manual", "competitionId": "10195", "pathCount": 4},
        },
        {
            "stage": "فینال",
            "participantCount": 8,
            "matchups": finals,
            "raw": {"source": "manual", "competitionId": "10195", "pathCount": 4},
        },
    ]


def fetch_standings(competition_id: str, season: str | None = None) -> dict:
    competition_id = str(competition_id)
    if competition_id in CHART_EXCLUDED_COMPETITION_IDS:
        raise RuntimeError(
            f"Competition {competition_id} is intentionally excluded from standings/knockout chart rendering."
        )

    params = {"id": competition_id}
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
    if competition_id == "10195" and not knockout_rounds:
        knockout_rounds = _fetch_uefa_world_cup_playoffs(season)
        if knockout_rounds:
            print("[STANDINGS] 10195: UEFA playoff fallback -> semifinals + finals")
        else:
            knockout_rounds = _manual_uefa_world_cup_playoffs()
            print("[STANDINGS] 10195: manual UEFA playoff bracket -> semifinals + finals")
    _enrich_knockout_penalties(knockout_rounds)

    # Some super cups and one-off competitions have no standings or bracket
    # in FotMob at all. If the competition has exactly one fixture, represent
    # that match as a one-card final instead of treating the competition as an
    # error. Competitions with multiple fixtures still need real knockout data.
    if not tables and not knockout_rounds:
        single_match = _fetch_single_matchup(competition_id, season)
        if single_match is not None:
            knockout_rounds = _single_match_knockout(single_match)
            print(f"[STANDINGS] {competition_id}: single-match fallback -> final")
        else:
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


def _extract_single_matchup(data: Any) -> dict | None:
    """Extract a lone competition match when FotMob has no table/bracket."""
    candidates: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            home = node.get("home")
            away = node.get("away")
            match_id = node.get("matchId") or node.get("match_id")
            if match_id is None:
                match_id = node.get("id")
            if (
                isinstance(home, dict)
                and isinstance(away, dict)
                and home.get("id") is not None
                and away.get("id") is not None
                and match_id is not None
            ):
                key = str(match_id)
                if key not in seen:
                    seen.add(key)
                    candidates.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(data)
    if len(candidates) != 1:
        return None

    raw = candidates[0]
    home = raw.get("home") or {}
    away = raw.get("away") or {}
    home_score = _as_int(raw.get("homeScore"))
    away_score = _as_int(raw.get("awayScore"))
    if home_score is None:
        home_score = _as_int(home.get("score"))
    if away_score is None:
        away_score = _as_int(away.get("score"))

    return {
        "number": 1,
        "homeTeamId": str(home.get("id") or ""),
        "awayTeamId": str(away.get("id") or ""),
        "homeTeam": _clean(home.get("name") or home.get("longName")),
        "awayTeam": _clean(away.get("name") or away.get("longName")),
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": str(raw.get("winner") or ""),
        "bestOf": 1,
        "tbdTeam1": False,
        "tbdTeam2": False,
        "matches": [{"matchId": str(raw.get("matchId") or raw.get("match_id") or raw.get("id"))}],
        "aggregatedResult": {},
        "aggregatedWinner": None,
        "aggregatedLoser": None,
        "penaltyScore": raw.get("penaltyScore") if isinstance(raw.get("penaltyScore"), dict) else None,
        "raw": raw,
    }


def _fetch_single_matchup(competition_id: str, season: str | None) -> dict | None:
    """Fallback for single-match competitions that expose no table/bracket."""
    params = {"id": str(competition_id)}
    if season:
        params["season"] = season
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/fixtures",
            params=params,
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            return None
        return _extract_single_matchup(payload)
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] {competition_id}: single-match fallback unavailable: {error}")
        return None


def _single_match_knockout(matchup: dict) -> list[dict]:
    return [{
        "stage": "فینال",
        "participantCount": 2,
        "matchups": [matchup],
        "raw": matchup.get("raw") or {},
    }]



def _extract_fixture_matchups(data: Any) -> list[dict]:
    """Recursively collect unique fixture-like matchups from a FotMob payload."""
    found: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            home = node.get("home") if isinstance(node.get("home"), dict) else None
            away = node.get("away") if isinstance(node.get("away"), dict) else None
            match_id = node.get("matchId") or node.get("match_id") or node.get("id")
            if home and away and match_id is not None:
                key = str(match_id)
                if key not in seen:
                    seen.add(key)
                    item = dict(node)
                    item["_fixture_stage"] = (
                        node.get("stage")
                        or node.get("roundName")
                        or node.get("round")
                        or node.get("stageName")
                        or node.get("stage_name")
                        or node.get("round_name")
                        or node.get("roundInfo")
                    )
                    found.append(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found


def _fixture_stage_text(match: dict) -> str:
    value = match.get("_fixture_stage")
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("roundName")
            or value.get("stageName")
            or value.get("round")
        )
    return str(value or "").strip().lower()


def _fixture_score_value(team: dict, match: dict, side: str) -> int | None:
    candidates = [
        team.get("score"),
        team.get("currentScore"),
        team.get("displayScore"),
        team.get("goals"),
        match.get(f"{side}Score"),
        match.get(f"{side}_score"),
        match.get(f"{side}Goals"),
    ]
    for value in candidates:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        if isinstance(value, dict):
            for key in ("current", "display", "value", "score", "goals"):
                nested = value.get(key)
                if isinstance(nested, (int, float)):
                    return int(nested)
                if isinstance(nested, str) and nested.strip().lstrip("-").isdigit():
                    return int(nested)
    return None


def _fixture_penalty_score(match: dict) -> dict | None:
    value = match.get("penaltyScore") or match.get("penaltyScores")
    if isinstance(value, dict):
        home = value.get("home")
        away = value.get("away")
        if isinstance(home, dict):
            home = home.get("score") or home.get("value")
        if isinstance(away, dict):
            away = away.get("score") or away.get("value")
        if isinstance(home, (int, float)) and isinstance(away, (int, float)):
            return {"home": int(home), "away": int(away)}
    for container_key in ("shootout", "penalties", "penaltyShootout"):
        container = match.get(container_key)
        if isinstance(container, dict):
            home = container.get("home") or container.get("homeScore")
            away = container.get("away") or container.get("awayScore")
            if isinstance(home, (int, float)) and isinstance(away, (int, float)):
                return {"home": int(home), "away": int(away)}
    return None


def _normalize_fixture_match(match: dict) -> dict:
    home = match.get("home") or {}
    away = match.get("away") or {}
    match_id = match.get("matchId") or match.get("match_id") or match.get("id")
    return {
        "home": {
            "id": str(home.get("id") or home.get("teamId") or ""),
            "name": str(home.get("name") or home.get("teamName") or "نامشخص"),
        },
        "away": {
            "id": str(away.get("id") or away.get("teamId") or ""),
            "name": str(away.get("name") or away.get("teamName") or "نامشخص"),
        },
        "homeScore": _fixture_score_value(home, match, "home"),
        "awayScore": _fixture_score_value(away, match, "away"),
        "winner": str(match.get("winner") or ""),
        "bestOf": 1,
        "tbdTeam1": False,
        "tbdTeam2": False,
        "matches": [{"matchId": str(match_id)}],
        "aggregatedResult": {},
        "aggregatedWinner": None,
        "aggregatedLoser": None,
        "penaltyScore": _fixture_penalty_score(match),
        "raw": match,
    }


def _fetch_uefa_world_cup_playoffs(season: str | None) -> list[dict]:
    """Build the UEFA 2026 playoff tree from fixtures plus the official path draw.

    FotMob does not expose the bracket tree reliably, so the path relationship
    is defined here, while scores/results are read from FotMob fixtures.
    """
    params = {"id": "10195"}
    if season:
        params["season"] = season
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/fixtures",
            params=params,
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] 10195: UEFA playoff fixtures unavailable: {error}")
        return []

    fixtures = _extract_fixture_matchups(payload)
    by_pair: dict[frozenset[str], dict] = {}
    for fixture in fixtures:
        home = fixture.get("home") or {}
        away = fixture.get("away") or {}
        home_id = str(home.get("id") or home.get("teamId") or "")
        away_id = str(away.get("id") or away.get("teamId") or "")
        if home_id and away_id:
            by_pair[frozenset((home_id, away_id))] = fixture

    # Official 2026 draw: two semi-finals form each path, and their winners
    # meet in that path's final. The relationships are fixed before matches.
    team_ids = {
        "ایتالیا": "8204",
        "ایرلند شمالی": "10259",
        "ولز": "5790",
        "بوسنی و هرزگوین": "10106",
        "اوکراین": "6718",
        "سوئد": "8520",
        "لهستان": "8568",
        "آلبانی": "10024",
        "ترکیه": "6595",
        "رومانی": "9730",
        "اسلواکی": "8497",
        "کوزوو": "430156",
        "دانمارک": "8238",
        "مقدونیه شمالی": "8260",
        "چک": "8496",
        "ایرلند": "5791",
    }
    paths = [
        [("ایتالیا", "ایرلند شمالی"), ("ولز", "بوسنی و هرزگوین")],
        [("اوکراین", "سوئد"), ("لهستان", "آلبانی")],
        [("ترکیه", "رومانی"), ("اسلواکی", "کوزوو")],
        [("دانمارک", "مقدونیه شمالی"), ("چک", "ایرلند")],
    ]

    def normalize(fixture: dict) -> dict:
        return _normalize_fixture_match(fixture)

    semifinals: list[dict] = []
    winners_by_path: list[list[dict]] = []
    for path in paths:
        path_matches: list[dict] = []
        path_winners: list[dict] = []
        for home_name, away_name in path:
            key = frozenset((team_ids[home_name], team_ids[away_name]))
            fixture = by_pair.get(key)
            if fixture is None:
                print(f"[STANDINGS] 10195: missing fixture {home_name} vs {away_name}")
                return []
            match = normalize(fixture)
            path_matches.append(match)
            path_winners.append(match)
        winners_by_path.append(path_winners)
        semifinals.extend(path_matches)

    def winner_name(match: dict) -> tuple[str, str] | None:
        home_score = match.get("homeScore")
        away_score = match.get("awayScore")
        if not isinstance(home_score, (int, float)) or not isinstance(away_score, (int, float)):
            return None
        if home_score > away_score:
            return str(match["home"]["name"]), str(match["home"]["id"])
        if away_score > home_score:
            return str(match["away"]["name"]), str(match["away"]["id"])
        penalty = match.get("penaltyScore") or {}
        if isinstance(penalty, dict):
            hp = penalty.get("home")
            ap = penalty.get("away")
            if isinstance(hp, (int, float)) and isinstance(ap, (int, float)):
                if hp > ap:
                    return str(match["home"]["name"]), str(match["home"]["id"])
                if ap > hp:
                    return str(match["away"]["name"]), str(match["away"]["id"])
        return None

    finals: list[dict] = []
    for path_index, path_matches in enumerate(winners_by_path, 1):
        winners = [winner_name(match) for match in path_matches]
        final_fixture = None
        if all(w is not None for w in winners):
            ids = [w[1] for w in winners]
            final_fixture = by_pair.get(frozenset(ids))
        if final_fixture is not None:
            final_match = normalize(final_fixture)
        elif all(w is not None for w in winners):
            home_name, home_id = winners[0]
            away_name, away_id = winners[1]
            final_match = {
                "home": {"id": home_id, "name": home_name},
                "away": {"id": away_id, "name": away_name},
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": False,
                "tbdTeam2": False,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {"source": "derived-path", "path": path_index},
            }
        else:
            # Results are not complete yet: keep the path relationship visible
            # with placeholders instead of inventing a final pairing.
            final_match = {
                "home": {"id": "", "name": f"برنده بازی {path_index * 2 - 1}"},
                "away": {"id": "", "name": f"برنده بازی {path_index * 2}"},
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": True,
                "tbdTeam2": True,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {"source": "derived-path", "path": path_index},
            }
        finals.append(final_match)

    return [
        {
            "stage": "نیمه‌نهایی",
            "participantCount": 16,
            "matchups": semifinals,
            "raw": {"source": "fixtures+draw", "competitionId": "10195", "pathCount": 4},
        },
        {
            "stage": "فینال",
            "participantCount": 8,
            "matchups": finals,
            "raw": {"source": "fixtures+draw", "competitionId": "10195", "pathCount": 4},
        },
    ]


def _manual_uefa_world_cup_playoffs() -> list[dict]:
    """Static 2026 UEFA playoff bracket; FotMob does not expose the bracket tree."""
    team_ids = {
        "ایتالیا": "8204",
        "ایرلند شمالی": "10259",
        "ولز": "5790",
        "بوسنی و هرزگوین": "10106",
        "اوکراین": "6718",
        "سوئد": "8520",
        "لهستان": "8568",
        "آلبانی": "10024",
        "ترکیه": "6595",
        "رومانی": "9730",
        "اسلواکی": "8497",
        "کوزوو": "430156",
        "دانمارک": "8238",
        "مقدونیه شمالی": "8260",
        "چک": "8496",
        "ایرلند": "5791",
    }

    def match(
        home: str,
        away: str,
        home_score: int,
        away_score: int,
        home_penalty: int | None = None,
        away_penalty: int | None = None,
    ) -> dict:
        penalty = None
        if home_penalty is not None and away_penalty is not None:
            penalty = {"home": home_penalty, "away": away_penalty}
        return {
            "number": 0,
            "homeTeamId": team_ids[home],
            "awayTeamId": team_ids[away],
            "homeTeam": home,
            "awayTeam": away,
            "homeScore": home_score,
            "awayScore": away_score,
            "winner": "",
            "bestOf": 1,
            "tbdTeam1": False,
            "tbdTeam2": False,
            "matches": [],
            "aggregatedResult": {},
            "aggregatedWinner": None,
            "aggregatedLoser": None,
            "penaltyScore": penalty,
            "raw": {},
        }

    semifinal_pairs = [
        ("ایتالیا", "ایرلند شمالی", 2, 0, None, None),
        ("ولز", "بوسنی و هرزگوین", 1, 1, 2, 4),
        ("اوکراین", "سوئد", 1, 3, None, None),
        ("لهستان", "آلبانی", 2, 1, None, None),
        ("ترکیه", "رومانی", 1, 0, None, None),
        ("اسلواکی", "کوزوو", 3, 4, None, None),
        ("دانمارک", "مقدونیه شمالی", 4, 0, None, None),
        ("چک", "ایرلند", 2, 2, 4, 3),
    ]
    final_pairs = [
        ("بوسنی و هرزگوین", "ایتالیا", 1, 1, 4, 1),
        ("سوئد", "لهستان", 3, 2, None, None),
        ("کوزوو", "ترکیه", 0, 1, None, None),
        ("چک", "دانمارک", 2, 2, 3, 1),
    ]

    semifinals = [
        dict(match("home", "away", 0, 0), number=index + 1)
        for index, match in enumerate([])
    ]
    semifinals = []
    for index, item in enumerate(semifinal_pairs, 1):
        m = match(*item)
        m["number"] = index
        semifinals.append(m)

    finals = []
    for index, item in enumerate(final_pairs, 1):
        m = match(*item)
        m["number"] = index
        finals.append(m)

    return [
        {
            "stage": "نیمه‌نهایی",
            "participantCount": 16,
            "matchups": semifinals,
            "raw": {"source": "manual", "competitionId": "10195", "pathCount": 4},
        },
        {
            "stage": "فینال",
            "participantCount": 8,
            "matchups": finals,
            "raw": {"source": "manual", "competitionId": "10195", "pathCount": 4},
        },
    ]


def fetch_standings(competition_id: str, season: str | None = None) -> dict:
    competition_id = str(competition_id)
    if competition_id in CHART_EXCLUDED_COMPETITION_IDS:
        raise RuntimeError(
            f"Competition {competition_id} is intentionally excluded from standings/knockout chart rendering."
        )

    params = {"id": competition_id}
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
    if competition_id == "10195" and not knockout_rounds:
        knockout_rounds = _fetch_uefa_world_cup_playoffs(season)
        if knockout_rounds:
            print("[STANDINGS] 10195: UEFA playoff fallback -> semifinals + finals")
        else:
            knockout_rounds = _manual_uefa_world_cup_playoffs()
            print("[STANDINGS] 10195: manual UEFA playoff bracket -> semifinals + finals")
    _enrich_knockout_penalties(knockout_rounds)

    # Some super cups and one-off competitions have no standings or bracket
    # in FotMob at all. If the competition has exactly one fixture, represent
    # that match as a one-card final instead of treating the competition as an
    # error. Competitions with multiple fixtures still need real knockout data.
    if not tables and not knockout_rounds:
        single_match = _fetch_single_matchup(competition_id, season)
        if single_match is not None:
            knockout_rounds = _single_match_knockout(single_match)
            print(f"[STANDINGS] {competition_id}: single-match fallback -> final")
        else:
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


def _enrich_knockout_penalties(rounds: list[dict]) -> None:
    """Fill shootout scores from the actual matchDetails payload."""
    for round_data in rounds:
        for matchup in round_data.get("matchups", []):
            match_ids = _find_match_ids(matchup.get("matches") or [])
            if not match_ids:
                match_ids = _find_match_ids(matchup.get("raw") or {})
            for match_id in match_ids:
                home_score, away_score, penalty = _fetch_match_result(
                    match_id,
                    matchup.get("homeTeamId"),
                    matchup.get("awayTeamId"),
                )
                if home_score is not None:
                    matchup["homeScore"] = home_score
                if away_score is not None:
                    matchup["awayScore"] = away_score
                if penalty is not None:
                    matchup["penaltyScore"] = penalty
                if home_score is not None or away_score is not None or penalty is not None:
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


def _extract_single_matchup(data: Any) -> dict | None:
    """Extract a lone competition match when FotMob has no table/bracket."""
    candidates: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            home = node.get("home")
            away = node.get("away")
            match_id = node.get("matchId") or node.get("match_id")
            if match_id is None:
                match_id = node.get("id")
            if (
                isinstance(home, dict)
                and isinstance(away, dict)
                and home.get("id") is not None
                and away.get("id") is not None
                and match_id is not None
            ):
                key = str(match_id)
                if key not in seen:
                    seen.add(key)
                    candidates.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(data)
    if len(candidates) != 1:
        return None

    raw = candidates[0]
    home = raw.get("home") or {}
    away = raw.get("away") or {}
    home_score = _as_int(raw.get("homeScore"))
    away_score = _as_int(raw.get("awayScore"))
    if home_score is None:
        home_score = _as_int(home.get("score"))
    if away_score is None:
        away_score = _as_int(away.get("score"))

    return {
        "number": 1,
        "homeTeamId": str(home.get("id") or ""),
        "awayTeamId": str(away.get("id") or ""),
        "homeTeam": _clean(home.get("name") or home.get("longName")),
        "awayTeam": _clean(away.get("name") or away.get("longName")),
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": str(raw.get("winner") or ""),
        "bestOf": 1,
        "tbdTeam1": False,
        "tbdTeam2": False,
        "matches": [{"matchId": str(raw.get("matchId") or raw.get("match_id") or raw.get("id"))}],
        "aggregatedResult": {},
        "aggregatedWinner": None,
        "aggregatedLoser": None,
        "penaltyScore": raw.get("penaltyScore") if isinstance(raw.get("penaltyScore"), dict) else None,
        "raw": raw,
    }


def _fetch_single_matchup(competition_id: str, season: str | None) -> dict | None:
    """Fallback for single-match competitions that expose no table/bracket."""
    params = {"id": str(competition_id)}
    if season:
        params["season"] = season
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/fixtures",
            params=params,
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            return None
        return _extract_single_matchup(payload)
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] {competition_id}: single-match fallback unavailable: {error}")
        return None


def _single_match_knockout(matchup: dict) -> list[dict]:
    return [{
        "stage": "فینال",
        "participantCount": 2,
        "matchups": [matchup],
        "raw": matchup.get("raw") or {},
    }]



def _extract_fixture_matchups(data: Any) -> list[dict]:
    """Collect FotMob fixtures while tolerating the different fixture schemas."""
    found: list[dict] = []
    seen: set[str] = set()

    def first_dict(node: dict, keys: tuple[str, ...]) -> dict | None:
        for key in keys:
            value = node.get(key)
            if isinstance(value, dict):
                return value
        return None

    def match_id_from(node: dict) -> str:
        for key in ("matchId", "match_id", "fixtureId", "fixture_id"):
            value = node.get(key)
            if value is not None:
                return str(value)
        nested = node.get("match")
        if isinstance(nested, dict):
            for key in ("matchId", "match_id", "id"):
                value = nested.get(key)
                if value is not None:
                    return str(value)
        value = node.get("id")
        return str(value) if value is not None else ""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            home = first_dict(node, ("home", "homeTeam", "home_team"))
            away = first_dict(node, ("away", "awayTeam", "away_team"))
            if home and away:
                match_id = match_id_from(node)
                if not match_id:
                    nested = node.get("match")
                    if isinstance(nested, dict):
                        match_id = match_id_from(nested)
                if match_id and match_id not in seen:
                    seen.add(match_id)
                    item = dict(node)
                    item["_fixture_home"] = home
                    item["_fixture_away"] = away
                    item["_fixture_match_id"] = match_id
                    item["_fixture_stage"] = (
                        node.get("stage")
                        or node.get("roundName")
                        or node.get("round")
                        or node.get("stageName")
                        or node.get("stage_name")
                        or node.get("round_name")
                        or node.get("roundInfo")
                    )
                    found.append(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found



def _fixture_stage_text(match: dict) -> str:
    value = match.get("_fixture_stage")
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("roundName")
            or value.get("stageName")
            or value.get("round")
        )
    return str(value or "").strip().lower()


def _fixture_score_value(team: dict, match: dict, side: str) -> int | None:
    candidates = [
        team.get("score"),
        team.get("currentScore"),
        team.get("displayScore"),
        team.get("goals"),
        match.get(f"{side}Score"),
        match.get(f"{side}_score"),
        match.get(f"{side}Goals"),
    ]
    for value in candidates:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        if isinstance(value, dict):
            for key in ("current", "display", "value", "score", "goals"):
                nested = value.get(key)
                if isinstance(nested, (int, float)):
                    return int(nested)
                if isinstance(nested, str) and nested.strip().lstrip("-").isdigit():
                    return int(nested)
    return None


def _fixture_penalty_score(match: dict) -> dict | None:
    value = match.get("penaltyScore") or match.get("penaltyScores")
    if isinstance(value, dict):
        home = value.get("home")
        away = value.get("away")
        if isinstance(home, dict):
            home = home.get("score") or home.get("value")
        if isinstance(away, dict):
            away = away.get("score") or away.get("value")
        if isinstance(home, (int, float)) and isinstance(away, (int, float)):
            return {"home": int(home), "away": int(away)}
    for container_key in ("shootout", "penalties", "penaltyShootout"):
        container = match.get(container_key)
        if isinstance(container, dict):
            home = container.get("home") or container.get("homeScore")
            away = container.get("away") or container.get("awayScore")
            if isinstance(home, (int, float)) and isinstance(away, (int, float)):
                return {"home": int(home), "away": int(away)}
    return None


def _normalize_fixture_match(match: dict) -> dict:
    home = match.get("_fixture_home") or match.get("home") or match.get("homeTeam") or {}
    away = match.get("_fixture_away") or match.get("away") or match.get("awayTeam") or {}
    match_id = match.get("_fixture_match_id") or match.get("matchId") or match.get("match_id") or match.get("id")
    return {
        "home": {
            "id": str(home.get("id") or home.get("teamId") or ""),
            "name": str(home.get("name") or home.get("teamName") or ""),
        },
        "away": {
            "id": str(away.get("id") or away.get("teamId") or ""),
            "name": str(away.get("name") or away.get("teamName") or ""),
        },
        "homeScore": _fixture_score_value(home, match, "home"),
        "awayScore": _fixture_score_value(away, match, "away"),
        "winner": str(match.get("winner") or ""),
        "bestOf": 1,
        "tbdTeam1": False,
        "tbdTeam2": False,
        "matches": [{"matchId": str(match_id)}],
        "aggregatedResult": {},
        "aggregatedWinner": None,
        "aggregatedLoser": None,
        "penaltyScore": _fixture_penalty_score(match),
        "raw": match,
    }





def _fetch_uefa_world_cup_playoffs(season: str | None) -> list[dict]:
    """Build the UEFA 2026 playoff tree from fixtures plus the official path draw.

    FotMob does not expose the bracket tree reliably, so the path relationship
    is defined here, while scores/results are read from FotMob fixtures.
    """
    params = {"id": "10195"}
    if season:
        params["season"] = season
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/fixtures",
            params=params,
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] 10195: UEFA playoff fixtures unavailable: {error}")
        return []

    fixtures = _extract_fixture_matchups(payload)
    by_pair: dict[frozenset[str], dict] = {}
    for fixture in fixtures:
        home = fixture.get("home") or {}
        away = fixture.get("away") or {}
        home_id = str(home.get("id") or home.get("teamId") or "")
        away_id = str(away.get("id") or away.get("teamId") or "")
        if home_id and away_id:
            by_pair[frozenset((home_id, away_id))] = fixture

    # Official 2026 draw: two semi-finals form each path, and their winners
    # meet in that path's final. The relationships are fixed before matches.
    team_ids = {
        "ایتالیا": "8204",
        "ایرلند شمالی": "10259",
        "ولز": "5790",
        "بوسنی و هرزگوین": "10106",
        "اوکراین": "6718",
        "سوئد": "8520",
        "لهستان": "8568",
        "آلبانی": "10024",
        "ترکیه": "6595",
        "رومانی": "9730",
        "اسلواکی": "8497",
        "کوزوو": "430156",
        "دانمارک": "8238",
        "مقدونیه شمالی": "8260",
        "چک": "8496",
        "ایرلند": "5791",
    }
    paths = [
        [("ایتالیا", "ایرلند شمالی"), ("ولز", "بوسنی و هرزگوین")],
        [("اوکراین", "سوئد"), ("لهستان", "آلبانی")],
        [("ترکیه", "رومانی"), ("اسلواکی", "کوزوو")],
        [("دانمارک", "مقدونیه شمالی"), ("چک", "ایرلند")],
    ]

    def normalize(fixture: dict) -> dict:
        return _normalize_fixture_match(fixture)

    semifinals: list[dict] = []
    winners_by_path: list[list[dict]] = []
    for path in paths:
        path_matches: list[dict] = []
        path_winners: list[dict] = []
        for home_name, away_name in path:
            key = frozenset((team_ids[home_name], team_ids[away_name]))
            fixture = by_pair.get(key)
            if fixture is None:
                print(f"[STANDINGS] 10195: missing fixture {home_name} vs {away_name}")
                return []
            match = normalize(fixture)
            path_matches.append(match)
            path_winners.append(match)
        winners_by_path.append(path_winners)
        semifinals.extend(path_matches)

    def winner_name(match: dict) -> tuple[str, str] | None:
        home_score = match.get("homeScore")
        away_score = match.get("awayScore")
        if not isinstance(home_score, (int, float)) or not isinstance(away_score, (int, float)):
            return None
        if home_score > away_score:
            return str(match["home"]["name"]), str(match["home"]["id"])
        if away_score > home_score:
            return str(match["away"]["name"]), str(match["away"]["id"])
        penalty = match.get("penaltyScore") or {}
        if isinstance(penalty, dict):
            hp = penalty.get("home")
            ap = penalty.get("away")
            if isinstance(hp, (int, float)) and isinstance(ap, (int, float)):
                if hp > ap:
                    return str(match["home"]["name"]), str(match["home"]["id"])
                if ap > hp:
                    return str(match["away"]["name"]), str(match["away"]["id"])
        return None

    finals: list[dict] = []
    for path_index, path_matches in enumerate(winners_by_path, 1):
        winners = [winner_name(match) for match in path_matches]
        final_fixture = None
        if all(w is not None for w in winners):
            ids = [w[1] for w in winners]
            final_fixture = by_pair.get(frozenset(ids))
        if final_fixture is not None:
            final_match = normalize(final_fixture)
        elif all(w is not None for w in winners):
            home_name, home_id = winners[0]
            away_name, away_id = winners[1]
            final_match = {
                "home": {"id": home_id, "name": home_name},
                "away": {"id": away_id, "name": away_name},
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": False,
                "tbdTeam2": False,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {"source": "derived-path", "path": path_index},
            }
        else:
            # Results are not complete yet: keep the path relationship visible
            # with placeholders instead of inventing a final pairing.
            final_match = {
                "home": {"id": "", "name": f"برنده بازی {path_index * 2 - 1}"},
                "away": {"id": "", "name": f"برنده بازی {path_index * 2}"},
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": True,
                "tbdTeam2": True,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {"source": "derived-path", "path": path_index},
            }
        finals.append(final_match)

    return [
        {
            "stage": "نیمه‌نهایی",
            "participantCount": 16,
            "matchups": semifinals,
            "raw": {"source": "fixtures+draw", "competitionId": "10195", "pathCount": 4},
        },
        {
            "stage": "فینال",
            "participantCount": 8,
            "matchups": finals,
            "raw": {"source": "fixtures+draw", "competitionId": "10195", "pathCount": 4},
        },
    ]


def _manual_uefa_world_cup_playoffs() -> list[dict]:
    """Static 2026 UEFA playoff bracket; FotMob does not expose the bracket tree."""
    team_ids = {
        "ایتالیا": "8204",
        "ایرلند شمالی": "10259",
        "ولز": "5790",
        "بوسنی و هرزگوین": "10106",
        "اوکراین": "6718",
        "سوئد": "8520",
        "لهستان": "8568",
        "آلبانی": "10024",
        "ترکیه": "6595",
        "رومانی": "9730",
        "اسلواکی": "8497",
        "کوزوو": "430156",
        "دانمارک": "8238",
        "مقدونیه شمالی": "8260",
        "چک": "8496",
        "ایرلند": "5791",
    }

    def match(
        home: str,
        away: str,
        home_score: int,
        away_score: int,
        home_penalty: int | None = None,
        away_penalty: int | None = None,
    ) -> dict:
        penalty = None
        if home_penalty is not None and away_penalty is not None:
            penalty = {"home": home_penalty, "away": away_penalty}
        return {
            "number": 0,
            "homeTeamId": team_ids[home],
            "awayTeamId": team_ids[away],
            "homeTeam": home,
            "awayTeam": away,
            "homeScore": home_score,
            "awayScore": away_score,
            "winner": "",
            "bestOf": 1,
            "tbdTeam1": False,
            "tbdTeam2": False,
            "matches": [],
            "aggregatedResult": {},
            "aggregatedWinner": None,
            "aggregatedLoser": None,
            "penaltyScore": penalty,
            "raw": {},
        }

    semifinal_pairs = [
        ("ایتالیا", "ایرلند شمالی", 2, 0, None, None),
        ("ولز", "بوسنی و هرزگوین", 1, 1, 2, 4),
        ("اوکراین", "سوئد", 1, 3, None, None),
        ("لهستان", "آلبانی", 2, 1, None, None),
        ("ترکیه", "رومانی", 1, 0, None, None),
        ("اسلواکی", "کوزوو", 3, 4, None, None),
        ("دانمارک", "مقدونیه شمالی", 4, 0, None, None),
        ("چک", "ایرلند", 2, 2, 4, 3),
    ]
    final_pairs = [
        ("بوسنی و هرزگوین", "ایتالیا", 1, 1, 4, 1),
        ("سوئد", "لهستان", 3, 2, None, None),
        ("کوزوو", "ترکیه", 0, 1, None, None),
        ("چک", "دانمارک", 2, 2, 3, 1),
    ]

    semifinals = [
        dict(match("home", "away", 0, 0), number=index + 1)
        for index, match in enumerate([])
    ]
    semifinals = []
    for index, item in enumerate(semifinal_pairs, 1):
        m = match(*item)
        m["number"] = index
        semifinals.append(m)

    finals = []
    for index, item in enumerate(final_pairs, 1):
        m = match(*item)
        m["number"] = index
        finals.append(m)

    return [
        {
            "stage": "نیمه‌نهایی",
            "participantCount": 16,
            "matchups": semifinals,
            "raw": {"source": "manual", "competitionId": "10195", "pathCount": 4},
        },
        {
            "stage": "فینال",
            "participantCount": 8,
            "matchups": finals,
            "raw": {"source": "manual", "competitionId": "10195", "pathCount": 4},
        },
    ]


def fetch_standings(competition_id: str, season: str | None = None) -> dict:
    competition_id = str(competition_id)
    if competition_id in CHART_EXCLUDED_COMPETITION_IDS:
        raise RuntimeError(
            f"Competition {competition_id} is intentionally excluded from standings/knockout chart rendering."
        )

    params = {"id": competition_id}
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
    if competition_id == "10195" and not knockout_rounds:
        knockout_rounds = _fetch_uefa_world_cup_playoffs(season)
        if knockout_rounds:
            print("[STANDINGS] 10195: UEFA playoff fallback -> semifinals + finals")
        else:
            knockout_rounds = _manual_uefa_world_cup_playoffs()
            print("[STANDINGS] 10195: manual UEFA playoff bracket -> semifinals + finals")
    _enrich_knockout_penalties(knockout_rounds)

    # Some super cups and one-off competitions have no standings or bracket
    # in FotMob at all. If the competition has exactly one fixture, represent
    # that match as a one-card final instead of treating the competition as an
    # error. Competitions with multiple fixtures still need real knockout data.
    if not tables and not knockout_rounds:
        single_match = _fetch_single_matchup(competition_id, season)
        if single_match is not None:
            knockout_rounds = _single_match_knockout(single_match)
            print(f"[STANDINGS] {competition_id}: single-match fallback -> final")
        else:
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


def _extract_single_matchup(data: Any) -> dict | None:
    """Extract a lone competition match when FotMob has no table/bracket."""
    candidates: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            home = node.get("home")
            away = node.get("away")
            match_id = node.get("matchId") or node.get("match_id")
            if match_id is None:
                match_id = node.get("id")
            if (
                isinstance(home, dict)
                and isinstance(away, dict)
                and home.get("id") is not None
                and away.get("id") is not None
                and match_id is not None
            ):
                key = str(match_id)
                if key not in seen:
                    seen.add(key)
                    candidates.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(data)
    if len(candidates) != 1:
        return None

    raw = candidates[0]
    home = raw.get("home") or {}
    away = raw.get("away") or {}
    home_score = _as_int(raw.get("homeScore"))
    away_score = _as_int(raw.get("awayScore"))
    if home_score is None:
        home_score = _as_int(home.get("score"))
    if away_score is None:
        away_score = _as_int(away.get("score"))

    return {
        "number": 1,
        "homeTeamId": str(home.get("id") or ""),
        "awayTeamId": str(away.get("id") or ""),
        "homeTeam": _clean(home.get("name") or home.get("longName")),
        "awayTeam": _clean(away.get("name") or away.get("longName")),
        "homeScore": home_score,
        "awayScore": away_score,
        "winner": str(raw.get("winner") or ""),
        "bestOf": 1,
        "tbdTeam1": False,
        "tbdTeam2": False,
        "matches": [{"matchId": str(raw.get("matchId") or raw.get("match_id") or raw.get("id"))}],
        "aggregatedResult": {},
        "aggregatedWinner": None,
        "aggregatedLoser": None,
        "penaltyScore": raw.get("penaltyScore") if isinstance(raw.get("penaltyScore"), dict) else None,
        "raw": raw,
    }


def _fetch_single_matchup(competition_id: str, season: str | None) -> dict | None:
    """Fallback for single-match competitions that expose no table/bracket."""
    params = {"id": str(competition_id)}
    if season:
        params["season"] = season
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/fixtures",
            params=params,
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            return None
        return _extract_single_matchup(payload)
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] {competition_id}: single-match fallback unavailable: {error}")
        return None


def _single_match_knockout(matchup: dict) -> list[dict]:
    return [{
        "stage": "فینال",
        "participantCount": 2,
        "matchups": [matchup],
        "raw": matchup.get("raw") or {},
    }]



def _extract_fixture_matchups(data: Any) -> list[dict]:
    """Recursively collect unique fixture-like matchups from a FotMob payload."""
    found: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            home = node.get("home") if isinstance(node.get("home"), dict) else None
            away = node.get("away") if isinstance(node.get("away"), dict) else None
            match_id = node.get("matchId") or node.get("match_id") or node.get("id")
            if home and away and match_id is not None:
                key = str(match_id)
                if key not in seen:
                    seen.add(key)
                    item = dict(node)
                    item["_fixture_stage"] = (
                        node.get("stage")
                        or node.get("roundName")
                        or node.get("round")
                        or node.get("stageName")
                        or node.get("stage_name")
                        or node.get("round_name")
                        or node.get("roundInfo")
                    )
                    found.append(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found


def _fixture_stage_text(match: dict) -> str:
    value = match.get("_fixture_stage")
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("roundName")
            or value.get("stageName")
            or value.get("round")
        )
    return str(value or "").strip().lower()


def _fixture_score_value(team: dict, match: dict, side: str) -> int | None:
    candidates = [
        team.get("score"),
        team.get("currentScore"),
        team.get("displayScore"),
        team.get("goals"),
        match.get(f"{side}Score"),
        match.get(f"{side}_score"),
        match.get(f"{side}Goals"),
    ]
    for value in candidates:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        if isinstance(value, dict):
            for key in ("current", "display", "value", "score", "goals"):
                nested = value.get(key)
                if isinstance(nested, (int, float)):
                    return int(nested)
                if isinstance(nested, str) and nested.strip().lstrip("-").isdigit():
                    return int(nested)
    return None


def _fixture_penalty_score(match: dict) -> dict | None:
    value = match.get("penaltyScore") or match.get("penaltyScores")
    if isinstance(value, dict):
        home = value.get("home")
        away = value.get("away")
        if isinstance(home, dict):
            home = home.get("score") or home.get("value")
        if isinstance(away, dict):
            away = away.get("score") or away.get("value")
        if isinstance(home, (int, float)) and isinstance(away, (int, float)):
            return {"home": int(home), "away": int(away)}
    for container_key in ("shootout", "penalties", "penaltyShootout"):
        container = match.get(container_key)
        if isinstance(container, dict):
            home = container.get("home") or container.get("homeScore")
            away = container.get("away") or container.get("awayScore")
            if isinstance(home, (int, float)) and isinstance(away, (int, float)):
                return {"home": int(home), "away": int(away)}
    return None


def _normalize_fixture_match(match: dict) -> dict:
    home = match.get("home") or {}
    away = match.get("away") or {}
    match_id = match.get("matchId") or match.get("match_id") or match.get("id")
    return {
        "home": {
            "id": str(home.get("id") or home.get("teamId") or ""),
            "name": str(home.get("name") or home.get("teamName") or "نامشخص"),
        },
        "away": {
            "id": str(away.get("id") or away.get("teamId") or ""),
            "name": str(away.get("name") or away.get("teamName") or "نامشخص"),
        },
        "homeScore": _fixture_score_value(home, match, "home"),
        "awayScore": _fixture_score_value(away, match, "away"),
        "winner": str(match.get("winner") or ""),
        "bestOf": 1,
        "tbdTeam1": False,
        "tbdTeam2": False,
        "matches": [{"matchId": str(match_id)}],
        "aggregatedResult": {},
        "aggregatedWinner": None,
        "aggregatedLoser": None,
        "penaltyScore": _fixture_penalty_score(match),
        "raw": match,
    }


def _fetch_uefa_world_cup_playoffs(season: str | None) -> list[dict]:
    """Build the UEFA 2026 playoff tree from fixtures plus the official path draw.

    FotMob does not expose the bracket tree reliably, so the path relationship
    is defined here, while scores/results are read from FotMob fixtures.
    """
    params = {"id": "10195"}
    if season:
        params["season"] = season
    try:
        response = requests.get(
            f"{FOTMOB_BASE_URL}/api/data/fixtures",
            params=params,
            headers=HEADERS,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        print(f"[STANDINGS] 10195: UEFA playoff fixtures unavailable: {error}")
        return []

    fixtures = _extract_fixture_matchups(payload)
    by_pair: dict[frozenset[str], dict] = {}
    for fixture in fixtures:
        home = fixture.get("home") or {}
        away = fixture.get("away") or {}
        home_id = str(home.get("id") or home.get("teamId") or "")
        away_id = str(away.get("id") or away.get("teamId") or "")
        if home_id and away_id:
            by_pair[frozenset((home_id, away_id))] = fixture

    # Official 2026 draw: two semi-finals form each path, and their winners
    # meet in that path's final. The relationships are fixed before matches.
    team_ids = {
        "ایتالیا": "8204",
        "ایرلند شمالی": "10259",
        "ولز": "5790",
        "بوسنی و هرزگوین": "10106",
        "اوکراین": "6718",
        "سوئد": "8520",
        "لهستان": "8568",
        "آلبانی": "10024",
        "ترکیه": "6595",
        "رومانی": "9730",
        "اسلواکی": "8497",
        "کوزوو": "430156",
        "دانمارک": "8238",
        "مقدونیه شمالی": "8260",
        "چک": "8496",
        "ایرلند": "5791",
    }
    paths = [
        [("ایتالیا", "ایرلند شمالی"), ("ولز", "بوسنی و هرزگوین")],
        [("اوکراین", "سوئد"), ("لهستان", "آلبانی")],
        [("ترکیه", "رومانی"), ("اسلواکی", "کوزوو")],
        [("دانمارک", "مقدونیه شمالی"), ("چک", "ایرلند")],
    ]

    def normalize(fixture: dict) -> dict:
        return _normalize_fixture_match(fixture)

    semifinals: list[dict] = []
    winners_by_path: list[list[dict]] = []
    for path in paths:
        path_matches: list[dict] = []
        path_winners: list[dict] = []
        for home_name, away_name in path:
            key = frozenset((team_ids[home_name], team_ids[away_name]))
            fixture = by_pair.get(key)
            if fixture is None:
                print(f"[STANDINGS] 10195: missing fixture {home_name} vs {away_name}")
                return []
            match = normalize(fixture)
            path_matches.append(match)
            path_winners.append(match)
        winners_by_path.append(path_winners)
        semifinals.extend(path_matches)

    def winner_name(match: dict) -> tuple[str, str] | None:
        home_score = match.get("homeScore")
        away_score = match.get("awayScore")
        if not isinstance(home_score, (int, float)) or not isinstance(away_score, (int, float)):
            return None
        if home_score > away_score:
            return str(match["home"]["name"]), str(match["home"]["id"])
        if away_score > home_score:
            return str(match["away"]["name"]), str(match["away"]["id"])
        penalty = match.get("penaltyScore") or {}
        if isinstance(penalty, dict):
            hp = penalty.get("home")
            ap = penalty.get("away")
            if isinstance(hp, (int, float)) and isinstance(ap, (int, float)):
                if hp > ap:
                    return str(match["home"]["name"]), str(match["home"]["id"])
                if ap > hp:
                    return str(match["away"]["name"]), str(match["away"]["id"])
        return None

    finals: list[dict] = []
    for path_index, path_matches in enumerate(winners_by_path, 1):
        winners = [winner_name(match) for match in path_matches]
        final_fixture = None
        if all(w is not None for w in winners):
            ids = [w[1] for w in winners]
            final_fixture = by_pair.get(frozenset(ids))
        if final_fixture is not None:
            final_match = normalize(final_fixture)
        elif all(w is not None for w in winners):
            home_name, home_id = winners[0]
            away_name, away_id = winners[1]
            final_match = {
                "home": {"id": home_id, "name": home_name},
                "away": {"id": away_id, "name": away_name},
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": False,
                "tbdTeam2": False,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {"source": "derived-path", "path": path_index},
            }
        else:
            # Results are not complete yet: keep the path relationship visible
            # with placeholders instead of inventing a final pairing.
            final_match = {
                "home": {"id": "", "name": f"برنده بازی {path_index * 2 - 1}"},
                "away": {"id": "", "name": f"برنده بازی {path_index * 2}"},
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": True,
                "tbdTeam2": True,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {"source": "derived-path", "path": path_index},
            }
        finals.append(final_match)

    return [
        {
            "stage": "نیمه‌نهایی",
            "participantCount": 16,
            "matchups": semifinals,
            "raw": {"source": "fixtures+draw", "competitionId": "10195", "pathCount": 4},
        },
        {
            "stage": "فینال",
            "participantCount": 8,
            "matchups": finals,
            "raw": {"source": "fixtures+draw", "competitionId": "10195", "pathCount": 4},
        },
    ]


def _manual_uefa_world_cup_playoffs() -> list[dict]:
    """Static 2026 UEFA playoff bracket; FotMob does not expose the bracket tree."""
    team_ids = {
        "ایتالیا": "8204",
        "ایرلند شمالی": "10259",
        "ولز": "5790",
        "بوسنی و هرزگوین": "10106",
        "اوکراین": "6718",
        "سوئد": "8520",
        "لهستان": "8568",
        "آلبانی": "10024",
        "ترکیه": "6595",
        "رومانی": "9730",
        "اسلواکی": "8497",
        "کوزوو": "430156",
        "دانمارک": "8238",
        "مقدونیه شمالی": "8260",
        "چک": "8496",
        "ایرلند": "5791",
    }

    def match(
        home: str,
        away: str,
        home_score: int,
        away_score: int,
        home_penalty: int | None = None,
        away_penalty: int | None = None,
    ) -> dict:
        penalty = None
        if home_penalty is not None and away_penalty is not None:
            penalty = {"home": home_penalty, "away": away_penalty}
        return {
            "number": 0,
            "homeTeamId": team_ids[home],
            "awayTeamId": team_ids[away],
            "homeTeam": home,
            "awayTeam": away,
            "homeScore": home_score,
            "awayScore": away_score,
            "winner": "",
            "bestOf": 1,
            "tbdTeam1": False,
            "tbdTeam2": False,
            "matches": [],
            "aggregatedResult": {},
            "aggregatedWinner": None,
            "aggregatedLoser": None,
            "penaltyScore": penalty,
            "raw": {},
        }

    semifinal_pairs = [
        ("ایتالیا", "ایرلند شمالی", 2, 0, None, None),
        ("ولز", "بوسنی و هرزگوین", 1, 1, 2, 4),
        ("اوکراین", "سوئد", 1, 3, None, None),
        ("لهستان", "آلبانی", 2, 1, None, None),
        ("ترکیه", "رومانی", 1, 0, None, None),
        ("اسلواکی", "کوزوو", 3, 4, None, None),
        ("دانمارک", "مقدونیه شمالی", 4, 0, None, None),
        ("چک", "ایرلند", 2, 2, 4, 3),
    ]
    final_pairs = [
        ("بوسنی و هرزگوین", "ایتالیا", 1, 1, 4, 1),
        ("سوئد", "لهستان", 3, 2, None, None),
        ("کوزوو", "ترکیه", 0, 1, None, None),
        ("چک", "دانمارک", 2, 2, 3, 1),
    ]

    semifinals = [
        dict(match("home", "away", 0, 0), number=index + 1)
        for index, match in enumerate([])
    ]
    semifinals = []
    for index, item in enumerate(semifinal_pairs, 1):
        m = match(*item)
        m["number"] = index
        semifinals.append(m)

    finals = []
    for index, item in enumerate(final_pairs, 1):
        m = match(*item)
        m["number"] = index
        finals.append(m)

    return [
        {
            "stage": "نیمه‌نهایی",
            "participantCount": 16,
            "matchups": semifinals,
            "raw": {"source": "manual", "competitionId": "10195", "pathCount": 4},
        },
        {
            "stage": "فینال",
            "participantCount": 8,
            "matchups": finals,
            "raw": {"source": "manual", "competitionId": "10195", "pathCount": 4},
        },
    ]


def fetch_standings(competition_id: str, season: str | None = None) -> dict:
    competition_id = str(competition_id)
    if competition_id in CHART_EXCLUDED_COMPETITION_IDS:
        raise RuntimeError(
            f"Competition {competition_id} is intentionally excluded from standings/knockout chart rendering."
        )

    params = {"id": competition_id}
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
    if competition_id == "10195" and not knockout_rounds:
        knockout_rounds = _fetch_uefa_world_cup_playoffs(season)
        if knockout_rounds:
            print("[STANDINGS] 10195: UEFA playoff fallback -> semifinals + finals")
        else:
            knockout_rounds = _manual_uefa_world_cup_playoffs()
            print("[STANDINGS] 10195: manual UEFA playoff bracket -> semifinals + finals")
    _enrich_knockout_penalties(knockout_rounds)

    # Some super cups and one-off competitions have no standings or bracket
    # in FotMob at all. If the competition has exactly one fixture, represent
    # that match as a one-card final instead of treating the competition as an
    # error. Competitions with multiple fixtures still need real knockout data.
    if not tables and not knockout_rounds:
        single_match = _fetch_single_matchup(competition_id, season)
        if single_match is not None:
            knockout_rounds = _single_match_knockout(single_match)
            print(f"[STANDINGS] {competition_id}: single-match fallback -> final")
        else:
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
