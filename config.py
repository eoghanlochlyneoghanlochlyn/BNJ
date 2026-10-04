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
    "11015", "222", "8924", "207", "74", "132", "133", "209", "141", "134",
    "138", "10195", "10199", "9809", "9807",
}

# Numeric FotMob IDs for competitions that should not produce a standings/knockout poster.
# FIFA Intercontinental Cup (10703) is intentionally excluded because FotMob
# exposes its structure in a way that does not render correctly as a bracket.
CHART_EXCLUDED_COMPETITION_IDS = {"10703"}

# Numeric FotMob IDs for the five requested domestic leagues.
MAJOR_LEAGUE_IDS = {"47", "87", "55", "54", "53"}

# Kept only for compatibility with older imports elsewhere in the project.
PRIORITY_TEAMS = set()
COMPETITION_KEYWORDS = set()
