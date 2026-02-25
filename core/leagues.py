"""League and country definitions with football-data.co.uk codes."""

from datetime import date


def get_current_season_code() -> str:
    """Return the football-data.co.uk season code (e.g. '2526' for 2025-26).

    Football seasons start in August, so anything before August belongs
    to the previous season cycle.
    """
    today = date.today()
    year = today.year
    if today.month < 8:  # Before August → season started previous year
        start_year = year - 1
    else:
        start_year = year
    end_year = start_year + 1
    return f"{start_year % 100:02d}{end_year % 100:02d}"


def get_past_season_codes(n_seasons: int) -> list[str]:
    """Return season codes for the current + N-1 previous seasons.

    E.g. n_seasons=5 in Feb 2026 → ['2526', '2425', '2324', '2223', '2122']
    Most recent first.
    """
    today = date.today()
    year = today.year
    if today.month < 8:
        start_year = year - 1
    else:
        start_year = year

    codes = []
    for i in range(n_seasons):
        sy = start_year - i
        ey = sy + 1
        codes.append(f"{sy % 100:02d}{ey % 100:02d}")
    return codes


def season_display(code) -> str:
    """Convert season code to display string: '2526' → '2025-26'.

    Accepts str, int, or numpy integer (e.g. 1819, '2526').
    """
    code = str(code)
    s = int(code[:2])
    e = int(code[2:])
    # Handle century boundary (e.g. 9900 → 1999-00)
    century_s = 2000 if s < 50 else 1900
    return f"{century_s + s}-{e:02d}"


# Each league entry: display name → dict with football-data code and team count
# fixturedownload_slug is used as a backup fixture source
COUNTRIES = {
    "England": {
        "Premier League": {"code": "E0", "teams": 20, "fd_slug": "epl"},
        "Championship": {"code": "E1", "teams": 24, "fd_slug": "championship"},
        "League One": {"code": "E2", "teams": 24},
        "League Two": {"code": "E3", "teams": 24},
    },
    "Germany": {
        "Bundesliga": {"code": "D1", "teams": 18, "fd_slug": "bundesliga"},
        "2. Bundesliga": {"code": "D2", "teams": 18},
    },
    "Spain": {
        "La Liga": {"code": "SP1", "teams": 20, "fd_slug": "la-liga"},
        "Segunda Division": {"code": "SP2", "teams": 22},
    },
    "Italy": {
        "Serie A": {"code": "I1", "teams": 20, "fd_slug": "serie-a"},
        "Serie B": {"code": "I2", "teams": 20},
    },
    "France": {
        "Ligue 1": {"code": "F1", "teams": 18, "fd_slug": "ligue-1"},
        "Ligue 2": {"code": "F2", "teams": 18},
    },
}


def get_fd_slug(league_code: str) -> str | None:
    """Get fixturedownload.com URL slug for a league code."""
    for leagues in COUNTRIES.values():
        for info in leagues.values():
            if info["code"] == league_code:
                return info.get("fd_slug")
    return None


# Team name mapping: fixturedownload.com → football-data.co.uk
# Only need entries where names differ
FD_TEAM_MAP = {
    # EPL
    "Man Utd": "Man United",
    "Spurs": "Tottenham",
    "Nott'm Forest": "Nott'm Forest",
    # La Liga
    "Atlético Madrid": "Ath Madrid",
    "Athletic Bilbao": "Ath Bilbao",
    "Real Betis": "Betis",
    "Rayo Vallecano": "Vallecano",
    "Celta Vigo": "Celta",
    # Bundesliga
    "Bayer Leverkusen": "Leverkusen",
    "Bayern Munich": "Bayern Munich",
    "RB Leipzig": "RB Leipzig",
    "Borussia Dortmund": "Dortmund",
    "Borussia M'gladbach": "M'gladbach",
    # Serie A
    "AC Milan": "Milan",
    "Inter Milan": "Inter",
    # Ligue 1
    "Paris Saint Germain": "Paris SG",
}

BASE_URL = "https://www.football-data.co.uk/mmz4281"


def get_results_url(code: str, season: str | None = None) -> str:
    """Build the football-data.co.uk CSV URL for a league's season results."""
    if season is None:
        season = get_current_season_code()
    return f"{BASE_URL}/{season}/{code}.csv"


def get_league_info(country: str, league: str) -> dict | None:
    """Return the info dict for a league, or None if not found."""
    return COUNTRIES.get(country, {}).get(league)


def get_all_league_codes() -> dict[str, str]:
    """Return a flat mapping of football-data Div codes to display names."""
    result = {}
    for country, leagues in COUNTRIES.items():
        for league_name, info in leagues.items():
            result[info["code"]] = f"{league_name} ({country})"
    return result
