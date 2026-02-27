"""Transform raw football-data.co.uk CSV data into the clean format
used by the prediction engine."""

import os

import pandas as pd


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

    # Best available odds across all bookmakers (what a real punter shops for)
    for suffix, dst in [("H", "Max_Home_Odds"), ("D", "Max_Draw_Odds"), ("A", "Max_Away_Odds")]:
        result[dst] = _best_odds(df, suffix).values

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


def extract_fixtures(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Extract upcoming fixtures (rows where FTR is NaN but teams exist).

    Handles both formats:
    - Season CSV: has FTR column, fixtures are rows where FTR is empty
    - Dedicated fixtures.csv: may not have FTR at all, all rows are fixtures

    Prefers future-dated matches, but falls back to all unresulted matches
    if no future fixtures exist yet (e.g. when results haven't been updated).
    """
    if raw_df.empty:
        return pd.DataFrame(columns=["Team", "Opponent"])

    # Determine home/away column names
    if "HomeTeam" in raw_df.columns:
        home_col, away_col = "HomeTeam", "AwayTeam"
    elif "Team" in raw_df.columns:
        home_col, away_col = "Team", "Opponent"
    else:
        return pd.DataFrame(columns=["Team", "Opponent"])

    if "FTR" in raw_df.columns:
        mask = raw_df["FTR"].isna() | (raw_df["FTR"] == "")
    else:
        # No FTR column = all rows are fixtures
        mask = pd.Series(True, index=raw_df.index)

    mask &= raw_df[home_col].notna()
    mask &= raw_df[away_col].notna()
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

    # Bet365 odds
    for src, dst in [("B365H", "Home_Odds"), ("B365D", "Draw_Odds"), ("B365A", "Away_Odds")]:
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src].values, errors="coerce")

    # Best available odds
    for suffix, dst in [("H", "Max_Home_Odds"), ("D", "Max_Draw_Odds"), ("A", "Max_Away_Odds")]:
        result[dst] = _best_odds(df, suffix).values

    # Market average odds
    for suffix, dst in [("H", "Avg_Home_Odds"), ("D", "Avg_Draw_Odds"), ("A", "Avg_Away_Odds")]:
        result[dst] = _avg_odds(df, suffix).values

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
        fixtures_extra = extract_fixtures(fixtures_raw_df)
        # Merge and deduplicate
        fixtures = pd.concat([fixtures_from_csv, fixtures_extra], ignore_index=True)
        fixtures = fixtures.drop_duplicates(subset=["Team", "Opponent"]).reset_index(drop=True)
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
