"""Transform raw football-data.co.uk CSV data into the clean format
used by the prediction engine."""

import os

import pandas as pd


def clean_results(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Extract and rename the columns we need from the raw CSV.

    Returns only completed matches (FTR is not NaN).
    Columns: Team, Opponent, GF, GA, Result, Home_Odds, Draw_Odds, Away_Odds
    """
    # Use column names rather than positional indices for robustness
    required = ["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]
    odds_cols = ["B365H", "B365D", "B365A"]

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

    # H → W (home team won), A → L (home team lost), D stays
    result["Result"] = df["FTR"].replace({"H": "W", "A": "L"})

    # Odds — may be missing in some rows
    for src, dst in zip(odds_cols, ["Home_Odds", "Draw_Odds", "Away_Odds"]):
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src], errors="coerce")
        else:
            result[dst] = float("nan")

    return result.reset_index(drop=True)


def extract_fixtures(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Extract upcoming fixtures (rows where FTR is NaN but teams exist).

    Handles both formats:
    - Season CSV: has FTR column, fixtures are rows where FTR is empty
    - Dedicated fixtures.csv: may not have FTR at all, all rows are fixtures
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

    result = pd.DataFrame()
    result["Team"] = df[home_col].values
    result["Opponent"] = df[away_col].values

    for src, dst in [("B365H", "Home_Odds"), ("B365D", "Draw_Odds"), ("B365A", "Away_Odds")]:
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src].values, errors="coerce")

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


def save_workbook(results_df: pd.DataFrame, fixtures_df: pd.DataFrame,
                  league_table_df: pd.DataFrame, path: str):
    """Save all three DataFrames into a single Excel workbook."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        results_df.to_excel(writer, sheet_name="Results", index=False)
        fixtures_df.to_excel(writer, sheet_name="Fixtures", index=False)
        league_table_df.to_excel(writer, sheet_name="League Table", index=False)


def process_and_save(raw_df: pd.DataFrame, fixtures_raw_df: pd.DataFrame | None,
                     output_path: str) -> dict:
    """Full pipeline: clean results, extract/merge fixtures, build table, save.

    fixtures_raw_df: dedicated fixtures DataFrame (already filtered to this league).
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

    save_workbook(results, fixtures, table, output_path)

    return {
        "results_count": len(results),
        "fixtures_count": len(fixtures),
        "teams": len(table),
    }
