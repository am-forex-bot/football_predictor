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


# Each league entry: display name → dict with football-data code and team count
COUNTRIES = {
    "England": {
        "Premier League": {"code": "E0", "teams": 20},
        "Championship": {"code": "E1", "teams": 24},
        "League One": {"code": "E2", "teams": 24},
        "League Two": {"code": "E3", "teams": 24},
    },
    "Germany": {
        "Bundesliga": {"code": "D1", "teams": 18},
        "2. Bundesliga": {"code": "D2", "teams": 18},
    },
    "Spain": {
        "La Liga": {"code": "SP1", "teams": 20},
        "Segunda Division": {"code": "SP2", "teams": 22},
    },
    "Italy": {
        "Serie A": {"code": "I1", "teams": 20},
        "Serie B": {"code": "I2", "teams": 20},
    },
    "France": {
        "Ligue 1": {"code": "F1", "teams": 18},
        "Ligue 2": {"code": "F2", "teams": 18},
    },
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
