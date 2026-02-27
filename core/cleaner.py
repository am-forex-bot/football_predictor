"""Transform raw football-data.co.uk CSV data into the clean format
used by the prediction engine."""

import logging
import os

import pandas as pd

log = logging.getLogger(__name__)


def _best_odds(df: pd.DataFrame, suffix: str) -> pd.Series:
    """Get best available odds for H/D/A across all bookmakers.

    Checks MaxH/MaxD/MaxA first (football-data.co.uk pre-computed max),
    then falls back to computing max across known bookmaker columns,
    then falls back to B365 alone.
    """
    max_col = f"Max{suffix}"  # e.g. MaxH, MaxD, MaxA
    if max_col in df.columns:
        return pd.to_numeric(df[max_col], errors="coerce")

    # Known bookmaker prefixes on football-data.co.uk
    prefixes = ["B365", "BW", "IW", "PS", "WH", "VC", "LB", "SB"]
    available = []
    for pfx in prefixes:
        col = f"{pfx}{suffix}"
        if col in df.columns:
            available.append(pd.to_numeric(df[col], errors="coerce"))

    if available:
        return pd.concat(available, axis=1).max(axis=1)

    return pd.Series(float("nan"), index=df.index)


def _avg_odds(df: pd.DataFrame, suffix: str) -> pd.Series:
    """Get market average odds. Uses AvgH/D/A if available, else mean of bookmakers."""
    avg_col = f"Avg{suffix}"
    if avg_col in df.columns:
        return pd.to_numeric(df[avg_col], errors="coerce")

    prefixes = ["B365", "BW", "IW", "PS", "WH", "VC"]
    available = []
    for pfx in prefixes:
        col = f"{pfx}{suffix}"
        if col in df.columns:
            available.append(pd.to_numeric(df[col], errors="coerce"))

    if available:
        return pd.concat(available, axis=1).mean(axis=1)

    return pd.Series(float("nan"), index=df.index)


def clean_results(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Extract and rename the columns we need from the raw CSV.

    Returns only completed matches (FTR is not NaN).
    Columns: Team, Opponent, GF, GA, Result,
             Home_Odds, Draw_Odds, Away_Odds (Bet365),
             Max_Home_Odds, Max_Draw_Odds, Max_Away_Odds (best price),
             Avg_Home_Odds, Avg_Draw_Odds, Avg_Away_Odds (market average),
             Pin_Home_Odds, Pin_Draw_Odds, Pin_Away_Odds (Pinnacle)
    """
    required = ["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]

    for col in required:
        if col not in raw_df.columns:
            raise KeyError(f"Missing required column: {col}")

    # Only completed matches
    df = raw_df[raw_df["FTR"].notna() & (raw_df["FTR"] != "")].copy()

    result = pd.DataFrame()
    result["Team"] = df["HomeTeam"]
    result["Opponent"] = df["AwayTeam"]
    result["GF"] = pd.to_numeric(df["FTHG"], errors="coerce")
    result["GA"] = pd.to_numeric(df["FTAG"], errors="coerce")

    # Preserve match date for proper gameweek grouping
    if "Date" in df.columns:
        result["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    elif "date" in df.columns:
        result["Date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")

    # H → W (home team won), A → L (home team lost), D stays
    result["Result"] = df["FTR"].replace({"H": "W", "A": "L"})

    # Bet365 odds (primary — always present on football-data.co.uk)
    for src, dst in [("B365H", "Home_Odds"), ("B365D", "Draw_Odds"), ("B365A", "Away_Odds")]:
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src], errors="coerce")
        else:
            result[dst] = float("nan")

    # Max odds — set to Bet365 (same as Home_Odds) so value calculations
    # and backtests use the odds the user can actually get, not inflated
    # best-across-all-bookmakers prices they can't bet on.
    for src_dst in [("Home_Odds", "Max_Home_Odds"),
                    ("Draw_Odds", "Max_Draw_Odds"),
                    ("Away_Odds", "Max_Away_Odds")]:
        result[src_dst[1]] = result[src_dst[0]]

    # Market average odds
    for suffix, dst in [("H", "Avg_Home_Odds"), ("D", "Avg_Draw_Odds"), ("A", "Avg_Away_Odds")]:
        result[dst] = _avg_odds(df, suffix).values

    # Pinnacle odds (sharpest line — best for implied probability)
    for src, dst in [("PSH", "Pin_Home_Odds"), ("PSD", "Pin_Draw_Odds"), ("PSA", "Pin_Away_Odds")]:
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src], errors="coerce")
        else:
            result[dst] = float("nan")

    # Match stats (shots, corners, cards) — available on most football-data.co.uk files
    stat_cols = [
        ("HS", "Home_Shots"), ("AS", "Away_Shots"),
        ("HST", "Home_SOT"), ("AST", "Away_SOT"),
        ("HC", "Home_Corners"), ("AC", "Away_Corners"),
        ("HF", "Home_Fouls"), ("AF", "Away_Fouls"),
        ("HY", "Home_Yellows"), ("AY", "Away_Yellows"),
        ("HR", "Home_Reds"), ("AR", "Away_Reds"),
    ]
    for src, dst in stat_cols:
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src], errors="coerce")

    return result.reset_index(drop=True)


def _detect_column_shift(raw_df: pd.DataFrame) -> bool:
    """Detect if football-data.co.uk CSV has column misalignment.

    This happens when the fixtures.csv has one fewer empty field than the header
    expects (e.g. FTHG and FTAG are empty but FTR's empty field is missing).
    Result: FTR gets the B365H value, all subsequent columns shift left by 1.

    Returns True if the FTR column appears to contain odds values (float > 1.0)
    rather than match results ('H', 'D', 'A').
    """
    if "FTR" not in raw_df.columns:
        return False

    ftr = raw_df["FTR"]
    # Valid FTR values are: NaN, '', 'H', 'D', 'A'
    # If FTR has float values > 1.0, it's probably B365H (column shift)
    ftr_numeric = pd.to_numeric(ftr, errors="coerce")
    n_numeric = ftr_numeric.notna().sum()
    if n_numeric == 0:
        return False

    # If any FTR value is numeric and > 1.0, it's likely odds, not a result
    if (ftr_numeric > 1.0).any():
        return True

    return False


def _fix_column_shift(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Fix column shift in football-data.co.uk fixtures.csv.

    When the CSV is missing one empty field (FTR), all columns from FTR onwards
    are shifted left by 1. Fix by inserting a NaN FTR and shifting data right.
    """
    df = raw_df.copy()
    cols = list(df.columns)

    try:
        ftr_idx = cols.index("FTR")
    except ValueError:
        return df

    # The current FTR column has what should be in the NEXT column (B365H).
    # Shift: save current values, then shift each column right by 1 from FTR.
    shifted_cols = cols[ftr_idx:]  # FTR, B365H, B365D, B365A, ...

    # Shift values: col[n] gets col[n-1]'s values, from right to left
    for i in range(len(shifted_cols) - 1, 0, -1):
        df[shifted_cols[i]] = df[shifted_cols[i - 1]].values

    # FTR itself becomes NaN (it's a fixture, no result)
    df["FTR"] = float("nan")

    return df


def extract_fixtures(raw_df: pd.DataFrame,
                     all_are_fixtures: bool = False) -> pd.DataFrame:
    """Extract upcoming fixtures (rows where FTR is NaN but teams exist).

    Handles both formats:
    - Season CSV: has FTR column, fixtures are rows where FTR is empty
    - Dedicated fixtures.csv: may not have FTR at all, all rows are fixtures

    Args:
        all_are_fixtures: If True, treat ALL rows as fixtures (skip FTR check).
            Use this when the input is from a dedicated fixtures source.

    Prefers future-dated matches, but falls back to all unresulted matches
    if no future fixtures exist yet (e.g. when results haven't been updated).
    """
    if raw_df.empty:
        return pd.DataFrame(columns=["Team", "Opponent"])

    # Detect and fix column misalignment in football-data fixtures.csv.
    # This happens when the CSV has one fewer empty field than the header,
    # causing FTR to get the B365H value and all odds to shift left.
    if _detect_column_shift(raw_df):
        log.warning("Column shift detected: FTR has odds values (e.g. %s). "
                    "Fixing alignment.",
                    raw_df["FTR"].dropna().head(3).tolist())
        raw_df = _fix_column_shift(raw_df)
        # After fix, all rows are fixtures (FTR is now NaN)
        all_are_fixtures = True

    # Determine home/away column names
    if "HomeTeam" in raw_df.columns:
        home_col, away_col = "HomeTeam", "AwayTeam"
    elif "Team" in raw_df.columns:
        home_col, away_col = "Team", "Opponent"
    else:
        return pd.DataFrame(columns=["Team", "Opponent"])

    has_ftr = "FTR" in raw_df.columns
    if all_are_fixtures:
        mask = pd.Series(True, index=raw_df.index)
    elif has_ftr:
        mask = raw_df["FTR"].isna() | (raw_df["FTR"] == "")
    else:
        # No FTR column = all rows are fixtures
        mask = pd.Series(True, index=raw_df.index)

    mask &= raw_df[home_col].notna()
    mask &= raw_df[away_col].notna()
    df = raw_df.loc[mask].copy()

    b365_present = "B365H" in df.columns
    n_b365_before = int(df["B365H"].notna().sum()) if b365_present else 0
    log.info("extract_fixtures: %d rows selected (all_fixtures=%s, FTR col=%s), "
             "B365H=%s (%d non-null)",
             len(df), all_are_fixtures, has_ftr, b365_present, n_b365_before)

    # Safety check: if FTR filter excluded everything but B365 data exists
    # in the original df, we likely have a column issue — retry without FTR
    if len(df) == 0 and not all_are_fixtures and "B365H" in raw_df.columns:
        n_raw_b365 = int(raw_df["B365H"].notna().sum())
        if n_raw_b365 > 0:
            log.warning("FTR filter excluded ALL rows but B365H has %d values. "
                        "Retrying without FTR filter.", n_raw_b365)
            mask = raw_df[home_col].notna() & raw_df[away_col].notna()
            df = raw_df.loc[mask].copy()

    # Try to filter to future-only matches
    date_col = None
    for col in ("Date", "date"):
        if col in df.columns:
            date_col = col
            break

    is_future_only = False
    if date_col is not None:
        dates = pd.to_datetime(df[date_col], dayfirst=True, errors="coerce")
        tomorrow = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
        future_mask = dates.isna() | (dates >= tomorrow)
        future_df = df.loc[future_mask]

        n_b365_future = int(future_df["B365H"].notna().sum()) if b365_present and not future_df.empty else 0
        log.info("extract_fixtures: %d future rows (of %d), B365H non-null=%d",
                 len(future_df), len(df), n_b365_future)

        if len(future_df) > 0:
            # We have genuine future fixtures — use only those
            df = future_df
            is_future_only = True
        # else: no future fixtures yet, keep all unresulted as fallback

    result = pd.DataFrame()
    result["Team"] = df[home_col].values
    result["Opponent"] = df[away_col].values

    # Preserve date for display
    if date_col is not None and date_col in df.columns:
        result["Date"] = pd.to_datetime(df[date_col].values, dayfirst=True, errors="coerce")

    # Flag whether these are confirmed future or possibly already played
    result["_future_only"] = is_future_only

    # Bet365 odds — 1X2
    for src, dst in [("B365H", "Home_Odds"), ("B365D", "Draw_Odds"), ("B365A", "Away_Odds")]:
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src].values, errors="coerce")

    # Bet365 Over/Under 2.5 odds (football-data.co.uk fixtures.csv uses B365>2.5 / B365<2.5)
    for src, dst in [("B365>2.5", "Over_25_Odds"), ("B365<2.5", "Under_25_Odds")]:
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src].values, errors="coerce")

    # Max odds = same as B365 (user only uses Bet365)
    for src_dst in [("Home_Odds", "Max_Home_Odds"),
                    ("Draw_Odds", "Max_Draw_Odds"),
                    ("Away_Odds", "Max_Away_Odds")]:
        if src_dst[0] in result.columns:
            result[src_dst[1]] = result[src_dst[0]]

    # Market average odds
    for suffix, dst in [("H", "Avg_Home_Odds"), ("D", "Avg_Draw_Odds"), ("A", "Avg_Away_Odds")]:
        result[dst] = _avg_odds(df, suffix).values

    n_home_odds = int(result["Home_Odds"].notna().sum()) if "Home_Odds" in result.columns else 0
    log.info("extract_fixtures: result has %d rows, %d with Home_Odds",
             len(result), n_home_odds)

    return result.reset_index(drop=True)


def build_league_table(results_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate league standings from the cleaned results data.

    Each row in results_df represents a home match: Team (home) vs Opponent (away).
    We derive both teams' stats from each row.
    """
    stats: dict[str, dict] = {}

    def _ensure(team: str):
        if team not in stats:
            stats[team] = {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0}

    for _, row in results_df.iterrows():
        home = row["Team"]
        away = row["Opponent"]
        gf = int(row["GF"]) if pd.notna(row["GF"]) else 0
        ga = int(row["GA"]) if pd.notna(row["GA"]) else 0
        result = row["Result"]

        _ensure(home)
        _ensure(away)

        stats[home]["P"] += 1
        stats[away]["P"] += 1
        stats[home]["GF"] += gf
        stats[home]["GA"] += ga
        stats[away]["GF"] += ga
        stats[away]["GA"] += gf

        if result == "W":
            stats[home]["W"] += 1
            stats[away]["L"] += 1
        elif result == "L":
            stats[away]["W"] += 1
            stats[home]["L"] += 1
        else:  # Draw
            stats[home]["D"] += 1
            stats[away]["D"] += 1

    rows = []
    for team, s in stats.items():
        pts = s["W"] * 3 + s["D"]
        gd = s["GF"] - s["GA"]
        rows.append({
            "Team": team,
            "P": s["P"],
            "W": s["W"],
            "D": s["D"],
            "L": s["L"],
            "GF": s["GF"],
            "GA": s["GA"],
            "GD": gd,
            "Pts": pts,
        })

    table = pd.DataFrame(rows)
    table = table.sort_values(
        by=["Pts", "GD", "GF"], ascending=[False, False, False]
    ).reset_index(drop=True)
    table.insert(0, "Position", range(1, len(table) + 1))
    return table


def combine_seasons(season_data: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    """Combine multiple seasons into one results DataFrame with Season column.

    season_data: [(season_code, raw_df), ...] in chronological order (oldest first).
    Each season's matches are cleaned and tagged with their season code.
    """
    all_results = []
    for season_code, raw_df in season_data:
        try:
            cleaned = clean_results(raw_df)
            cleaned["Season"] = season_code
            all_results.append(cleaned)
        except (KeyError, ValueError):
            continue  # skip seasons with bad data

    if not all_results:
        return pd.DataFrame()

    return pd.concat(all_results, ignore_index=True)


def assign_gameweeks(results_df: pd.DataFrame, max_gap_days: int = 4) -> pd.Series:
    """Assign gameweek numbers based on Friday-to-Thursday calendar weeks.

    All matches from Friday 00:00 to Thursday 23:59 belong to the same
    gameweek. This naturally groups weekend + midweek fixtures together,
    meaning a double-header week could have 13+ games — the system handles
    this by allowing variable-size gameweeks.

    If no Date column exists, falls back to chunking by n_teams/2.

    Returns a Series of gameweek numbers (1-indexed) aligned with results_df index.
    """
    if "Date" not in results_df.columns or results_df["Date"].isna().all():
        # Fallback: chunk by number of teams
        teams = set(results_df["Team"].unique()) | set(results_df["Opponent"].unique())
        gpw = max(len(teams) // 2, 1)
        return pd.Series(
            [i // gpw + 1 for i in range(len(results_df))],
            index=results_df.index,
        )

    dates = pd.to_datetime(results_df["Date"], errors="coerce")

    # Convert each date to its Friday-Thursday week number.
    # Friday = weekday 4. Shifting by 3 days maps Fri→Mon of that week,
    # so all days Fri-Thu get the same isocalendar week.
    shifted = dates - pd.Timedelta(days=4)  # Fri→Mon, Sat→Tue, ..., Thu→Sun
    # Use (year, week) tuples as grouping keys
    week_keys = shifted.apply(
        lambda d: (d.isocalendar()[0], d.isocalendar()[1]) if pd.notna(d) else None
    )

    # Assign sequential gameweek numbers
    gw_labels = pd.Series(0, index=results_df.index, dtype=int)
    seen_weeks: dict = {}
    current_gw = 0

    for idx in results_df.index:
        wk = week_keys[idx]
        if wk is None:
            gw_labels[idx] = current_gw if current_gw > 0 else 1
            continue
        if wk not in seen_weeks:
            current_gw += 1
            seen_weeks[wk] = current_gw
        gw_labels[idx] = seen_weeks[wk]

    return gw_labels


def save_workbook(results_df: pd.DataFrame, fixtures_df: pd.DataFrame,
                  league_table_df: pd.DataFrame, path: str,
                  backtest_results_df: pd.DataFrame | None = None):
    """Save DataFrames into a single Excel workbook.

    If backtest_results_df is provided (multi-season), saves it as a separate
    'Backtest Results' sheet for thorough backtesting.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        results_df.to_excel(writer, sheet_name="Results", index=False)
        fixtures_df.to_excel(writer, sheet_name="Fixtures", index=False)
        league_table_df.to_excel(writer, sheet_name="League Table", index=False)
        if backtest_results_df is not None and not backtest_results_df.empty:
            backtest_results_df.to_excel(writer, sheet_name="Backtest Results", index=False)


def process_and_save(raw_df: pd.DataFrame, fixtures_raw_df: pd.DataFrame | None,
                     output_path: str,
                     season_data: list[tuple[str, pd.DataFrame]] | None = None) -> dict:
    """Full pipeline: clean results, extract/merge fixtures, build table, save.

    fixtures_raw_df: dedicated fixtures DataFrame (already filtered to this league).
    season_data: optional list of (season_code, raw_df) for multi-season backtest data.
    Returns a summary dict with counts.
    """
    results = clean_results(raw_df)
    table = build_league_table(results)

    # Fixtures from the season CSV (rows with no result yet)
    fixtures_from_csv = extract_fixtures(raw_df)

    # Fixtures from the dedicated fixtures.csv (if provided)
    if fixtures_raw_df is not None and not fixtures_raw_df.empty:
        # Log incoming data to diagnose odds pipeline
        b365_in_raw = "B365H" in fixtures_raw_df.columns
        n_b365_raw = int(fixtures_raw_df["B365H"].notna().sum()) if b365_in_raw else 0
        log.info("process_and_save: fixtures_raw_df has %d rows, B365H present=%s, "
                 "B365H non-null=%d, columns=%s",
                 len(fixtures_raw_df), b365_in_raw, n_b365_raw,
                 [c for c in fixtures_raw_df.columns if "B365" in str(c) or "Home" in str(c)])

        fixtures_extra = extract_fixtures(fixtures_raw_df, all_are_fixtures=True)

        odds_in_extra = "Home_Odds" in fixtures_extra.columns
        n_odds_extra = int(fixtures_extra["Home_Odds"].notna().sum()) if odds_in_extra else 0
        log.info("process_and_save: after extract_fixtures → %d rows, "
                 "Home_Odds present=%s, Home_Odds non-null=%d",
                 len(fixtures_extra), odds_in_extra, n_odds_extra)

        # Merge and deduplicate — put fixtures_extra FIRST because it has
        # Bet365 odds from football-data.co.uk fixtures.csv.
        # drop_duplicates keeps the first occurrence, so the version WITH
        # odds wins over the season CSV version (which has no odds).
        fixtures = pd.concat([fixtures_extra, fixtures_from_csv], ignore_index=True)
        fixtures = fixtures.drop_duplicates(subset=["Team", "Opponent"]).reset_index(drop=True)

        # Final check
        n_final = int(fixtures["Home_Odds"].notna().sum()) if "Home_Odds" in fixtures.columns else 0
        log.info("process_and_save: final fixtures=%d, Home_Odds non-null=%d", len(fixtures), n_final)
    else:
        fixtures = fixtures_from_csv

    # Multi-season backtest data
    backtest_df = None
    n_seasons = 1
    if season_data and len(season_data) > 1:
        backtest_df = combine_seasons(season_data)
        n_seasons = len(season_data)

    save_workbook(results, fixtures.drop(columns=["_future_only"], errors="ignore"),
                 table, output_path, backtest_df)

    return {
        "results_count": len(results),
        "fixtures_count": len(fixtures),
        "teams": len(table),
        "backtest_matches": len(backtest_df) if backtest_df is not None else len(results),
        "n_seasons": n_seasons,
    }
