from zoneinfo import ZoneInfo

IRAN_TIMEZONE = ZoneInfo("Asia/Tehran")

# Exactly the 15 team IDs supplied by the user.
PRIORITY_TEAM_IDS = {
    "8650", "9825", "8456", "10260", "8455",
    "8586", "9885", "8564", "8636", "9823",
    "9789", "9847", "8633", "8634", "9906",
}

# Exactly the numeric competition IDs supplied by the user.
# mode, stage, extra_teams, extra_country and aliases are intentionally ignored.
COMPETITION_IDS = {
    "77", "50", "9806", "44", "290", "289", "297", "525", "9469",
    "526", "45", "42", "73", "10216", "78", "10703", "247", "139",
    "11015", "8924", "207", "74", "132", "133", "209", "141", "134",
    "138", "10607", "10199",
}

# Numeric FotMob IDs for the five requested domestic leagues.
MAJOR_LEAGUE_IDS = {"47", "87", "55", "54", "53"}

# Kept only for compatibility with older imports elsewhere in the project.
PRIORITY_TEAMS = set()
COMPETITION_KEYWORDS = set()
