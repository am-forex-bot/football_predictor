"""Download match data from football-data.co.uk and fixtures from openfootball.

Results come from football-data.co.uk season CSVs.
Fixtures (upcoming matches) come from football-data.co.uk fixtures.csv
(primary — includes Bet365 odds) supplemented by openfootball/football.json.
"""

import json
import logging
import random
import time
from io import StringIO

import pandas as pd
import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal

log = logging.getLogger(__name__)

from core.leagues import (get_results_url, get_past_season_codes, season_display,
                         get_of_json, get_current_season_code, OPENFOOTBALL_TEAM_MAP)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
]

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
OPENFOOTBALL_BASE = "https://raw.githubusercontent.com/openfootball/football.json/master"


def _fetch_csv(url: str, retries: int = 5) -> str:
    """Download a CSV from the given URL with retry and UA rotation."""
    session = requests.Session()
    for attempt in range(retries):
        session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.text
            raise requests.HTTPError(f"HTTP {resp.status_code}")
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Failed to download {url} after {retries} attempts: {exc}") from exc
            time.sleep(2 ** attempt + random.uniform(0, 1))
    raise RuntimeError(f"Failed to download {url}")


def _parse_csv_text(text: str) -> pd.DataFrame:
    """Parse CSV text, handling BOM and encoding issues."""
    if text.startswith("\ufeff"):
        text = text[1:]
    return pd.read_csv(StringIO(text))


def download_results(league_code: str, season: str | None = None) -> pd.DataFrame:
    """Download a league's season CSV and return as DataFrame."""
    url = get_results_url(league_code, season)
    text = _fetch_csv(url)
    return _parse_csv_text(text)


def download_results_multi(league_code: str, n_seasons: int = 5,
                           progress_callback=None) -> list[tuple[str, pd.DataFrame]]:
    """Download multiple seasons. Returns [(season_code, df), ...] oldest first.

    Skips seasons that fail (e.g. league didn't exist yet) and continues.
    """
    codes = get_past_season_codes(n_seasons)
    results = []
    for i, code in enumerate(reversed(codes)):  # oldest first
        if progress_callback:
            progress_callback(f"Downloading {season_display(code)} ({i+1}/{n_seasons})...")
        try:
            df = download_results(league_code, code)
            if len(df) > 0:
                results.append((code, df))
        except Exception:
            if progress_callback:
                progress_callback(f"  Season {season_display(code)} not available, skipping")
    return results


def download_fixtures() -> pd.DataFrame:
    """Download the global fixtures.csv from football-data.co.uk."""
    text = _fetch_csv(FIXTURES_URL)
    return _parse_csv_text(text)


def _merge_fixtures_with_odds(of_df: pd.DataFrame, fd_df: pd.DataFrame) -> pd.DataFrame:
    """Merge football-data.co.uk fixtures (with Bet365 odds) and openfootball fixtures.

    Football-data.co.uk fixtures.csv is PRIMARY because it carries Bet365 odds
    (B365H, B365D, B365A, B365>2.5, B365<2.5, etc.).
    Openfootball supplements with additional fixtures not in football-data.

    Previous approach used a LEFT join from openfootball, which silently lost
    all Bet365 odds whenever team names didn't match perfectly between sources.
    New approach: keep football-data rows intact, append openfootball extras.
    """
    if fd_df.empty:
        return of_df
    if of_df.empty:
        return fd_df

    # Log what we're merging
    b365_col = "B365H" if "B365H" in fd_df.columns else None
    if b365_col:
        n_with_odds = int(fd_df[b365_col].notna().sum())
        log.info("Merge: football-data has %d/%d fixtures with B365 odds",
                 n_with_odds, len(fd_df))
    else:
        log.info("Merge: football-data has %d fixtures but NO B365H column "
                 "(columns: %s)", len(fd_df), list(fd_df.columns)[:10])

    # Football-data is primary (has odds) — keep ALL its rows intact
    fd_keys = set(zip(fd_df["HomeTeam"], fd_df["AwayTeam"]))

    # Find openfootball fixtures NOT already in football-data
    of_only = of_df[
        ~of_df.apply(
            lambda r: (r["HomeTeam"], r["AwayTeam"]) in fd_keys, axis=1
        )
    ]

    if not of_only.empty:
        log.info("Merge: adding %d openfootball-only fixtures (no odds)", len(of_only))
        return pd.concat([fd_df, of_only], ignore_index=True)

    log.info("Merge: all openfootball fixtures already in football-data")
    return fd_df


def download_fixtures_openfootball(league_code: str) -> pd.DataFrame:
    """Download fixtures from openfootball/football.json on GitHub.

    This is the primary fixture source — it's a community-maintained dataset
    on GitHub that covers all major European leagues and is reliably accessible.

    Returns a DataFrame with HomeTeam, AwayTeam, Date columns
    (team names mapped to football-data.co.uk convention).
    Returns empty DataFrame if not available for this league.
    """
    of_json = get_of_json(league_code)
    if not of_json:
        return pd.DataFrame()

    season = get_current_season_code()
    start_year = 2000 + int(season[:2])
    end_year = start_year + 1
    # openfootball uses "2025-26" format
    season_dir = f"{start_year}-{end_year % 100:02d}"

    # Try multiple URL patterns — openfootball repo structure can vary
    urls_to_try = [
        f"{OPENFOOTBALL_BASE}/{season_dir}/{of_json}",
        # Some repos use full-year format
        f"{OPENFOOTBALL_BASE}/{start_year}-{end_year}/{of_json}",
    ]

    data = None
    for url in urls_to_try:
        try:
            text = _fetch_csv(url, retries=2)
            data = json.loads(text)
            if data.get("matches"):
                break
        except Exception:
            continue

    if not data:
        return pd.DataFrame()

    # openfootball may nest matches inside "rounds"
    matches = data.get("matches", [])
    if not matches and "rounds" in data:
        for rnd in data["rounds"]:
            matches.extend(rnd.get("matches", []))

    if not matches:
        return pd.DataFrame()

    # Filter to unplayed matches (no score or no full-time score)
    unplayed = []
    for m in matches:
        score = m.get("score")
        if not score or not score.get("ft"):
            unplayed.append(m)

    if not unplayed:
        return pd.DataFrame()

    rows = []
    for m in unplayed:
        home = m.get("team1", "")
        away = m.get("team2", "")
        date_str = m.get("date", "")

        # Map openfootball names to football-data.co.uk names
        home_mapped = OPENFOOTBALL_TEAM_MAP.get(home, home)
        away_mapped = OPENFOOTBALL_TEAM_MAP.get(away, away)

        rows.append({
            "Div": league_code,
            "Date": date_str,
            "HomeTeam": home_mapped,
            "AwayTeam": away_mapped,
            "FTR": "",
        })

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# QThread workers for non-blocking GUI downloads
# ---------------------------------------------------------------------------

class DownloadWorker(QObject):
    """Runs downloads in a background thread, emitting progress signals."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, league_code: str, n_seasons: int = 1, season: str | None = None):
        super().__init__()
        self.league_code = league_code
        self.n_seasons = n_seasons
        self.season = season

    def run(self):
        try:
            if self.n_seasons > 1:
                # Multi-season download
                self.progress.emit(
                    f"Downloading {self.n_seasons} seasons for {self.league_code}..."
                )
                season_data = download_results_multi(
                    self.league_code, self.n_seasons,
                    progress_callback=lambda msg: self.progress.emit(msg),
                )
                self.progress.emit(
                    f"  Got {len(season_data)} seasons of data"
                )

                # Current season is the last one (most recent)
                current_df = season_data[-1][1] if season_data else pd.DataFrame()
            else:
                self.progress.emit(f"Downloading results for {self.league_code}...")
                current_df = download_results(self.league_code, self.season)
                season_data = None  # single season mode

            total = len(current_df)
            played = current_df["FTR"].notna().sum() if "FTR" in current_df.columns else 0
            upcoming = total - played
            self.progress.emit(
                f"  Current season: {played} played, {upcoming} upcoming."
            )

            # Download fixtures from openfootball (comprehensive fixture list)
            self.progress.emit("Downloading fixtures from openfootball...")
            of_fixtures = pd.DataFrame()
            try:
                of_fixtures = download_fixtures_openfootball(self.league_code)
                if not of_fixtures.empty:
                    self.progress.emit(
                        f"  Fixtures: {len(of_fixtures)} upcoming from openfootball"
                    )
                else:
                    self.progress.emit("  No fixtures from openfootball for this league.")
            except Exception as e:
                self.progress.emit(f"  Warning: openfootball failed: {e}")

            # Always try football-data.co.uk for bookmaker odds (PRIMARY source)
            self.progress.emit("Downloading Bet365 odds from football-data.co.uk...")
            fd_fixtures = pd.DataFrame()
            try:
                all_fixtures = download_fixtures()
                if "Div" in all_fixtures.columns:
                    fd_fixtures = all_fixtures[
                        all_fixtures["Div"] == self.league_code
                    ].copy()
                    if not fd_fixtures.empty:
                        # Report which B365 columns are present
                        b365_cols = [c for c in fd_fixtures.columns if c.startswith("B365")]
                        n_b365 = int(fd_fixtures["B365H"].notna().sum()) if "B365H" in fd_fixtures.columns else 0
                        self.progress.emit(
                            f"  football-data: {len(fd_fixtures)} fixtures, "
                            f"{n_b365} with B365 odds  "
                            f"(columns: {', '.join(b365_cols) or 'none'})"
                        )
                    else:
                        self.progress.emit("  No odds data for this league on football-data.")
                else:
                    self.progress.emit("  Odds source: no Div column found.")
            except Exception as e:
                self.progress.emit(f"  football-data download failed: {e}")

            # Combine fixtures: football-data (with odds) is PRIMARY,
            # openfootball supplements with extra fixtures.
            if not fd_fixtures.empty and not of_fixtures.empty:
                league_fixtures = _merge_fixtures_with_odds(of_fixtures, fd_fixtures)
                n_b365 = int(league_fixtures["B365H"].notna().sum()) if "B365H" in league_fixtures.columns else 0
                self.progress.emit(
                    f"  Combined: {len(league_fixtures)} total fixtures, "
                    f"{n_b365} with Bet365 odds"
                )
            elif not fd_fixtures.empty:
                league_fixtures = fd_fixtures
                n_b365 = int(fd_fixtures["B365H"].notna().sum()) if "B365H" in fd_fixtures.columns else 0
                self.progress.emit(
                    f"  Using {len(fd_fixtures)} football-data fixtures ({n_b365} with B365 odds)"
                )
            elif not of_fixtures.empty:
                league_fixtures = of_fixtures
                self.progress.emit(
                    f"  Using {len(of_fixtures)} openfootball fixtures (no odds)"
                )
            else:
                league_fixtures = pd.DataFrame()
                self.progress.emit("  No fixtures found from any source.")

            self.finished.emit({
                "results": current_df,
                "fixtures": league_fixtures,
                "season_data": season_data,  # list of (code, df) or None
            })
        except Exception as exc:
            self.error.emit(str(exc))


def start_download(league_code: str, n_seasons: int = 1,
                   season: str | None = None) -> tuple[QThread, DownloadWorker]:
    """Create and start a download worker thread. Returns (thread, worker)."""
    thread = QThread()
    worker = DownloadWorker(league_code, n_seasons=n_seasons, season=season)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.start()
    return thread, worker
