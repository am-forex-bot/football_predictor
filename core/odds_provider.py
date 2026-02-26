"""Fetch live bookmaker odds from the-odds-api.com.

Free tier: 500 requests/month (one request per league per click).
Returns real pre-match odds from Bet365, Pinnacle, and other bookmakers
so the value engine can calculate edge against actual market prices.

Get your free API key at: https://the-odds-api.com
"""

import json
import os
from typing import Optional

import pandas as pd
import requests

# ───────────────────────────────────────────────────────────────────────
# League code → the-odds-api sport key
# ───────────────────────────────────────────────────────────────────────

LEAGUE_TO_SPORT = {
    "E0": "soccer_epl",
    "E1": "soccer_efl_champ",
    "E2": "soccer_england_league1",
    "E3": "soccer_england_league2",
    "SC0": "soccer_spl",
    "D1": "soccer_germany_bundesliga",
    "D2": "soccer_germany_bundesliga2",
    "SP1": "soccer_spain_la_liga",
    "SP2": "soccer_spain_la_liga2",
    "I1": "soccer_italy_serie_a",
    "I2": "soccer_italy_serie_b",
    "F1": "soccer_france_ligue_one",
    "F2": "soccer_france_ligue_two",
    "N1": "soccer_netherlands_eredivisie",
    "B1": "soccer_belgium_first_div",
    "P1": "soccer_portugal_primeira_liga",
    "T1": "soccer_turkey_super_league",
    "G1": "soccer_greece_super_league",
}

# ───────────────────────────────────────────────────────────────────────
# Team name mapping: the-odds-api name → football-data.co.uk name
# ───────────────────────────────────────────────────────────────────────

_TEAM_MAP = {
    # England
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Nottingham Forest": "Nott'm Forest",
    "Tottenham Hotspur": "Tottenham",
    "Newcastle United": "Newcastle",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    "Brighton and Hove Albion": "Brighton",
    "Leicester City": "Leicester",
    "Ipswich Town": "Ipswich",
    "Sheffield United": "Sheffield United",
    "Luton Town": "Luton",
    "Leeds United": "Leeds",
    "Norwich City": "Norwich",
    "Coventry City": "Coventry",
    "Middlesbrough FC": "Middlesbrough",
    "Sunderland AFC": "Sunderland",
    "Blackburn Rovers": "Blackburn",
    "Queens Park Rangers": "QPR",
    "Stoke City": "Stoke",
    "Swansea City": "Swansea",
    "Cardiff City": "Cardiff",
    "Hull City": "Hull",
    "Bristol City": "Bristol City",
    "Plymouth Argyle": "Plymouth",
    "West Bromwich Albion": "West Brom",
    "Preston North End": "Preston",
    "Huddersfield Town": "Huddersfield",
    "Birmingham City": "Birmingham",
    "Watford FC": "Watford",
    # Germany
    "Bayern Munich": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "Bayer Leverkusen": "Leverkusen",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "Borussia Monchengladbach": "M'gladbach",
    "Borussia Mönchengladbach": "M'gladbach",
    "VfB Stuttgart": "Stuttgart",
    "SC Freiburg": "Freiburg",
    "VfL Wolfsburg": "Wolfsburg",
    "1. FSV Mainz 05": "Mainz",
    "FSV Mainz 05": "Mainz",
    "TSG Hoffenheim": "Hoffenheim",
    "1899 Hoffenheim": "Hoffenheim",
    "FC Augsburg": "Augsburg",
    "SV Werder Bremen": "Werder Bremen",
    "Werder Bremen": "Werder Bremen",
    "1. FC Heidenheim": "Heidenheim",
    "1. FC Heidenheim 1846": "Heidenheim",
    "FC St. Pauli": "St Pauli",
    "Holstein Kiel": "Holstein Kiel",
    "VfL Bochum": "Bochum",
    "VfL Bochum 1848": "Bochum",
    "1. FC Union Berlin": "Union Berlin",
    "1. FC Köln": "FC Koln",
    "1. FC Koln": "FC Koln",
    "Hertha Berlin": "Hertha",
    "Hertha BSC": "Hertha",
    "Fortuna Düsseldorf": "Fortuna Dusseldorf",
    "Fortuna Dusseldorf": "Fortuna Dusseldorf",
    "SV Darmstadt 98": "Darmstadt",
    # Spain
    "Atletico Madrid": "Ath Madrid",
    "Atlético Madrid": "Ath Madrid",
    "Atletico de Madrid": "Ath Madrid",
    "Athletic Bilbao": "Ath Bilbao",
    "Athletic Club": "Ath Bilbao",
    "Real Sociedad": "Sociedad",
    "Real Betis": "Betis",
    "Celta Vigo": "Celta",
    "RC Celta de Vigo": "Celta",
    "Rayo Vallecano": "Vallecano",
    "RCD Mallorca": "Mallorca",
    "Deportivo Alavés": "Alaves",
    "Deportivo Alaves": "Alaves",
    "CD Leganés": "Leganes",
    "CD Leganes": "Leganes",
    "RCD Espanyol": "Espanol",
    "Espanyol": "Espanol",
    "Real Valladolid": "Valladolid",
    "Villarreal CF": "Villarreal",
    "Getafe CF": "Getafe",
    "Sevilla FC": "Sevilla",
    "Valencia CF": "Valencia",
    "Girona FC": "Girona",
    "UD Las Palmas": "Las Palmas",
    "UD Almería": "Almeria",
    "UD Almeria": "Almeria",
    "Cadiz CF": "Cadiz",
    "Granada CF": "Granada",
    # Italy
    "AC Milan": "Milan",
    "Inter Milan": "Inter",
    "Internazionale": "Inter",
    "AS Roma": "Roma",
    "SS Lazio": "Lazio",
    "SSC Napoli": "Napoli",
    "Hellas Verona": "Verona",
    "US Lecce": "Lecce",
    "Cagliari Calcio": "Cagliari",
    "Genoa CFC": "Genoa",
    "Parma Calcio 1913": "Parma",
    "Venezia FC": "Venezia",
    "US Sassuolo": "Sassuolo",
    "US Salernitana 1919": "Salernitana",
    "Frosinone Calcio": "Frosinone",
    # France
    "Paris Saint-Germain": "Paris SG",
    "Paris Saint Germain": "Paris SG",
    "Olympique Lyonnais": "Lyon",
    "Olympique de Marseille": "Marseille",
    "AS Monaco": "Monaco",
    "AS Saint-Étienne": "St Etienne",
    "AS Saint-Etienne": "St Etienne",
    "RC Lens": "Lens",
    "Stade Rennais": "Rennes",
    "RC Strasbourg": "Strasbourg",
    "FC Nantes": "Nantes",
    "OGC Nice": "Nice",
    "Stade Brestois": "Brest",
    "Stade de Reims": "Reims",
    "Montpellier HSC": "Montpellier",
    "Toulouse FC": "Toulouse",
    "FC Lorient": "Lorient",
    "Clermont Foot": "Clermont",
    "Le Havre AC": "Le Havre",
    "FC Metz": "Metz",
    # Netherlands
    "Ajax Amsterdam": "Ajax",
    "PSV Eindhoven": "PSV",
    "Feyenoord Rotterdam": "Feyenoord",
    "AZ Alkmaar": "AZ Alkmaar",
    "FC Twente": "Twente",
    "FC Utrecht": "Utrecht",
    "SC Heerenveen": "Heerenveen",
    "Sparta Rotterdam": "Sparta Rotterdam",
    "NEC Nijmegen": "NEC Nijmegen",
    "Fortuna Sittard": "For Sittard",
    "RKC Waalwijk": "Waalwijk",
    "Go Ahead Eagles": "Go Ahead Eagles",
    "PEC Zwolle": "Zwolle",
    "Heracles Almelo": "Heracles",
    # Scotland
    "Celtic FC": "Celtic",
    "Rangers FC": "Rangers",
    "Aberdeen FC": "Aberdeen",
    "Heart of Midlothian": "Hearts",
    "Hibernian FC": "Hibernian",
    "Dundee FC": "Dundee",
    "Dundee United": "Dundee Utd",
    "Kilmarnock FC": "Kilmarnock",
    "St. Mirren": "St Mirren",
    "Motherwell FC": "Motherwell",
    "Ross County FC": "Ross County",
    "Livingston FC": "Livingston",
    "St Johnstone FC": "St Johnstone",
    # Belgium
    "Club Brugge": "Club Brugge",
    "RSC Anderlecht": "Anderlecht",
    "KRC Genk": "Genk",
    "Royal Antwerp FC": "Antwerp",
    "Standard Liège": "Standard",
    "Standard Liege": "Standard",
    # Portugal
    "SL Benfica": "Benfica",
    "FC Porto": "Porto",
    "Sporting CP": "Sporting CP",
    "Sporting Lisbon": "Sporting CP",
    "SC Braga": "Sp Braga",
    "Vitória SC": "Guimaraes",
    "Vitoria SC": "Guimaraes",
}


def _normalise(name: str) -> str:
    """Normalise a team name for fuzzy matching."""
    n = name.lower().strip()
    # Strip common suffixes
    for suffix in (" fc", " cf", " afc", " sc", " sv", " 1848", " 1846",
                   " 1913", " 1919", " calcio"):
        n = n.removesuffix(suffix)
    return n.strip()


def _match_team(odds_name: str, fd_names: list[str]) -> Optional[str]:
    """Match an odds-api team name to the closest football-data name."""
    # 1. Direct map
    if odds_name in _TEAM_MAP:
        mapped = _TEAM_MAP[odds_name]
        if mapped in fd_names:
            return mapped

    # 2. Exact match (already in fd format)
    if odds_name in fd_names:
        return odds_name

    # 3. Case-insensitive match
    lower_map = {n.lower(): n for n in fd_names}
    if odds_name.lower() in lower_map:
        return lower_map[odds_name.lower()]

    # 4. Normalised substring match
    norm_odds = _normalise(odds_name)
    for fd_name in fd_names:
        norm_fd = _normalise(fd_name)
        if norm_odds == norm_fd:
            return fd_name
        if norm_odds in norm_fd or norm_fd in norm_odds:
            return fd_name

    return None


# ───────────────────────────────────────────────────────────────────────
# Config file
# ───────────────────────────────────────────────────────────────────────

_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "odds_config.json"
)


def load_config() -> dict:
    """Load saved config (API key + bookmaker preference)."""
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_api_key() -> str:
    """Load saved API key."""
    return load_config().get("api_key", "")


def load_bookmaker() -> str:
    """Load saved bookmaker preference."""
    return load_config().get("bookmaker", "bet365")


def save_config(api_key: str = "", bookmaker: str = ""):
    """Save config for next time."""
    os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
    existing = load_config()
    if api_key:
        existing["api_key"] = api_key.strip()
    if bookmaker:
        existing["bookmaker"] = bookmaker.strip()
    with open(_CONFIG_FILE, "w") as f:
        json.dump(existing, f)


def save_api_key(key: str):
    """Save API key (convenience wrapper)."""
    save_config(api_key=key)


# Bookmaker keys used by the-odds-api
BOOKMAKERS = {
    "Bet365": "bet365",
    "Pinnacle": "pinnacle",
    "William Hill": "williamhill",
    "Betfair Sportsbook": "betfair_sb_uk",
    "Paddy Power": "paddypower",
    "Ladbrokes": "ladbrokes_uk",
    "Coral": "coral",
    "Sky Bet": "skybet",
    "Betway": "betway",
    "Unibet": "unibet_uk",
    "888sport": "sport888",
    "All bookmakers": "",
}


# ───────────────────────────────────────────────────────────────────────
# Fetch odds
# ───────────────────────────────────────────────────────────────────────

_BASE = "https://api.the-odds-api.com/v4"


def get_sport_key(league_code: str) -> Optional[str]:
    """Get the-odds-api sport key for a football-data league code."""
    return LEAGUE_TO_SPORT.get(league_code)


def fetch_odds(league_code: str, api_key: str,
               bookmaker: str = "bet365") -> dict:
    """Fetch live bookmaker odds for upcoming fixtures.

    Fetches 1X2 (h2h) and Over/Under 2.5 (totals) markets.
    Filters to the specified bookmaker so you only see prices you can get.

    API cost: 1 request per call (h2h + totals in one request).
    Free tier: 500 requests/month.

    Raises ValueError if league not supported or API key invalid.
    """
    sport = get_sport_key(league_code)
    if not sport:
        supported = ", ".join(sorted(LEAGUE_TO_SPORT.keys()))
        raise ValueError(
            f"League {league_code} not supported by odds API. "
            f"Supported: {supported}"
        )

    if not api_key or not api_key.strip():
        raise ValueError(
            "No API key set. Get a free key at https://the-odds-api.com "
            "and paste it into the API Key field."
        )

    url = f"{_BASE}/sports/{sport}/odds/"
    params = {
        "apiKey": api_key.strip(),
        "regions": "uk,eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
    }

    # Filter to specific bookmaker if set (reduces noise, not cost)
    bm_key = BOOKMAKERS.get(bookmaker, bookmaker)
    if bm_key:
        params["bookmakers"] = bm_key

    resp = requests.get(url, params=params, timeout=15)

    if resp.status_code == 401:
        raise ValueError("Invalid API key. Check your key at https://the-odds-api.com")
    if resp.status_code == 429:
        raise ValueError("API quota exceeded. Free tier = 500 requests/month.")
    if resp.status_code == 422:
        raise ValueError(f"League '{sport}' not currently available on the-odds-api.")
    resp.raise_for_status()

    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")

    return {
        "odds": _parse_odds(data, bm_key),
        "remaining_requests": remaining,
        "used_requests": used,
        "raw_count": len(data),
    }


def _parse_odds(events: list, target_bm: str = "") -> list[dict]:
    """Parse the-odds-api response into our format.

    Extracts 1X2 and Over/Under 2.5 odds from the target bookmaker.
    """
    results = []

    for event in events:
        home_raw = event.get("home_team", "")
        away_raw = event.get("away_team", "")
        commence = event.get("commence_time", "")

        bookmakers = event.get("bookmakers", [])
        if not bookmakers:
            continue

        # 1X2 odds
        h2h = {"home": None, "draw": None, "away": None}
        # Over/Under 2.5
        ou25 = {"over": None, "under": None}

        for bm in bookmakers:
            bm_key = bm.get("key", "")

            # If targeting a specific bookmaker, only use that one
            if target_bm and bm_key != target_bm:
                continue

            for market in bm.get("markets", []):
                mkey = market.get("key", "")

                if mkey == "h2h":
                    outcomes = {
                        o["name"]: o["price"]
                        for o in market.get("outcomes", [])
                    }
                    h = outcomes.get(home_raw)
                    d = outcomes.get("Draw")
                    a = outcomes.get(away_raw)
                    if h and d and a:
                        h2h = {"home": h, "draw": d, "away": a}

                elif mkey == "totals":
                    # Look for the 2.5 goals line
                    for o in market.get("outcomes", []):
                        point = o.get("point")
                        if point == 2.5:
                            if o["name"] == "Over":
                                ou25["over"] = o["price"]
                            elif o["name"] == "Under":
                                ou25["under"] = o["price"]

        if h2h["home"] is None:
            continue

        results.append({
            "home_team_raw": home_raw,
            "away_team_raw": away_raw,
            "home_team": home_raw,
            "away_team": away_raw,
            "commence_time": commence,
            "home_odds": h2h["home"],
            "draw_odds": h2h["draw"],
            "away_odds": h2h["away"],
            "over_25_odds": ou25["over"],
            "under_25_odds": ou25["under"],
        })

    return results


def merge_odds_into_fixtures(fixtures_df: pd.DataFrame,
                             odds_data: list[dict]) -> pd.DataFrame:
    """Merge live odds into the fixtures DataFrame.

    Matches fixtures by team names and populates the odds columns
    that the Poisson model and value engine expect:
    - Home_Odds, Draw_Odds, Away_Odds (1X2)
    - Max_Home_Odds etc. (set same as above for single-bookmaker mode)
    - Over_25_Odds, Under_25_Odds (totals)
    """
    if fixtures_df.empty or not odds_data:
        return fixtures_df

    df = fixtures_df.copy()

    # Determine team column names
    if "Team" in df.columns:
        home_col, away_col = "Team", "Opponent"
    elif "HomeTeam" in df.columns:
        home_col, away_col = "HomeTeam", "AwayTeam"
    else:
        return df

    # Get all fixture team names for matching
    fd_names = list(set(df[home_col].tolist() + df[away_col].tolist()))

    # Remap odds team names to football-data names
    for o in odds_data:
        o["home_team"] = _match_team(o["home_team_raw"], fd_names) or o["home_team_raw"]
        o["away_team"] = _match_team(o["away_team_raw"], fd_names) or o["away_team_raw"]

    # Build lookup: (home, away) → odds dict
    odds_lookup = {}
    for o in odds_data:
        key = (o["home_team"], o["away_team"])
        odds_lookup[key] = o

    # Ensure odds columns exist
    for col in ("Home_Odds", "Draw_Odds", "Away_Odds",
                "Max_Home_Odds", "Max_Draw_Odds", "Max_Away_Odds",
                "Over_25_Odds", "Under_25_Odds"):
        if col not in df.columns:
            df[col] = float("nan")

    matched = 0
    for idx in df.index:
        home = df.at[idx, home_col]
        away = df.at[idx, away_col]
        key = (home, away)

        if key not in odds_lookup:
            continue

        o = odds_lookup[key]
        matched += 1

        # 1X2 odds
        df.at[idx, "Home_Odds"] = o["home_odds"]
        df.at[idx, "Draw_Odds"] = o["draw_odds"]
        df.at[idx, "Away_Odds"] = o["away_odds"]

        # Max = same as above in single-bookmaker mode
        df.at[idx, "Max_Home_Odds"] = o["home_odds"]
        df.at[idx, "Max_Draw_Odds"] = o["draw_odds"]
        df.at[idx, "Max_Away_Odds"] = o["away_odds"]

        # Over/Under 2.5
        if o.get("over_25_odds"):
            df.at[idx, "Over_25_Odds"] = o["over_25_odds"]
        if o.get("under_25_odds"):
            df.at[idx, "Under_25_Odds"] = o["under_25_odds"]

    return df
