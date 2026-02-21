"""Download match data from football-data.co.uk.

Downloads both the season results CSV (which may contain upcoming fixtures
as rows with no FTR) AND the dedicated fixtures.csv which has all upcoming
fixtures across all leagues.
"""

import random
import time
from io import StringIO

import pandas as pd
import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.leagues import get_results_url

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
]

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"


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


def download_fixtures() -> pd.DataFrame:
    """Download the global fixtures.csv from football-data.co.uk."""
    text = _fetch_csv(FIXTURES_URL)
    return _parse_csv_text(text)


# ---------------------------------------------------------------------------
# QThread workers for non-blocking GUI downloads
# ---------------------------------------------------------------------------

class DownloadWorker(QObject):
    """Runs downloads in a background thread, emitting progress signals."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, league_code: str, season: str | None = None):
        super().__init__()
        self.league_code = league_code
        self.season = season

    def run(self):
        try:
            self.progress.emit(f"Downloading results for {self.league_code}...")
            results_df = download_results(self.league_code, self.season)
            total = len(results_df)
            played = results_df["FTR"].notna().sum()
            upcoming = total - played
            self.progress.emit(
                f"  Results: {played} played, {upcoming} upcoming in season CSV."
            )

            # Also download the dedicated fixtures file
            self.progress.emit("Downloading fixtures.csv (all leagues)...")
            try:
                fixtures_df = download_fixtures()
                if "Div" in fixtures_df.columns:
                    league_fixtures = fixtures_df[
                        fixtures_df["Div"] == self.league_code
                    ].copy()
                    self.progress.emit(
                        f"  Fixtures: {len(league_fixtures)} upcoming for {self.league_code} "
                        f"(from {len(fixtures_df)} total across all leagues)."
                    )
                else:
                    league_fixtures = fixtures_df
                    self.progress.emit(
                        f"  Fixtures: {len(fixtures_df)} rows (no Div column to filter)."
                    )
            except Exception as e:
                self.progress.emit(f"  Warning: Could not download fixtures.csv: {e}")
                league_fixtures = pd.DataFrame()

            self.finished.emit({
                "results": results_df,
                "fixtures": league_fixtures,
            })
        except Exception as exc:
            self.error.emit(str(exc))


def start_download(league_code: str, season: str | None = None) -> tuple[QThread, DownloadWorker]:
    """Create and start a download worker thread. Returns (thread, worker)."""
    thread = QThread()
    worker = DownloadWorker(league_code, season)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.start()
    return thread, worker
