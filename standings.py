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
    if not tables:
        raise RuntimeError(
            f"No standings table found for FotMob competition {competition_id}. "
            "This competition may use a group/league-phase/knockout structure "
            "that will be handled by the next standings modules."
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
