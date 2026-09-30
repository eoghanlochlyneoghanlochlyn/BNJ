import datetime as dt
import tempfile
import unittest
from pathlib import Path

from standings import _extract_knockout, _extract_tables, _knockout_stage_label, _normalize_rows, all_groups_complete, group_stage_complete, has_knockout, is_grouped_standings
import standings_renderer as standings_renderer_module
from standings_renderer import _ensure_full_knockout_bracket, _group_display_name, _is_placeholder_team, render_group_standings, render_knockout_standings, render_standings


class StandingsTests(unittest.TestCase):
    def test_extract_knockout_rounds(self):
        payload = {"playoff": {"rounds": [
            {"participantCount": 16, "stage": "playoff", "matchups": [
                {"drawOrder": 1, "homeTeamId": 9829, "awayTeamId": 9847,
                 "homeTeam": "Monaco", "awayTeam": "Paris Saint-Germain",
                 "homeScore": 4, "awayScore": 5, "bestOf": 2,
                 "aggregatedResult": {"homeScore": 4, "awayScore": 5},
                 "penaltyScore": {"home": 3, "away": 4}}
            ]},
            {"participantCount": 8, "stage": "quarterfinal", "matchups": [
                {"drawOrder": 1, "homeTeamId": 9825, "awayTeamId": 8456,
                 "homeTeam": "Arsenal", "awayTeam": "Manchester City",
                 "bestOf": 2, "tbdTeam1": False, "tbdTeam2": True}
            ]}
        ]}}
        rounds = _extract_knockout(payload)
        self.assertEqual(len(rounds), 2)
        self.assertEqual(rounds[0]["stage"], "پلی‌آف")
        self.assertEqual(rounds[1]["stage"], "یک‌چهارم نهایی")
        self.assertEqual(rounds[0]["matchups"][0]["homeScore"], 4)
        self.assertEqual(rounds[0]["matchups"][0]["bestOf"], 2)
        self.assertEqual(rounds[0]["matchups"][0]["aggregatedResult"]["homeScore"], 4)
        self.assertEqual(rounds[0]["matchups"][0]["penaltyScore"]["away"], 4)
        self.assertTrue(has_knockout({"knockoutRounds": rounds}))

    def test_knockout_stage_label_from_participant_count(self):
        self.assertEqual(_knockout_stage_label({"participantCount": 16}), "یک‌هشتم نهایی")
        self.assertEqual(_knockout_stage_label({"participantCount": 8}), "یک‌چهارم نهایی")
        self.assertEqual(_knockout_stage_label({"participantCount": 4}), "نیمه‌نهایی")
        self.assertEqual(_knockout_stage_label({"participantCount": 2}), "فینال")

    def test_knockout_bracket_always_reaches_final(self):
        rounds = _extract_knockout({"playoff": {"rounds": [
            {"participantCount": 8, "stage": "quarterfinal", "matchups": [
                {"drawOrder": i, "homeTeamId": str(1000 + i * 2),
                 "awayTeamId": str(1001 + i * 2),
                 "homeTeam": f"Home {i}", "awayTeam": f"Away {i}",
                 "homeScore": 1, "awayScore": 0}
                for i in range(1, 5)
            ]},
            {"participantCount": 4, "stage": "semifinal", "matchups": [
                {"drawOrder": i, "homeTeamId": str(2000 + i * 2),
                 "awayTeamId": str(2001 + i * 2),
                 "homeTeam": f"SF Home {i}", "awayTeam": f"SF Away {i}",
                 "homeScore": 2, "awayScore": 1}
                for i in range(1, 3)
            ]}
        ]}})
        full = _ensure_full_knockout_bracket(rounds)
        self.assertEqual(
            [item["stage"] for item in full],
            ["یک‌چهارم نهایی", "نیمه‌نهایی", "فینال"],
        )
        self.assertEqual(len(full[-1]["matchups"]), 1)
        self.assertTrue(full[-1]["placeholder"])
        self.assertTrue(full[-1]["matchups"][0]["tbdTeam1"])

    def test_render_knockout_poster(self):
        rounds = _extract_knockout({"playoff": {"rounds": [
            {"participantCount": 16, "stage": "round of 16", "matchups": [
                {"drawOrder": 1, "homeTeamId": "9825", "awayTeamId": "8456",
                 "homeTeam": "Arsenal", "awayTeam": "Manchester City",
                 "homeScore": 3, "awayScore": 2, "bestOf": 1}
            ]},
            {"participantCount": 8, "stage": "quarterfinal", "matchups": [
                {"drawOrder": 1, "homeTeamId": "9825", "awayTeamId": "8456",
                 "homeTeam": "Arsenal", "awayTeam": "Manchester City",
                 "homeScore": 5, "awayScore": 4, "bestOf": 2}
            ]}
        ]}})
        data = {"competitionId": "42", "competitionName": "Champions League",
                "season": "2025/2026", "knockoutRounds": rounds}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "knockout.png"
            render_knockout_standings(data, dt.date(2026, 9, 29), output)
            self.assertTrue(output.exists())
            from PIL import Image
            with Image.open(output) as image:
                self.assertEqual(image.size[0], 1600)
                self.assertGreater(image.size[1], 1500)

    def test_knockout_placeholder_detection(self):
        self.assertTrue(_is_placeholder_team("1B", "1871"))
        self.assertTrue(_is_placeholder_team("3ADEF", "941364"))
        self.assertTrue(_is_placeholder_team("Winner EF 3", "1871"))
        self.assertTrue(_is_placeholder_team("Loser QF 1", "941364"))
        self.assertTrue(_is_placeholder_team("TBD", "1871"))
        self.assertTrue(_is_placeholder_team("", "1871", tbd=True))
        self.assertFalse(_is_placeholder_team("Arsenal", "9825"))

    def test_knockout_placeholders_never_request_logos(self):
        rounds = _extract_knockout({"playoff": {"rounds": [
            {"participantCount": 2, "stage": "final", "matchups": [
                {
                    "drawOrder": 1,
                    "homeTeamId": "1871",
                    "awayTeamId": "941364",
                    "homeTeam": "1B",
                    "awayTeam": "3ADEF",
                    "homeScore": None,
                    "awayScore": None,
                    "tbdTeam1": True,
                    "tbdTeam2": True,
                }
            ]}
        ]}})
        data = {
            "competitionId": "50",
            "competitionName": "European Championship",
            "season": "2028",
            "knockoutRounds": rounds,
        }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "placeholder-bracket.png"
            original_logo_loader = standings_renderer_module._team_logo

            def fail_if_logo_is_requested(_team_id):
                raise AssertionError("placeholder team triggered a logo request")

            standings_renderer_module._team_logo = fail_if_logo_is_requested
            try:
                render_knockout_standings(
                    data, dt.date(2026, 9, 30), output
                )
            finally:
                standings_renderer_module._team_logo = original_logo_loader

            self.assertTrue(output.exists())

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

    def test_auxiliary_best_third_table_does_not_block_completion(self):
        group_rows = [
            {"played": 3},
            {"played": 3},
            {"played": 3},
            {"played": 3},
        ]
        tables = [
            {"group": "Grp. A", "rows": group_rows},
            {"group": "Grp. B", "rows": group_rows},
            {"group": "Best 3rd placed teams", "rows": [{"played": None}] * 12},
        ]
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

    def test_best_third_title_is_persian(self):
        self.assertEqual(_group_display_name("Best 3rd placed teams"), "برترین تیم های سوم")

    def test_render_vertical_combined_group_poster_with_all_third_place_teams(self):
        def row(i):
            return {
                "rank": i, "teamId": str(9000 + i), "teamName": f"Team {i}",
                "played": 3, "wins": 2, "draws": 0, "losses": 1,
                "goalsFor": 5, "goalsAgainst": 3, "goalDiff": 2, "points": 6,
            }

        tables = [
            {"group": f"Grp. {chr(65 + i)}", "rows": [row(j) for j in range(1, 5)]}
            for i in range(12)
        ]
        tables.append({
            "group": "Best 3rd placed teams",
            "rows": [row(i) for i in range(1, 13)],
        })
        data = {
            "competitionId": "77", "competitionName": "World Cup",
            "season": "2026", "tables": tables,
        }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "combined.png"
            render_standings(data, dt.date(2026, 9, 29), output)
            self.assertTrue(output.exists())
            from PIL import Image
            with Image.open(output) as image:
                self.assertEqual(image.size[0], 1600)
                self.assertGreater(image.size[1], 6000)

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
