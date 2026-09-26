from zoneinfo import ZoneInfo

IRAN_TIMEZONE = ZoneInfo("Asia/Tehran")

# Every team explicitly present in the supplied selection list.
PRIORITY_TEAM_IDS = {
    "8650", "9825", "8456", "10260", "8455",
    "8586", "9885", "8564", "8636", "9823",
    "9789", "9847", "8633", "8634", "9906",
}

# Teams named in extra_teams / extra_country rules are also explicitly included.
EXTRA_PRIORITY_TEAM_NAMES = {
    "Brazil", "Argentina",
    "England", "France", "Portugal", "Belgium", "Netherlands",
    "Germany", "Croatia", "Italy", "Iran",
}

# Every supplied competition is included at every stage.
# Old mode/stage restrictions are intentionally ignored.
COMPETITION_IDS = {
    "77", "50", "9806", "44", "290", "289", "297", "525", "9469",
    "526", "45", "42", "73", "10216", "78", "10703", "247", "139",
    "11015", "8924", "207", "74", "132", "133", "209", "141", "134",
    "138", "10607", "10199",
}

# Kept for compatibility with older imports.
PRIORITY_TEAMS = set(EXTRA_PRIORITY_TEAM_NAMES)
MAJOR_LEAGUES = set()
COMPETITION_KEYWORDS = set()
