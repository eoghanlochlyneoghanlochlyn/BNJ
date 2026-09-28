"""Regression checks for the shared fixtures/results poster logic."""
import unittest
from renderer import (
    _competition_name, _competition_group_key, _competition_accent,
    _match_stage, _group_matches,
)


class SharedPosterTests(unittest.TestCase):
    def test_world_cups_separate_by_numeric_id(self):
        world = {"leagueId": "77", "competitionName": "World Cup"}
        clubs = {"leagueId": "78", "competitionName": "World Cup"}
        self.assertEqual(_competition_name(world), "جام جهانی")
        self.assertEqual(_competition_name(clubs), "جام جهانی باشگاه‌ها")
        self.assertNotEqual(_competition_group_key(world), _competition_group_key(clubs))
        self.assertEqual(len(_group_matches([world, clubs])), 2)

    def test_knockout_translations(self):
        cases = {
            "1/16": "یک‌شانزدهم نهایی",
            "1/8": "یک‌هشتم نهایی",
            "1/4": "یک‌چهارم نهایی",
            "1/2": "نیمه‌نهایی",
            "Round of 32": "یک‌شانزدهم نهایی",
            "Round of 16": "یک‌هشتم نهایی",
            "Quarter-finals": "یک‌چهارم نهایی",
            "Semi-finals": "نیمه‌نهایی",
            "Final": "فینال",
            "Week 7": "هفته ۷",
        }
        for raw, expected in cases.items():
            with self.subTest(stage=raw):
                self.assertEqual(_match_stage({"stage": raw}), expected)

    def test_colors_stable_and_distinct(self):
        first = {"leagueId": "77", "competitionName": "World Cup"}
        second = {"leagueId": "78", "competitionName": "World Cup"}
        self.assertEqual(_competition_accent(first), _competition_accent(dict(first)))
        self.assertNotEqual(_competition_accent(first), _competition_accent(second))
        for color in (_competition_accent(first), _competition_accent(second)):
            self.assertTrue(all(0 <= channel <= 255 for channel in color))


if __name__ == "__main__":
    unittest.main()
