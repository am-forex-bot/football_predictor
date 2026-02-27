"""Scrape Bet365 odds from Soccerway.com.

Soccerway displays Bet365 pre-match odds on their match pages.
This module fetches those odds as a supplementary source when
the-odds-api doesn't carry Bet365.

Usage:
    from core.soccerway import fetch_soccerway_odds
    odds = fetch_soccerway_odds("E0")  # returns list of dicts
"""

import logging
import re
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

# Soccerway competition URLs — maps football-data league code to Soccerway
# competition path.
_COMPETITION_PATHS = {
    "E0": "/national/england/premier-league/",
    "E1": "/national/england/championship/",
    "E2": "/national/england/league-one/",
    "E3": "/national/england/league-two/",
    "SC0": "/national/scotland/premier-league/",
    "D1": "/national/germany/bundesliga/",
    "D2": "/national/germany/2-bundesliga/",
    "SP1": "/national/spain/primera-division/",
    "SP2": "/national/spain/segunda-division/",
    "I1": "/national/italy/serie-a/",
    "I2": "/national/italy/serie-b/",
    "F1": "/national/france/ligue-1/",
    "F2": "/national/france/ligue-2/",
    "N1": "/national/netherlands/eredivisie/",
    "B1": "/national/belgium/first-division-a/",
    "P1": "/national/portugal/portuguese-liga/",
    "T1": "/national/turkey/super-lig/",
    "G1": "/national/greece/super-league/",
}

# Team name mapping: Soccerway names → football-data.co.uk names
# Only need entries where names differ
_SW_TEAM_MAP = {
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Nottingham Forest": "Nott'm Forest",
    "Tottenham Hotspur": "Tottenham",
    "Newcastle United": "Newcastle",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    "Brighton & Hove Albion": "Brighton",
    "Leicester City": "Leicester",
    "Ipswich Town": "Ipswich",
    "AFC Bournemouth": "Bournemouth",
    "Leeds United": "Leeds",
    "Sheffield United": "Sheffield United",
    "Sheffield Wednesday": "Sheffield Weds",
    "Queens Park Rangers": "QPR",
    "West Bromwich Albion": "West Brom",
    "Stoke City": "Stoke",
    "Swansea City": "Swansea",
    "Cardiff City": "Cardiff",
    "Hull City": "Hull",
    "Bristol City": "Bristol City",
    "Plymouth Argyle": "Plymouth",
    "Preston North End": "Preston",
    "Blackburn Rovers": "Blackburn",
    "Coventry City": "Coventry",
    "Norwich City": "Norwich",
    "Derby County": "Derby",
    "Huddersfield Town": "Huddersfield",
    "Birmingham City": "Birmingham",
    "Bayern Munich": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "Bayer Leverkusen": "Leverkusen",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "Borussia M'gladbach": "M'gladbach",
    "Atlético Madrid": "Ath Madrid",
    "Athletic Club": "Ath Bilbao",
    "Real Sociedad": "Sociedad",
    "Real Betis": "Betis",
    "Celta de Vigo": "Celta",
    "Rayo Vallecano": "Vallecano",
    "Paris Saint-Germain": "Paris SG",
    "Olympique Lyonnais": "Lyon",
    "Olympique de Marseille": "Marseille",
    "Internazionale": "Inter",
    "AC Milan": "Milan",
    "AS Roma": "Roma",
    "SS Lazio": "Lazio",
    "SSC Napoli": "Napoli",
    "Hellas Verona": "Verona",
    "Ajax": "Ajax",
    "PSV": "PSV",
    "Feyenoord": "Feyenoord",
    "Club Brugge": "Club Brugge",
    "RSC Anderlecht": "Anderlecht",
    "Benfica": "Benfica",
    "Porto": "Porto",
    "Sporting CP": "Sporting CP",
}

_BASE_URL = "https://int.soccerway.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

_AJAX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-GB,en;q=0.5",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": _BASE_URL + "/",
}


def _map_team(name: str) -> str:
    """Map a Soccerway team name to football-data.co.uk name."""
    name = name.strip()
    if name in _SW_TEAM_MAP:
        return _SW_TEAM_MAP[name]
    # Try stripping common suffixes
    for suffix in (" FC", " CF", " AFC"):
        stripped = name.removesuffix(suffix)
        if stripped in _SW_TEAM_MAP:
            return _SW_TEAM_MAP[stripped]
    return name


def _parse_odds_from_html(html: str) -> list[dict]:
    """Parse match fixtures with Bet365 odds from Soccerway HTML.

    Soccerway embeds odds in match rows with data attributes or in
    dedicated odds columns. The exact format varies but typically:
    - Match rows contain home/away team names
    - Odds are in <td> elements with class containing 'odds' or 'bet365'
    - Or in data attributes on the row element

    Returns list of dicts with home_team, away_team, home_odds, draw_odds, away_odds.
    """
    results = []

    # Pattern 1: Match rows with embedded odds data
    # Look for table rows containing match data
    # Soccerway typically uses: <td class="team team-a">Home</td>
    # and odds in: <td class="odds">1.50</td>

    # Find all match containers
    match_pattern = re.compile(
        r'<tr[^>]*class="[^"]*(?:match|game)[^"]*"[^>]*>(.*?)</tr>',
        re.DOTALL | re.IGNORECASE,
    )

    team_pattern = re.compile(
        r'<td[^>]*class="[^"]*team[^"]*"[^>]*>.*?'
        r'<a[^>]*>([^<]+)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    odds_pattern = re.compile(
        r'<td[^>]*class="[^"]*odds[^"]*"[^>]*>\s*'
        r'(?:<a[^>]*>)?\s*([\d.]+)\s*(?:</a>)?\s*</td>',
        re.DOTALL | re.IGNORECASE,
    )

    for match in match_pattern.finditer(html):
        row_html = match.group(1)

        teams = team_pattern.findall(row_html)
        odds = odds_pattern.findall(row_html)

        if len(teams) >= 2 and len(odds) >= 3:
            try:
                home = _map_team(teams[0])
                away = _map_team(teams[1])
                h_odds = float(odds[0])
                d_odds = float(odds[1])
                a_odds = float(odds[2])

                if h_odds > 1.0 and d_odds > 1.0 and a_odds > 1.0:
                    results.append({
                        "home_team_raw": teams[0].strip(),
                        "away_team_raw": teams[1].strip(),
                        "home_team": home,
                        "away_team": away,
                        "home_odds": h_odds,
                        "draw_odds": d_odds,
                        "away_odds": a_odds,
                        "over_25_odds": None,
                        "under_25_odds": None,
                        "btts_yes_odds": None,
                        "btts_no_odds": None,
                        "bookmaker": "Bet365 (Soccerway)",
                        "commence_time": "",
                    })
            except (ValueError, IndexError):
                continue

    # Pattern 2: Data attributes on rows (data-odds-home, data-odds-draw, etc.)
    data_pattern = re.compile(
        r'data-home-team="([^"]*)"[^>]*'
        r'data-away-team="([^"]*)"[^>]*'
        r'data-odds-home="([^"]*)"[^>]*'
        r'data-odds-draw="([^"]*)"[^>]*'
        r'data-odds-away="([^"]*)"',
        re.DOTALL | re.IGNORECASE,
    )

    for m in data_pattern.finditer(html):
        try:
            home_raw, away_raw = m.group(1).strip(), m.group(2).strip()
            h_odds = float(m.group(3))
            d_odds = float(m.group(4))
            a_odds = float(m.group(5))

            if h_odds > 1.0 and d_odds > 1.0 and a_odds > 1.0:
                # Check for duplicate
                key = (_map_team(home_raw), _map_team(away_raw))
                if not any((r["home_team"], r["away_team"]) == key for r in results):
                    results.append({
                        "home_team_raw": home_raw,
                        "away_team_raw": away_raw,
                        "home_team": key[0],
                        "away_team": key[1],
                        "home_odds": h_odds,
                        "draw_odds": d_odds,
                        "away_odds": a_odds,
                        "over_25_odds": None,
                        "under_25_odds": None,
                        "btts_yes_odds": None,
                        "btts_no_odds": None,
                        "bookmaker": "Bet365 (Soccerway)",
                        "commence_time": "",
                    })
        except (ValueError, IndexError):
            continue

    # Pattern 3: JSON-LD or inline script data
    json_pattern = re.compile(
        r'"homeTeam"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"[^}]*\}.*?'
        r'"awayTeam"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"[^}]*\}.*?'
        r'"offers"\s*:\s*\[([^\]]*)\]',
        re.DOTALL,
    )

    for m in json_pattern.finditer(html):
        try:
            home_raw = m.group(1).strip()
            away_raw = m.group(2).strip()
            offers = m.group(3)

            # Extract odds from offers JSON
            price_matches = re.findall(r'"price"\s*:\s*([\d.]+)', offers)
            if len(price_matches) >= 3:
                h_odds = float(price_matches[0])
                d_odds = float(price_matches[1])
                a_odds = float(price_matches[2])

                if h_odds > 1.0 and d_odds > 1.0 and a_odds > 1.0:
                    key = (_map_team(home_raw), _map_team(away_raw))
                    if not any((r["home_team"], r["away_team"]) == key for r in results):
                        results.append({
                            "home_team_raw": home_raw,
                            "away_team_raw": away_raw,
                            "home_team": key[0],
                            "away_team": key[1],
                            "home_odds": h_odds,
                            "draw_odds": d_odds,
                            "away_odds": a_odds,
                            "over_25_odds": None,
                            "under_25_odds": None,
                            "btts_yes_odds": None,
                            "btts_no_odds": None,
                            "bookmaker": "Bet365 (Soccerway)",
                            "commence_time": "",
                        })
        except (ValueError, IndexError):
            continue

    return results


def fetch_soccerway_odds(league_code: str,
                         timeout: int = 15) -> dict:
    """Fetch Bet365 odds from Soccerway for a league.

    Returns dict matching the format from odds_provider.fetch_odds():
    {
        "odds": [...],
        "source": "Bet365 (Soccerway)",
        "remaining_requests": "unlimited",
        "used_requests": "N/A",
        "raw_events": N,
    }
    """
    comp_path = _COMPETITION_PATHS.get(league_code)
    if not comp_path:
        return {
            "odds": [],
            "source": f"Soccerway: league {league_code} not mapped",
            "remaining_requests": "unlimited",
            "used_requests": "N/A",
            "raw_events": 0,
        }

    session = requests.Session()
    session.headers.update(_HEADERS)

    # Step 1: Try the competition matches page directly
    url = f"{_BASE_URL}{comp_path}"
    log.info("Soccerway: fetching %s", url)

    try:
        resp = session.get(url, timeout=timeout)
        log.info("Soccerway: %s → %s (%d bytes)",
                 url, resp.status_code, len(resp.content))

        if resp.status_code != 200:
            return {
                "odds": [],
                "source": f"Soccerway: HTTP {resp.status_code}",
                "remaining_requests": "unlimited",
                "used_requests": "N/A",
                "raw_events": 0,
            }

        html = resp.text
        odds = _parse_odds_from_html(html)

        if odds:
            log.info("Soccerway: found %d fixtures with Bet365 odds", len(odds))
            return {
                "odds": odds,
                "source": "Bet365 (Soccerway)",
                "remaining_requests": "unlimited",
                "used_requests": "N/A",
                "raw_events": len(odds),
            }

        # Step 2: Try the AJAX matches endpoint
        # Soccerway loads match data via AJAX block requests
        # Try common block patterns
        for block_id in [
            "page_competition_1_block_competition_matches_summary_9",
            "page_competition_1_block_competition_matches_summary_6",
            "page_competition_1_block_competition_matches_3",
        ]:
            ajax_url = f"{_BASE_URL}/a/block_competition_matches_summary"
            params = {
                "block_id": block_id,
                "callback_params": f'{{"page":"0","block_service_id":"competition_summary_block_competitionmatchessummary"}}',
                "action": "changeFilter",
                "params": '{"filter":"next"}',
            }

            try:
                session.headers.update(_AJAX_HEADERS)
                ajax_resp = session.get(ajax_url, params=params, timeout=timeout)

                if ajax_resp.status_code == 200:
                    try:
                        data = ajax_resp.json()
                        content = ""
                        for cmd in data.get("commands", []):
                            if "content" in cmd.get("parameters", {}):
                                content += cmd["parameters"]["content"]

                        if content:
                            odds = _parse_odds_from_html(content)
                            if odds:
                                log.info("Soccerway AJAX: found %d fixtures", len(odds))
                                return {
                                    "odds": odds,
                                    "source": "Bet365 (Soccerway)",
                                    "remaining_requests": "unlimited",
                                    "used_requests": "N/A",
                                    "raw_events": len(odds),
                                }
                    except (ValueError, KeyError):
                        continue
            except requests.RequestException:
                continue

            # Restore normal headers
            session.headers.update(_HEADERS)

        log.info("Soccerway: no odds found on page or via AJAX")
        return {
            "odds": [],
            "source": "Soccerway: no Bet365 odds found",
            "remaining_requests": "unlimited",
            "used_requests": "N/A",
            "raw_events": 0,
        }

    except requests.RequestException as e:
        log.warning("Soccerway fetch failed: %s", e)
        return {
            "odds": [],
            "source": f"Soccerway: {e}",
            "remaining_requests": "unlimited",
            "used_requests": "N/A",
            "raw_events": 0,
        }


def is_available() -> bool:
    """Quick check if Soccerway is reachable."""
    try:
        resp = requests.head(
            _BASE_URL, headers=_HEADERS, timeout=5, allow_redirects=True
        )
        return resp.status_code < 400
    except requests.RequestException:
        return False
