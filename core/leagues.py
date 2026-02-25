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
# of_json is the openfootball/football.json filename for fixture data
COUNTRIES = {
    "England": {
        "Premier League": {"code": "E0", "teams": 20, "of_json": "en.1.json"},
        "Championship": {"code": "E1", "teams": 24, "of_json": "en.2.json"},
        "League One": {"code": "E2", "teams": 24},
        "League Two": {"code": "E3", "teams": 24},
    },
    "Germany": {
        "Bundesliga": {"code": "D1", "teams": 18, "of_json": "de.1.json"},
        "2. Bundesliga": {"code": "D2", "teams": 18, "of_json": "de.2.json"},
    },
    "Spain": {
        "La Liga": {"code": "SP1", "teams": 20, "of_json": "es.1.json"},
        "Segunda Division": {"code": "SP2", "teams": 22, "of_json": "es.2.json"},
    },
    "Italy": {
        "Serie A": {"code": "I1", "teams": 20, "of_json": "it.1.json"},
        "Serie B": {"code": "I2", "teams": 20, "of_json": "it.2.json"},
    },
    "France": {
        "Ligue 1": {"code": "F1", "teams": 18, "of_json": "fr.1.json"},
        "Ligue 2": {"code": "F2", "teams": 18, "of_json": "fr.2.json"},
    },
}


def get_of_json(league_code: str) -> str | None:
    """Get openfootball/football.json filename for a league code."""
    for leagues in COUNTRIES.values():
        for info in leagues.values():
            if info["code"] == league_code:
                return info.get("of_json")
    return None


# Team name mapping: openfootball full names → football-data.co.uk short names
# Only entries where names differ are needed
OPENFOOTBALL_TEAM_MAP = {
    # England - Premier League
    "Arsenal FC": "Arsenal",
    "Aston Villa FC": "Aston Villa",
    "AFC Bournemouth": "Bournemouth",
    "Brentford FC": "Brentford",
    "Brighton & Hove Albion FC": "Brighton",
    "Burnley FC": "Burnley",
    "Chelsea FC": "Chelsea",
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Leeds United FC": "Leeds",
    "Liverpool FC": "Liverpool",
    "Manchester City FC": "Man City",
    "Manchester United FC": "Man United",
    "Newcastle United FC": "Newcastle",
    "Nottingham Forest FC": "Nott'm Forest",
    "Sunderland AFC": "Sunderland",
    "Tottenham Hotspur FC": "Tottenham",
    "West Ham United FC": "West Ham",
    "Wolverhampton Wanderers FC": "Wolves",
    # England - Championship
    "Birmingham City FC": "Birmingham",
    "Blackburn Rovers FC": "Blackburn",
    "Blackburn Rovers": "Blackburn",
    "Bristol City FC": "Bristol City",
    "Bristol City": "Bristol City",
    "Charlton Athletic FC": "Charlton",
    "Coventry City FC": "Coventry",
    "Derby County FC": "Derby",
    "Hull City AFC": "Hull",
    "Ipswich Town FC": "Ipswich",
    "Ipswich Town": "Ipswich",
    "Leicester City FC": "Leicester",
    "Leicester City": "Leicester",
    "Middlesbrough FC": "Middlesbrough",
    "Millwall FC": "Millwall",
    "Millwall": "Millwall",
    "Norwich City FC": "Norwich",
    "Oxford United FC": "Oxford",
    "Portsmouth FC": "Portsmouth",
    "Portsmouth": "Portsmouth",
    "Preston North End FC": "Preston",
    "Queens Park Rangers FC": "QPR",
    "Sheffield United FC": "Sheffield United",
    "Sheffield Wednesday FC": "Sheffield Weds",
    "Sheffield Wednesday": "Sheffield Weds",
    "Southampton FC": "Southampton",
    "Stoke City FC": "Stoke",
    "Stoke City": "Stoke",
    "Swansea City AFC": "Swansea",
    "Watford FC": "Watford",
    "Watford": "Watford",
    "West Bromwich Albion FC": "West Brom",
    "Wrexham AFC": "Wrexham",
    # Germany - Bundesliga
    "FC Bayern München": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "RB Leipzig": "RB Leipzig",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "VfB Stuttgart": "Stuttgart",
    "SC Freiburg": "Freiburg",
    "VfL Wolfsburg": "Wolfsburg",
    "1. FSV Mainz 05": "Mainz",
    "Borussia Mönchengladbach": "M'gladbach",
    "1. FC Union Berlin": "Union Berlin",
    "SV Werder Bremen": "Werder Bremen",
    "FC Augsburg": "Augsburg",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    "1. FC Heidenheim 1846": "Heidenheim",
    "1. FC Köln": "FC Koln",
    "FC St. Pauli 1910": "St Pauli",
    "Hamburger SV": "Hamburg",
    # Germany - 2. Bundesliga
    "Fortuna Düsseldorf": "Dusseldorf",
    "SC Paderborn 07": "Paderborn",
    "FC Schalke 04": "Schalke 04",
    "1. FC Nürnberg": "Nurnberg",
    "1. FC Kaiserslautern": "Kaiserslautern",
    "1. FC Magdeburg": "Magdeburg",
    "Hannover 96": "Hannover",
    "Hertha BSC": "Hertha",
    "Holstein Kiel": "Holstein Kiel",
    "Karlsruher SC": "Karlsruhe",
    "SV Darmstadt 98": "Darmstadt",
    "SV 07 Elversberg": "Elversberg",
    "SpVgg Greuther Fürth": "Greuther Furth",
    "Eintracht Braunschweig": "Braunschweig",
    "Arminia Bielefeld": "Bielefeld",
    "Dynamo Dresden": "Dresden",
    "Preußen Münster": "Munster",
    "VfL Bochum": "Bochum",
    # Spain - La Liga
    "Real Madrid CF": "Real Madrid",
    "FC Barcelona": "Barcelona",
    "Club Atlético de Madrid": "Ath Madrid",
    "Athletic Club": "Ath Bilbao",
    "Real Sociedad de Fútbol": "Real Sociedad",
    "Real Betis Balompié": "Betis",
    "Villarreal CF": "Villarreal",
    "Sevilla FC": "Sevilla",
    "RC Celta de Vigo": "Celta",
    "RCD Mallorca": "Mallorca",
    "Girona FC": "Girona",
    "Rayo Vallecano de Madrid": "Vallecano",
    "CA Osasuna": "Osasuna",
    "Getafe CF": "Getafe",
    "Deportivo Alavés": "Alaves",
    "Valencia CF": "Valencia",
    "RCD Espanyol de Barcelona": "Espanol",
    "Levante UD": "Levante",
    "Real Oviedo": "Real Oviedo",
    "Elche CF": "Elche",
    # Spain - Segunda
    "CD Leganés": "Leganes",
    "UD Las Palmas": "Las Palmas",
    "UD Almería": "Almeria",
    "Granada CF": "Granada",
    "Cádiz CF": "Cadiz",
    "SD Eibar": "Eibar",
    "SD Huesca": "Huesca",
    "Real Valladolid": "Valladolid",
    "Real Zaragoza": "Zaragoza",
    "Sporting Gijón": "Sp Gijon",
    "Deportivo La Coruña": "La Coruna",
    "Málaga CF": "Malaga",
    "Racing Santander": "Santander",
    "Córdoba CF": "Cordoba",
    "Burgos CF": "Burgos",
    "CD Mirandés": "Mirandes",
    "CD Castellón": "Castellon",
    "FC Andorra": "Andorra",
    "Real Sociedad B": "Real Sociedad B",
    "Albacete": "Albacete",
    "Cultural Leonesa": "Leonesa",
    "AD Ceuta FC": "Ceuta",
    # Italy - Serie A
    "Juventus FC": "Juventus",
    "FC Internazionale Milano": "Inter",
    "AC Milan": "Milan",
    "SSC Napoli": "Napoli",
    "AS Roma": "Roma",
    "SS Lazio": "Lazio",
    "Atalanta BC": "Atalanta",
    "ACF Fiorentina": "Fiorentina",
    "Bologna FC 1909": "Bologna",
    "Torino FC": "Torino",
    "Udinese Calcio": "Udinese",
    "US Sassuolo Calcio": "Sassuolo",
    "Cagliari Calcio": "Cagliari",
    "Genoa CFC": "Genoa",
    "Hellas Verona FC": "Verona",
    "US Lecce": "Lecce",
    "Parma Calcio 1913": "Parma",
    "Como 1907": "Como",
    "US Cremonese": "Cremonese",
    "AC Pisa 1909": "Pisa",
    # Italy - Serie B
    "Venezia FC": "Venezia",
    "Empoli FC": "Empoli",
    "Spezia Calcio": "Spezia",
    "Frosinone Calcio": "Frosinone",
    "Palermo FC": "Palermo",
    "SSC Bari": "Bari",
    "Sampdoria": "Sampdoria",
    "Modena FC": "Modena",
    "AC Monza": "Monza",
    "AC Reggiana 1919": "Reggiana",
    "Cesena FC": "Cesena",
    "Carrarese Calcio": "Carrarese",
    "Delfino Pescara": "Pescara",
    "FC Südtirol": "Sudtirol",
    "Juve Stabia": "Juve Stabia",
    "US Catanzaro": "Catanzaro",
    "Mantova 1911 SSD": "Mantova",
    "Calcio Padova": "Padova",
    "US Avellino": "Avellino",
    "Virtus Entella": "Entella",
    # France - Ligue 1
    "Paris Saint-Germain FC": "Paris SG",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "AS Monaco FC": "Monaco",
    "Lille OSC": "Lille",
    "OGC Nice": "Nice",
    "RC Strasbourg Alsace": "Strasbourg",
    "Racing Club de Lens": "Lens",
    "Stade Rennais FC 1901": "Rennes",
    "FC Nantes": "Nantes",
    "Stade Brestois 29": "Brest",
    "Toulouse FC": "Toulouse",
    "Le Havre AC": "Le Havre",
    "FC Metz": "Metz",
    "FC Lorient": "Lorient",
    "Angers SCO": "Angers",
    "AJ Auxerre": "Auxerre",
    "Paris FC": "Paris FC",
    # France - Ligue 2
    "Montpellier HSC": "Montpellier",
    "AS Saint-Étienne": "St Etienne",
    "Stade de Reims": "Reims",
    "EA Guingamp": "Guingamp",
    "Clermont Foot 63": "Clermont",
    "Amiens SC": "Amiens",
    "SC Bastia": "Bastia",
    "ESTAC Troyes": "Troyes",
    "AS Nancy Lorraine": "Nancy",
    "Grenoble Foot 38": "Grenoble",
    "Stade Lavallois": "Laval",
    "Pau FC": "Pau",
    "Rodez AF": "Rodez",
    "USL Dunkerque": "Dunkerque",
    "Red Star FC": "Red Star",
    "FC Annecy": "Annecy",
    "Le Mans FC": "Le Mans",
    "US Boulogne": "Boulogne",
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
