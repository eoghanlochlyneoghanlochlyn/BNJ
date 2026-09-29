import datetime as dt
import tempfile
import unittest
from pathlib import Path

from standings import _extract_tables, _normalize_rows, all_groups_complete, group_stage_complete, is_grouped_standings
from standings_renderer import render_group_standings, render_standings


class StandingsTests(unittest.TestCase):
    def test_normalize_fotmob_table_rows(self):
        payload = {
            "table": {
                "all": [
                    {
                        "idx": 1,
                        "name": "Arsenal",
                        "id": 9825,
                        "played": 6,
                        "wins": 5,
                        "draws": 1,
                        "losses": 0,
                        "scoresStr": "14-4",
                        "goalConDiff": 10,
                        "pts": 16,
                    }
                ]
            }
        }
        rows = _normalize_rows(payload["table"])
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["teamId"], "9825")
        self.assertEqual(rows[0]["goalsFor"], 14)
        self.assertEqual(rows[0]["goalsAgainst"], 4)
        self.assertEqual(rows[0]["goalDiff"], 10)
        self.assertEqual(rows[0]["points"], 16)

    def test_extract_multiple_real_tables(self):
        payload = {
            "table": [
                {"data": {"table": {"all": [
                    {"idx": 1, "id": 1, "name": "A", "played": 1, "pts": 3}
                ]}}},
                {"data": {"table": {"all": [
                    {"idx": 1, "id": 2, "name": "B", "played": 1, "pts": 3}
                ]}}},
            ]
        }
        tables = _extract_tables(payload)
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[0]["rows"][0]["teamId"], "1")
        self.assertEqual(tables[1]["rows"][0]["teamId"], "2")

    def test_group_name_extraction(self):
        payload = {
            "table": [
                {"data": {"leagueName": "Group A", "table": {"all": [
                    {"idx": 1, "id": 1, "name": "A", "played": 3, "pts": 9},
                    {"idx": 2, "id": 2, "name": "B", "played": 3, "pts": 6},
                    {"idx": 3, "id": 3, "name": "C", "played": 3, "pts": 3},
                    {"idx": 4, "id": 4, "name": "D", "played": 3, "pts": 0},
                ]}}},
                {"data": {"leagueName": "Group B", "table": {"all": [
                    {"idx": 1, "id": 5, "name": "E", "played": 3, "pts": 9},
                    {"idx": 2, "id": 6, "name": "F", "played": 3, "pts": 6},
                    {"idx": 3, "id": 7, "name": "G", "played": 3, "pts": 3},
                    {"idx": 4, "id": 8, "name": "H", "played": 3, "pts": 0},
                ]}}},
            ]
        }
        tables = _extract_tables(payload)
        self.assertEqual([table["group"] for table in tables], ["Group A", "Group B"])
        self.assertTrue(is_grouped_standings({"tables": tables}))
        self.assertTrue(group_stage_complete(tables[0]))
        self.assertTrue(all_groups_complete({"tables": tables}))

    def test_group_stage_not_complete_when_a_team_is_missing_a_match(self):
        table = {
            "rows": [
                {"played": 3},
                {"played": 3},
                {"played": 2},
                {"played": 3},
            ]
        }
        self.assertFalse(group_stage_complete(table))
        self.assertFalse(all_groups_complete({"tables": [table, table]}))

    def test_render_individual_group(self):
        rows = []
        for i in range(1, 5):
            rows.append({
                "rank": i,
                "teamId": str(8000 + i),
                "teamName": f"Team {i}",
                "played": 3,
                "wins": 2,
                "draws": 0,
                "losses": 1,
                "goalsFor": 5,
                "goalsAgainst": 3,
                "goalDiff": 2,
                "points": 6,
            })
        data = {
            "competitionId": "50",
            "competitionName": "European Championship",
            "season": "2026",
            "tables": [{"group": "Group B", "rows": rows}],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "group-b.png"
            render_group_standings(data, data["tables"][0], dt.date(2026, 9, 29), output)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1000)

    def test_render_realistic_league_table(self):
        rows = []
        for i in range(1, 21):
            rows.append(
                {
                    "rank": i,
                    "teamId": str(8000 + i),
                    "teamName": f"Team {i}",
                    "played": 10,
                    "wins": 5,
                    "draws": 2,
                    "losses": 3,
                    "goalsFor": 18,
                    "goalsAgainst": 12,
                    "goalDiff": 6,
                    "points": 17,
                }
            )

        data = {
            "competitionId": "47",
            "competitionName": "Premier League",
            "season": "2026/2027",
            "tables": [{"group": "", "rows": rows}],
        }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "standings.png"
            render_standings(data, dt.date(2026, 9, 29), output)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1000)

            from PIL import Image
            with Image.open(output) as image:
                self.assertEqual(image.mode, "RGB")
                self.assertGreater(image.size[1], 1800)


if __name__ == "__main__":
    unittest.main()
