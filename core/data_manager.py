"""Manage downloaded data files — tracking, staleness, and cleanup."""

import json
import os
import shutil
from datetime import datetime, timedelta

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
META_FILE = os.path.join(DATA_DIR, "metadata.json")
STALE_DAYS = 7


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_meta() -> dict:
    _ensure_data_dir()
    if os.path.exists(META_FILE):
        with open(META_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_meta(meta: dict):
    _ensure_data_dir()
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=2, default=str)


def get_workbook_path(league_code: str) -> str:
    """Return the Excel workbook path for a league."""
    _ensure_data_dir()
    return os.path.join(DATA_DIR, f"{league_code}_data.xlsx")


def record_download(league_code: str, league_name: str, results_count: int,
                    fixtures_count: int, teams: int):
    """Record that a league was just downloaded."""
    meta = _load_meta()
    meta[league_code] = {
        "league_name": league_name,
        "downloaded_at": datetime.now().isoformat(),
        "results_count": results_count,
        "fixtures_count": fixtures_count,
        "teams": teams,
        "file": get_workbook_path(league_code),
    }
    _save_meta(meta)


def get_all_downloads() -> dict:
    """Return metadata for all downloaded leagues."""
    return _load_meta()


def get_download_info(league_code: str) -> dict | None:
    """Return metadata for a specific league, or None if not downloaded."""
    meta = _load_meta()
    return meta.get(league_code)


def is_stale(league_code: str) -> bool:
    """Check if a league's data is older than STALE_DAYS."""
    info = get_download_info(league_code)
    if info is None:
        return True
    downloaded = datetime.fromisoformat(info["downloaded_at"])
    return datetime.now() - downloaded > timedelta(days=STALE_DAYS)


def has_data(league_code: str) -> bool:
    """Check if we have a valid workbook for a league."""
    info = get_download_info(league_code)
    if info is None:
        return False
    return os.path.exists(info["file"])


def get_available_leagues() -> list[tuple[str, str]]:
    """Return list of (code, display_name) for leagues with downloaded data."""
    meta = _load_meta()
    available = []
    for code, info in meta.items():
        if os.path.exists(info.get("file", "")):
            available.append((code, info["league_name"]))
    return available


def load_league_data(league_code: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    """Load Results, Fixtures, and League Table from a league's workbook.

    Returns (results_df, fixtures_df, league_table_df) or None if not available.
    """
    path = get_workbook_path(league_code)
    if not os.path.exists(path):
        return None
    results = pd.read_excel(path, sheet_name="Results")
    fixtures = pd.read_excel(path, sheet_name="Fixtures")
    table = pd.read_excel(path, sheet_name="League Table")
    return results, fixtures, table


def clean_league(league_code: str):
    """Remove a single league's data and metadata."""
    meta = _load_meta()
    info = meta.pop(league_code, None)
    if info and os.path.exists(info.get("file", "")):
        os.remove(info["file"])
    _save_meta(meta)


def clean_stale():
    """Remove all stale data (older than STALE_DAYS)."""
    meta = _load_meta()
    to_remove = [code for code in meta if is_stale(code)]
    for code in to_remove:
        clean_league(code)


def clean_all():
    """Wipe the entire data directory."""
    if os.path.exists(DATA_DIR):
        for f in os.listdir(DATA_DIR):
            path = os.path.join(DATA_DIR, f)
            if os.path.isfile(path):
                os.remove(path)
    _save_meta({})
