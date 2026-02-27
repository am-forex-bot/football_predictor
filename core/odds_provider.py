"""Fetch live bookmaker odds from the-odds-api.com.

Free tier: 500 requests/month (one request per league per click).
Returns real pre-match odds from Bet365, Pinnacle, and other bookmakers
so the value engine can calculate edge against actual market prices.

Get your free API key at: https://the-odds-api.com
"""

import json
import logging
import os
from typing import Optional
from urllib.parse import urlencode

import pandas as pd
import requests

log = logging.getLogger(__name__)

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
    # England — Premier League (the-odds-api name → football-data.co.uk name)
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
    "Southampton": "Southampton",
    "Bournemouth": "Bournemouth",
    "AFC Bournemouth": "Bournemouth",
    # England — Championship / lower leagues
    "Leeds United": "Leeds",
    "Norwich City": "Norwich",
    "Coventry City": "Coventry",
    "Middlesbrough FC": "Middlesbrough",
    "Middlesbrough": "Middlesbrough",
    "Sunderland AFC": "Sunderland",
    "Sunderland": "Sunderland",
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
    "Watford": "Watford",
    "Burnley FC": "Burnley",
    "Burnley": "Burnley",
    "Sheffield Wednesday": "Sheffield Weds",
    "Derby County": "Derby",
    "Oxford United": "Oxford",
    "Portsmouth FC": "Portsmouth",
    "Portsmouth": "Portsmouth",
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
    import unicodedata
    # Decompose accented characters → base + combining, then strip combining
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower().strip()
    # Strip common suffixes
    for suffix in (" fc", " cf", " afc", " sc", " sv", " ssd",
                   " 1848", " 1846", " 1910", " 1909", " 1913", " 1919",
                   " calcio", " de futbol", " balompie"):
        n = n.removesuffix(suffix)
    # Strip common prefixes
    for prefix in ("afc ", "fc ", "1. ", "rc ", "rcd ", "us ", "ss ",
                   "ssc ", "ud ", "cd ", "ac ", "as "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return n.strip()


def _match_team(odds_name: str, fd_names: list[str]) -> Optional[str]:
    """Match an odds-api team name to the closest football-data name.

    Uses a multi-pass approach:
    1. Direct map lookup (hard-coded known mappings)
    2. Exact match (already in the right format)
    3. Case-insensitive match
    4. Normalised exact match (strips suffixes, accents, etc.)
    5. Normalised substring match (one name contains the other)
    6. Word-overlap match (shares significant words)
    """
    if not odds_name or not fd_names:
        return None

    # 1. Direct map — check the mapped value is actually in our fixture list
    if odds_name in _TEAM_MAP:
        mapped = _TEAM_MAP[odds_name]
        if mapped in fd_names:
            return mapped
        # The mapped name might itself need case-insensitive matching
        lower_map = {n.lower(): n for n in fd_names}
        if mapped.lower() in lower_map:
            return lower_map[mapped.lower()]

    # 2. Exact match (already in fd format)
    if odds_name in fd_names:
        return odds_name

    # 3. Case-insensitive match
    lower_map = {n.lower(): n for n in fd_names}
    if odds_name.lower() in lower_map:
        return lower_map[odds_name.lower()]

    # 4. Normalised exact match
    norm_odds = _normalise(odds_name)
    norm_lookup = {_normalise(n): n for n in fd_names}
    if norm_odds in norm_lookup:
        return norm_lookup[norm_odds]

    # 5. Normalised substring match
    for fd_name in fd_names:
        norm_fd = _normalise(fd_name)
        if len(norm_odds) >= 3 and len(norm_fd) >= 3:
            if norm_odds in norm_fd or norm_fd in norm_odds:
                return fd_name

    # 6. Word-overlap match — if the significant words overlap
    odds_words = set(norm_odds.split()) - {"de", "la", "the", "of", "and", "city", "united", "town"}
    if odds_words:
        best_match = None
        best_overlap = 0
        for fd_name in fd_names:
            fd_words = set(_normalise(fd_name).split()) - {"de", "la", "the", "of", "and", "city", "united", "town"}
            if not fd_words:
                continue
            overlap = len(odds_words & fd_words)
            # Require at least one significant word overlap and > 50% match
            min_len = min(len(odds_words), len(fd_words))
            if overlap > best_overlap and overlap >= 1 and overlap / min_len >= 0.5:
                best_overlap = overlap
                best_match = fd_name
        if best_match and best_overlap >= 1:
            return best_match

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

    Fetches 1X2 (h2h) and Over/Under 2.5 (totals) markets from ALL
    bookmakers in uk/eu regions.  Post-filters to the requested bookmaker
    with automatic fallback to best-available if that bookmaker hasn't
    published prices yet.

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

    bm_key = BOOKMAKERS.get(bookmaker, bookmaker)
    key = api_key.strip()

    # CRITICAL: the-odds-api requires literal commas in query parameters.
    # Python's requests library percent-encodes commas (%2C) which breaks
    # the API — it treats "h2h%2Ctotals" as a single unknown market and
    # returns events with zero bookmaker data.
    #
    # Fix: use requests.Request + PreparedRequest to set the exact URL
    # with literal commas, bypassing the param encoder entirely.
    url = (
        f"{_BASE}/sports/{sport}/odds/"
        f"?apiKey={key}"
        f"&regions=uk,eu"
        f"&markets=h2h,totals"
        f"&oddsFormat=decimal"
    )
    req = requests.Request("GET", url)
    prepared = req.prepare()
    # Overwrite the URL to preserve literal commas (prepare() may re-encode)
    prepared.url = url

    session = requests.Session()
    resp = session.send(prepared, timeout=15)
    log.info("Odds API %s → %s (%s bytes)", sport, resp.status_code, len(resp.content))

    if resp.status_code == 401:
        raise ValueError("Invalid API key. Check your key at https://the-odds-api.com")
    if resp.status_code == 429:
        raise ValueError("API quota exceeded. Free tier = 500 requests/month.")
    if resp.status_code == 422:
        detail = ""
        try:
            detail = resp.json().get("message", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        raise ValueError(
            f"the-odds-api rejected request for '{sport}': {detail}"
        )
    resp.raise_for_status()

    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")

    log.info("Odds API returned %d events, remaining=%s", len(data), remaining)
    if data:
        sample = data[0]
        n_bm = len(sample.get("bookmakers", []))
        log.info("  First event: %s vs %s, %d bookmakers",
                 sample.get("home_team"), sample.get("away_team"), n_bm)

    # Use target bookmaker only — never fall back to other bookmakers
    odds = _parse_odds(data, bm_key)
    source = bookmaker

    if not odds and bm_key:
        # Log what bookmakers ARE in the response so we can debug
        all_bm_keys = set()
        for event in data:
            for bm in event.get("bookmakers", []):
                all_bm_keys.add(bm.get("key", ""))
        log.warning("Target bookmaker '%s' not found. Available: %s",
                    bm_key, sorted(all_bm_keys))

        # Try flexible matching: case-insensitive, partial match
        matched_key = ""
        for k in sorted(all_bm_keys):
            if bm_key.lower() in k.lower() or k.lower() in bm_key.lower():
                matched_key = k
                break
        if matched_key:
            log.info("Flexible match: '%s' → '%s'", bm_key, matched_key)
            odds = _parse_odds(data, matched_key)
            source = f"{bookmaker} (matched as '{matched_key}')"
        else:
            # Try Soccerway as fallback for Bet365 odds
            if "bet365" in bm_key.lower() or "bet365" in bookmaker.lower():
                try:
                    from core.soccerway import fetch_soccerway_odds
                    log.info("Trying Soccerway as Bet365 odds source...")
                    sw_result = fetch_soccerway_odds(league_code)
                    if sw_result["odds"]:
                        log.info("Soccerway returned %d fixtures with Bet365 odds",
                                 len(sw_result["odds"]))
                        return {
                            "odds": sw_result["odds"],
                            "remaining_requests": remaining,
                            "used_requests": used,
                            "raw_events": len(sw_result["odds"]),
                            "source": "Bet365 (via Soccerway)",
                        }
                except Exception as e:
                    log.warning("Soccerway fallback failed: %s", e)

            # No match at all — return no odds rather than fake prices
            source = (
                f"{bookmaker} not on the-odds-api. "
                f"Bet365 odds from football-data.co.uk will be used instead"
            )

    log.info("Parsed %d fixtures with odds (source: %s)", len(odds), source)

    return {
        "odds": odds,
        "remaining_requests": remaining,
        "used_requests": used,
        "raw_events": len(data),
        "source": source,
    }


def _parse_odds(events: list, target_bm: str = "") -> list[dict]:
    """Parse the-odds-api response into our format.

    If *target_bm* is set, only odds from that bookmaker are used.
    If *target_bm* is empty, the best (highest) odds across all
    bookmakers are used for each market.
    """
    results = []

    for event in events:
        home_raw = event.get("home_team", "")
        away_raw = event.get("away_team", "")
        commence = event.get("commence_time", "")

        bookmakers = event.get("bookmakers", [])
        if not bookmakers:
            continue

        # 1X2 odds — track best across bookmakers
        h2h = {"home": None, "draw": None, "away": None}
        # Over/Under 2.5
        ou25 = {"over": None, "under": None}
        # BTTS (Both Teams To Score)
        btts = {"yes": None, "no": None}
        # Which bookmaker provided the h2h odds
        h2h_source = ""

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
                        # When no target: pick best home odds
                        if h2h["home"] is None or h > h2h["home"]:
                            h2h = {"home": h, "draw": d, "away": a}
                            h2h_source = bm.get("title", bm_key)

                elif mkey == "totals":
                    for o in market.get("outcomes", []):
                        point = o.get("point")
                        if point == 2.5:
                            if o["name"] == "Over":
                                if ou25["over"] is None or o["price"] > ou25["over"]:
                                    ou25["over"] = o["price"]
                            elif o["name"] == "Under":
                                if ou25["under"] is None or o["price"] > ou25["under"]:
                                    ou25["under"] = o["price"]

                elif mkey == "btts":
                    for o in market.get("outcomes", []):
                        if o["name"] == "Yes":
                            if btts["yes"] is None or o["price"] > btts["yes"]:
                                btts["yes"] = o["price"]
                        elif o["name"] == "No":
                            if btts["no"] is None or o["price"] > btts["no"]:
                                btts["no"] = o["price"]

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
            "btts_yes_odds": btts["yes"],
            "btts_no_odds": btts["no"],
            "bookmaker": h2h_source,
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

    Handles both column conventions:
    - Team/Opponent (cleaned format from workbook)
    - HomeTeam/AwayTeam (raw format from download)
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
        log.warning("merge_odds: no Team or HomeTeam column found in fixtures")
        return df

    # Get all fixture team names for matching
    fd_names = list(set(
        df[home_col].dropna().tolist() + df[away_col].dropna().tolist()
    ))

    log.info("merge_odds: %d odds entries, %d fixtures, %d unique teams",
             len(odds_data), len(df), len(fd_names))

    # Remap odds team names to football-data names
    unmatched = []
    for o in odds_data:
        h = _match_team(o["home_team_raw"], fd_names)
        a = _match_team(o["away_team_raw"], fd_names)
        if not h:
            unmatched.append(o["home_team_raw"])
        if not a:
            unmatched.append(o["away_team_raw"])
        o["home_team"] = h or o["home_team_raw"]
        o["away_team"] = a or o["away_team_raw"]

    if unmatched:
        log.warning("merge_odds: %d team names not matched: %s",
                    len(unmatched), unmatched[:10])

    # Build lookup: (home, away) → odds dict
    odds_lookup = {}
    for o in odds_data:
        key = (o["home_team"], o["away_team"])
        odds_lookup[key] = o

    # Ensure odds columns exist
    for col in ("Home_Odds", "Draw_Odds", "Away_Odds",
                "Max_Home_Odds", "Max_Draw_Odds", "Max_Away_Odds",
                "Over_25_Odds", "Under_25_Odds",
                "BTTS_Yes_Odds", "BTTS_No_Odds"):
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

        # BTTS
        if o.get("btts_yes_odds"):
            df.at[idx, "BTTS_Yes_Odds"] = o["btts_yes_odds"]
        if o.get("btts_no_odds"):
            df.at[idx, "BTTS_No_Odds"] = o["btts_no_odds"]

    log.info("merge_odds: matched %d / %d fixtures", matched, len(df))
    return df
